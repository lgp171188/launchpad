# Copyright 2015-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the internal Git API."""

__metaclass__ = type

from pymacaroons import Macaroon
import six
from six.moves import xmlrpc_client
from testtools.matchers import (
    Equals,
    IsInstance,
    MatchesAll,
    MatchesListwise,
    MatchesSetwise,
    MatchesStructure,
    )
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.buildmaster.enums import BuildStatus
from lp.code.enums import (
    GitGranteeType,
    GitRepositoryType,
    TargetRevisionControlSystems,
    )
from lp.code.errors import GitRepositoryCreationFault
from lp.code.interfaces.codehosting import LAUNCHPAD_SERVICES
from lp.code.interfaces.codeimportjob import ICodeImportJobWorkflow
from lp.code.interfaces.gitcollection import IAllGitRepositories
from lp.code.interfaces.gitjob import IGitRefScanJobSource
from lp.code.interfaces.gitrepository import (
    GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE,
    IGitRepository,
    IGitRepositorySet,
    )
from lp.code.tests.helpers import GitHostingFixture
from lp.registry.enums import TeamMembershipPolicy
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.macaroons.interfaces import (
    BadMacaroonContext,
    IMacaroonIssuer,
    NO_USER,
    )
from lp.services.macaroons.model import MacaroonIssuerBase
from lp.services.webapp.escaping import html_escape
from lp.snappy.interfaces.snap import SNAP_TESTING_FLAGS
from lp.testing import (
    admin_logged_in,
    ANONYMOUS,
    celebrity_logged_in,
    login,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import (
    AppServerLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.xmlrpc import XMLRPCTestTransport
from lp.xmlrpc import faults


def _make_auth_params(requester, can_authenticate=False, macaroon_raw=None):
    auth_params = {"can-authenticate": can_authenticate}
    if requester == LAUNCHPAD_SERVICES:
        auth_params["user"] = LAUNCHPAD_SERVICES
    elif requester is not None:
        auth_params["uid"] = requester.id
    if macaroon_raw is not None:
        auth_params["macaroon"] = macaroon_raw
    return auth_params


@implementer(IMacaroonIssuer)
class DummyMacaroonIssuer(MacaroonIssuerBase):

    identifier = "test"
    _root_secret = "test"
    _verified_user = NO_USER

    def checkIssuingContext(self, context, **kwargs):
        """See `MacaroonIssuerBase`."""
        if not IGitRepository.providedBy(context):
            raise BadMacaroonContext(context)
        return context.id

    def checkVerificationContext(self, context, **kwargs):
        """See `IMacaroonIssuerBase`."""
        if not IGitRepository.providedBy(context):
            raise BadMacaroonContext(context)
        return context

    def verifyPrimaryCaveat(self, verified, caveat_value, context, **kwargs):
        """See `MacaroonIssuerBase`."""
        if context is None:
            # We're only verifying that the macaroon could be valid for some
            # context.
            ok = True
        else:
            ok = caveat_value == str(context.id)
        if ok:
            verified.user = self._verified_user
        return ok


class MatchesFault(MatchesStructure):
    """Match an XML-RPC fault.

    This can be given either::

        - a subclass of LaunchpadFault (matches only the fault code)
        - an instance of Fault (matches the fault code and the fault string
          from this instance exactly)
    """

    def __init__(self, expected_fault):
        fault_matchers = {}
        if (isinstance(expected_fault, six.class_types) and
                issubclass(expected_fault, faults.LaunchpadFault)):
            fault_matchers["faultCode"] = Equals(expected_fault.error_code)
        else:
            fault_matchers["faultCode"] = Equals(expected_fault.faultCode)
            fault_string = expected_fault.faultString
            # XXX cjwatson 2019-09-27: InvalidBranchName.faultString is
            # bytes, so we need this to handle that case.  Should it be?
            if not isinstance(fault_string, six.text_type):
                fault_string = fault_string.decode("UTF-8")
            fault_matchers["faultString"] = Equals(fault_string)
        super(MatchesFault, self).__init__(**fault_matchers)


class TestGitAPIMixin:
    """Helper methods for `IGitAPI` tests, and security-relevant tests."""

    def setUp(self):
        super(TestGitAPIMixin, self).setUp()
        self.git_api = xmlrpc_client.ServerProxy(
            "http://xmlrpc-private.launchpad.test:8087/git",
            transport=XMLRPCTestTransport())
        self.hosting_fixture = self.useFixture(GitHostingFixture())
        self.repository_set = getUtility(IGitRepositorySet)

    def assertFault(self, expected_fault, func, *args, **kwargs):
        """Assert that a call raises the expected fault."""
        fault = self.assertRaises(xmlrpc_client.Fault, func, *args, **kwargs)
        self.assertThat(fault, MatchesFault(expected_fault))
        return fault

    def assertGitRepositoryNotFound(self, requester, path, permission="read",
                                    can_authenticate=False, macaroon_raw=None):
        """Assert that the given path cannot be translated."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate,
            macaroon_raw=macaroon_raw)
        self.assertFault(
            faults.GitRepositoryNotFound(path.strip("/")),
            self.git_api.translatePath, path, permission, auth_params)

    def assertPermissionDenied(self, requester, path,
                               message="Permission denied.",
                               permission="read", can_authenticate=False,
                               macaroon_raw=None):
        """Assert that looking at the given path returns PermissionDenied."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate,
            macaroon_raw=macaroon_raw)
        self.assertFault(
            faults.PermissionDenied(message),
            self.git_api.translatePath, path, permission, auth_params)

    def assertUnauthorized(self, requester, path,
                           message="Authorisation required.",
                           permission="read", can_authenticate=False,
                           macaroon_raw=None):
        """Assert that looking at the given path returns Unauthorized."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate,
            macaroon_raw=macaroon_raw)
        self.assertFault(
            faults.Unauthorized(message),
            self.git_api.translatePath, path, permission, auth_params)

    def assertNotFound(self, requester, path, message, permission="read",
                       can_authenticate=False):
        """Assert that looking at the given path returns NotFound."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate)
        self.assertFault(
            faults.NotFound(message),
            self.git_api.translatePath, path, permission, auth_params)

    def assertInvalidSourcePackageName(self, requester, path, name,
                                       permission="read",
                                       can_authenticate=False):
        """Assert that looking at the given path returns
        InvalidSourcePackageName."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate)
        self.assertFault(
            faults.InvalidSourcePackageName(name),
            self.git_api.translatePath, path, permission, auth_params)

    def assertInvalidBranchName(self, requester, path, message,
                                permission="read", can_authenticate=False):
        """Assert that looking at the given path returns InvalidBranchName."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate)
        self.assertFault(
            faults.InvalidBranchName(Exception(message)),
            self.git_api.translatePath, path, permission, auth_params)

    def assertOopsOccurred(self, requester, path,
                           permission="read", can_authenticate=False):
        """Assert that looking at the given path OOPSes."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate)
        fault = self.assertFault(
            faults.OopsOccurred,
            self.git_api.translatePath, path, permission, auth_params)
        prefix = (
            "An unexpected error has occurred while creating a Git "
            "repository. Please report a Launchpad bug and quote: ")
        self.assertStartsWith(fault.faultString, prefix)
        return fault.faultString[len(prefix):].rstrip(".")

    def assertTranslates(self, requester, path, repository, writable,
                         permission="read", can_authenticate=False,
                         macaroon_raw=None, trailing="", private=False):
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate,
            macaroon_raw=macaroon_raw)
        translation = self.git_api.translatePath(path, permission, auth_params)
        login(ANONYMOUS)
        self.assertEqual(
            {"path": removeSecurityProxy(repository).getInternalPath(),
             "writable": writable, "trailing": trailing, "private": private},
            translation)

    def assertCreates(self, requester, path, can_authenticate=False,
                      private=False):
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate)
        translation = self.git_api.translatePath(path, "write", auth_params)
        login(ANONYMOUS)
        repository = getUtility(IGitRepositorySet).getByPath(
            requester, path.lstrip("/"))
        self.assertIsNotNone(repository)
        self.assertEqual(requester, repository.registrant)
        self.assertEqual(
            {"path": repository.getInternalPath(), "writable": True,
             "trailing": "", "private": private},
            translation)
        self.assertEqual(
            (repository.getInternalPath(),),
            self.hosting_fixture.create.extract_args()[0])
        self.assertEqual(GitRepositoryType.HOSTED, repository.repository_type)
        return repository

    def assertCreatesFromClone(self, requester, path, cloned_from,
                               can_authenticate=False):
        self.assertCreates(requester, path, can_authenticate)
        self.assertEqual(
            {"clone_from": cloned_from.getInternalPath()},
            self.hosting_fixture.create.extract_kwargs()[0])

    def assertHasRefPermissions(self, requester, repository, ref_paths,
                                permissions, macaroon_raw=None):
        auth_params = _make_auth_params(requester, macaroon_raw=macaroon_raw)
        translated_path = removeSecurityProxy(repository).getInternalPath()
        ref_paths = [
            xmlrpc_client.Binary(ref_path) for ref_path in ref_paths]
        results = self.git_api.checkRefPermissions(
            translated_path, ref_paths, auth_params)
        self.assertThat(results, MatchesSetwise(*(
            MatchesListwise([
                MatchesAll(
                    IsInstance(xmlrpc_client.Binary),
                    MatchesStructure.byEquality(data=ref_path)),
                Equals(ref_permissions),
                ])
            for ref_path, ref_permissions in permissions.items())))

    def test_translatePath_private_repository(self):
        requester = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                owner=requester, information_type=InformationType.USERDATA))
        path = u"/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository, True, private=True)

    def test_translatePath_cannot_see_private_repository(self):
        requester = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                information_type=InformationType.USERDATA))
        path = u"/%s" % repository.unique_name
        self.assertGitRepositoryNotFound(requester, path)

    def test_translatePath_anonymous_cannot_see_private_repository(self):
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                information_type=InformationType.USERDATA))
        path = u"/%s" % repository.unique_name
        self.assertGitRepositoryNotFound(None, path, can_authenticate=False)
        self.assertUnauthorized(None, path, can_authenticate=True)

    def test_translatePath_team_unowned(self):
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(self.factory.makePerson())
        repository = self.factory.makeGitRepository(owner=team)
        path = u"/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository, False)
        self.assertPermissionDenied(requester, path, permission="write")

    def test_translatePath_imported(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(
            owner=requester, repository_type=GitRepositoryType.IMPORTED)
        path = u"/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository, False)
        self.assertPermissionDenied(requester, path, permission="write")

    def test_translatePath_create_personal_team_denied(self):
        # translatePath refuses to create a personal repository for a team
        # of which the requester is not a member.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam()
        message = "%s is not a member of %s" % (
            requester.displayname, team.displayname)
        self.assertPermissionDenied(
            requester, u"/~%s/+git/random" % team.name, message=message,
            permission="write")

    def test_translatePath_create_other_user(self):
        # Creating a repository for another user fails.
        requester = self.factory.makePerson()
        other_person = self.factory.makePerson()
        project = self.factory.makeProduct()
        name = self.factory.getUniqueString()
        path = u"/~%s/%s/+git/%s" % (other_person.name, project.name, name)
        message = "%s cannot create Git repositories owned by %s" % (
            requester.displayname, other_person.displayname)
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")

    def test_translatePath_create_project_not_owner(self):
        # Somebody without edit permission on the project cannot create a
        # repository and immediately set it as the default for that project.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        path = u"/%s" % project.name
        message = "%s cannot create Git repositories owned by %s" % (
            requester.displayname, project.owner.displayname)
        initial_count = getUtility(IAllGitRepositories).count()
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")
        # No repository was created.
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count())

    def test_translatePath_grant_to_other(self):
        requester = self.factory.makePerson()
        other_person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/stable/next')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=other_person,
            can_force_push=True)
        path = u"/%s" % repository.unique_name
        self.assertTranslates(
            other_person, path, repository, True, private=False)

    def test_translatePath_grant_but_no_access(self):
        requester = self.factory.makePerson()
        grant_person = self.factory.makePerson()
        other_person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/stable/next')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=grant_person,
            can_force_push=True)
        path = u"/%s" % repository.unique_name
        self.assertTranslates(
            other_person, path, repository, False, private=False)

    def test_translatePath_grant_to_other_private(self):
        requester = self.factory.makePerson()
        other_person = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                owner=requester, information_type=InformationType.USERDATA))
        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/stable/next')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=other_person,
            can_force_push=True)
        path = u"/%s" % repository.unique_name
        self.assertGitRepositoryNotFound(
            other_person, path, can_authenticate=True)

    def _make_scenario_one_repository(self):
        user_a = self.factory.makePerson()
        user_b = self.factory.makePerson()
        user_c = self.factory.makePerson()
        stable_team = self.factory.makeTeam(members=[user_a, user_b])
        next_team = self.factory.makeTeam(members=[user_b, user_c])

        repository = removeSecurityProxy(
            self.factory.makeGitRepository(owner=user_a))

        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/stable/next')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=GitGranteeType.REPOSITORY_OWNER,
            can_force_push=True)

        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/stable/protected')
        self.factory.makeGitRuleGrant(rule=rule, grantee=stable_team)

        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/archived/*')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=GitGranteeType.REPOSITORY_OWNER)
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=user_b, can_create=True)

        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/stable/*')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=stable_team, can_push=True)

        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/*/next')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=next_team, can_force_push=True)

        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/tags/*')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=GitGranteeType.REPOSITORY_OWNER,
            can_create=True)
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=stable_team, can_create=True)

        test_ref_paths = [
            b'refs/heads/stable/next', b'refs/heads/stable/protected',
            b'refs/heads/stable/foo', b'refs/heads/archived/foo',
            b'refs/heads/foo/next', b'refs/heads/unprotected',
            b'refs/tags/1.0',
        ]

        return (user_a, user_b, user_c, stable_team, next_team, repository,
                test_ref_paths)

    def test_checkRefPermissions_scenario_one_user_a(self):
        user_a, _, _, _, _, repo, paths = self._make_scenario_one_repository()
        self.assertHasRefPermissions(user_a, repo, paths, {
            b'refs/heads/stable/next': ['push', 'force_push'],
            b'refs/heads/stable/protected': ['create', 'push'],
            b'refs/heads/stable/foo': ['create', 'push'],
            b'refs/heads/archived/foo': [],
            b'refs/heads/foo/next': ['create', 'push'],
            b'refs/heads/unprotected': ['create', 'push', 'force_push'],
            b'refs/tags/1.0': ['create'],
            })

    def test_checkRefPermissions_scenario_one_user_b(self):
        _, user_b, _, _, _, repo, paths = self._make_scenario_one_repository()
        self.assertHasRefPermissions(user_b, repo, paths, {
            b'refs/heads/stable/next': ['push', 'force_push'],
            b'refs/heads/stable/protected': [],
            b'refs/heads/stable/foo': ['push'],
            b'refs/heads/archived/foo': ['create'],
            b'refs/heads/foo/next': ['push', 'force_push'],
            b'refs/heads/unprotected': [],
            b'refs/tags/1.0': ['create'],
            })

    def test_checkRefPermissions_scenario_one_user_c(self):
        _, _, user_c, _, _, repo, paths = self._make_scenario_one_repository()
        self.assertHasRefPermissions(user_c, repo, paths, {
            b'refs/heads/stable/next': ['push', 'force_push'],
            b'refs/heads/stable/protected': [],
            b'refs/heads/stable/foo': [],
            b'refs/heads/archived/foo': [],
            b'refs/heads/foo/next': ['push', 'force_push'],
            b'refs/heads/unprotected': [],
            b'refs/tags/1.0': [],
            })

    def test_checkRefPermissions_scenario_one_user_d(self):
        user_d = self.factory.makePerson()
        _, _, _, _, _, repo, paths = self._make_scenario_one_repository()
        self.assertHasRefPermissions(user_d, repo, paths, {
            b'refs/heads/stable/next': [],
            b'refs/heads/stable/protected': [],
            b'refs/heads/stable/foo': [],
            b'refs/heads/archived/foo': [],
            b'refs/heads/foo/next': [],
            b'refs/heads/unprotected': [],
            b'refs/tags/1.0': [],
            })

    def _make_scenario_two_repository(self):
        user_a = self.factory.makePerson()
        user_b = self.factory.makePerson()

        repository = removeSecurityProxy(
            self.factory.makeGitRepository(owner=user_a))

        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/master')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=user_b, can_push=True)

        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/heads/*')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=GitGranteeType.REPOSITORY_OWNER,
            can_create=True, can_push=True, can_force_push=True)

        rule = self.factory.makeGitRule(
            repository, ref_pattern=u'refs/tags/*')
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=user_b, can_push=True)

        test_ref_paths = [b'refs/heads/master', b'refs/heads/foo',
                          b'refs/tags/1.0', b'refs/other']
        return user_a, user_b, repository, test_ref_paths

    def test_checkRefPermissions_scenario_two_user_a(self):
        user_a, _, repo, paths = self._make_scenario_two_repository()
        self.assertHasRefPermissions(user_a, repo, paths, {
            b'refs/heads/master': ['create', 'push', 'force_push'],
            b'refs/heads/foo': ['create', 'push', 'force_push'],
            b'refs/tags/1.0': ['create', 'push'],
            b'refs/other': ['create', 'push', 'force_push'],
            })

    def test_checkRefPermissions_scenario_two_user_b(self):
        _, user_b, repo, paths = self._make_scenario_two_repository()
        self.assertHasRefPermissions(user_b, repo, paths, {
            b'refs/heads/master': ['push'],
            b'refs/heads/foo': [],
            b'refs/tags/1.0': ['push'],
            b'refs/other': [],
            })

    def test_checkRefPermissions_scenario_two_user_c(self):
        _, _, repo, paths = self._make_scenario_two_repository()
        user_c = self.factory.makePerson()
        self.assertHasRefPermissions(user_c, repo, paths, {
            b'refs/heads/master': [],
            b'refs/heads/foo': [],
            b'refs/tags/1.0': [],
            b'refs/other': [],
            })

    def test_checkRefPermissions_bytes(self):
        owner = self.factory.makePerson()
        grantee = self.factory.makePerson()
        no_privileges = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(owner=owner))
        self.factory.makeGitRuleGrant(
            repository=repository, ref_pattern=u"refs/heads/next/*",
            grantee=grantee, can_push=True)
        paths = [
            # Properly-encoded UTF-8.
            u"refs/heads/next/\N{BLACK HEART SUIT}".encode("UTF-8"),
            # Non-UTF-8.  (git does not require any particular encoding for
            # ref paths; non-UTF-8 ones won't work well everywhere, but it's
            # at least possible to round-trip them through Launchpad.)
            b"refs/heads/next/\x80",
            ]

        self.assertHasRefPermissions(
            grantee, repository, paths, {path: ["push"] for path in paths})
        login(ANONYMOUS)
        self.assertHasRefPermissions(
            no_privileges, repository, paths, {path: [] for path in paths})

    def test_checkRefPermissions_nonexistent_repository(self):
        requester = self.factory.makePerson()
        self.assertFault(
            faults.GitRepositoryNotFound("nonexistent"),
            self.git_api.checkRefPermissions,
            "nonexistent", [], {"uid": requester.id})


class TestGitAPI(TestGitAPIMixin, TestCaseWithFactory):
    """Tests for the implementation of `IGitAPI`."""

    layer = LaunchpadFunctionalLayer

    def test_translatePath_cannot_translate(self):
        # Sometimes translatePath will not know how to translate a path.
        # When this happens, it returns a Fault saying so, including the
        # path it couldn't translate.
        requester = self.factory.makePerson()
        self.assertGitRepositoryNotFound(requester, u"/untranslatable")

    def test_translatePath_repository(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = u"/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository, False)

    def test_translatePath_repository_with_no_leading_slash(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = repository.unique_name
        self.assertTranslates(requester, path, repository, False)

    def test_translatePath_repository_with_trailing_slash(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = u"/%s/" % repository.unique_name
        self.assertTranslates(requester, path, repository, False)

    def test_translatePath_repository_with_trailing_segments(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = u"/%s/foo/bar" % repository.unique_name
        self.assertTranslates(
            requester, path, repository, False, trailing="foo/bar")

    def test_translatePath_no_such_repository(self):
        requester = self.factory.makePerson()
        path = u"/%s/+git/no-such-repository" % requester.name
        self.assertGitRepositoryNotFound(requester, path)

    def test_translatePath_no_such_repository_non_ascii(self):
        requester = self.factory.makePerson()
        path = u"/%s/+git/\N{LATIN SMALL LETTER I WITH DIAERESIS}" % (
            requester.name)
        self.assertGitRepositoryNotFound(requester, path)

    def test_translatePath_anonymous_public_repository(self):
        repository = self.factory.makeGitRepository()
        path = u"/%s" % repository.unique_name
        self.assertTranslates(
            None, path, repository, False, can_authenticate=False)
        self.assertTranslates(
            None, path, repository, False, can_authenticate=True)

    def test_translatePath_owned(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        path = u"/%s" % repository.unique_name
        self.assertTranslates(
            requester, path, repository, True, permission="write")

    def test_translatePath_team_owned(self):
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(requester)
        repository = self.factory.makeGitRepository(owner=team)
        path = u"/%s" % repository.unique_name
        self.assertTranslates(
            requester, path, repository, True, permission="write")

    def test_translatePath_shortened_path(self):
        # translatePath translates the shortened path to a repository.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        with person_logged_in(repository.target.owner):
            getUtility(IGitRepositorySet).setDefaultRepository(
                repository.target, repository)
        path = u"/%s" % repository.target.name
        self.assertTranslates(requester, path, repository, False)

    def test_translatePath_create_project(self):
        # translatePath creates a project repository that doesn't exist, if
        # it can.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        self.assertCreates(
            requester, u"/~%s/%s/+git/random" % (requester.name, project.name))

    def test_translatePath_create_project_clone_from_target_default(self):
        # translatePath creates a project repository cloned from the target
        # default if it exists.
        target = self.factory.makeProduct()
        repository = self.factory.makeGitRepository(
            owner=target.owner, target=target)
        with person_logged_in(target.owner):
            self.repository_set.setDefaultRepository(target, repository)
            self.assertCreatesFromClone(
                target.owner,
                u"/~%s/%s/+git/random" % (target.owner.name, target.name),
                repository)

    def test_translatePath_create_project_clone_from_owner_default(self):
        # translatePath creates a project repository cloned from the owner
        # default if it exists and the target default does not.
        target = self.factory.makeProduct()
        repository = self.factory.makeGitRepository(
            owner=target.owner, target=target)
        with person_logged_in(target.owner) as user:
            self.repository_set.setDefaultRepositoryForOwner(
                target.owner, target, repository, user)
            self.assertCreatesFromClone(
                target.owner,
                u"/~%s/%s/+git/random" % (target.owner.name, target.name),
                repository)

    def test_translatePath_create_package(self):
        # translatePath creates a package repository that doesn't exist, if
        # it can.
        requester = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        self.assertCreates(
            requester,
            u"/~%s/%s/+source/%s/+git/random" % (
                requester.name,
                dsp.distribution.name, dsp.sourcepackagename.name))

    def test_translatePath_create_oci_project(self):
        # translatePath creates an OCI project repository that doesn't
        # exist, if it can.
        requester = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        self.assertCreates(
            requester,
            u"/~%s/%s/+oci/%s/+git/random" % (
                requester.name, oci_project.pillar.name, oci_project.name))

    def test_translatePath_create_personal(self):
        # translatePath creates a personal repository that doesn't exist, if
        # it can.
        requester = self.factory.makePerson()
        self.assertCreates(requester, u"/~%s/+git/random" % requester.name)

    def test_translatePath_create_personal_team(self):
        # translatePath creates a personal repository for a team of which
        # the requester is a member.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(members=[requester])
        self.assertCreates(requester, u"/~%s/+git/random" % team.name)

    def test_translatePath_create_bytestring(self):
        # ASCII strings come in as bytestrings, not Unicode strings. They
        # work fine too.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        path = u"/~%s/%s/+git/random" % (requester.name, project.name)
        self.assertCreates(requester, path.encode('ascii'))

    def test_translatePath_anonymous_cannot_create(self):
        # Anonymous users cannot create repositories.
        project = self.factory.makeProject()
        self.assertGitRepositoryNotFound(
            None, u"/%s" % project.name, permission="write",
            can_authenticate=False)
        self.assertUnauthorized(
            None, u"/%s" % project.name, permission="write",
            can_authenticate=True)

    def test_translatePath_create_invalid_namespace(self):
        # Trying to create a repository at a path that isn't valid for Git
        # repositories returns a PermissionDenied fault.
        requester = self.factory.makePerson()
        path = u"/~%s" % requester.name
        message = "'%s' is not a valid Git repository path." % path.strip("/")
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")

    def test_translatePath_create_no_such_person(self):
        # Creating a repository for a non-existent person fails.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester, u"/~nonexistent/+git/random",
            "User/team 'nonexistent' does not exist.", permission="write")

    def test_translatePath_create_no_such_project(self):
        # Creating a repository for a non-existent project fails.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester, u"/~%s/nonexistent/+git/random" % requester.name,
            "Project 'nonexistent' does not exist.", permission="write")

    def test_translatePath_create_no_such_person_or_project(self):
        # If neither the person nor the project are found, then the missing
        # person is reported in preference.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester, u"/~nonexistent/nonexistent/+git/random",
            "User/team 'nonexistent' does not exist.", permission="write")

    def test_translatePath_create_invalid_project(self):
        # Creating a repository with an invalid project name fails.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester, u"/_bad_project/+git/random",
            "Project '_bad_project' does not exist.", permission="write")

    def test_translatePath_create_missing_sourcepackagename(self):
        # If translatePath is asked to create a repository for a missing
        # source package, it will create the source package.
        requester = self.factory.makePerson()
        distro = self.factory.makeDistribution()
        repository_name = self.factory.getUniqueString()
        path = u"/~%s/%s/+source/new-package/+git/%s" % (
            requester.name, distro.name, repository_name)
        repository = self.assertCreates(requester, path)
        self.assertEqual(
            "new-package", repository.target.sourcepackagename.name)

    def test_translatePath_create_invalid_sourcepackagename(self):
        # Creating a repository for an invalid source package name fails.
        requester = self.factory.makePerson()
        distro = self.factory.makeDistribution()
        repository_name = self.factory.getUniqueString()
        path = u"/~%s/%s/+source/new package/+git/%s" % (
            requester.name, distro.name, repository_name)
        self.assertInvalidSourcePackageName(
            requester, path, "new package", permission="write")

    def test_translatePath_create_bad_name(self):
        # Creating a repository with an invalid name fails.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        invalid_name = "invalid name!"
        path = u"/~%s/%s/+git/%s" % (
            requester.name, project.name, invalid_name)
        # LaunchpadValidationError unfortunately assumes its output is
        # always HTML, so it ends up double-escaped in XML-RPC faults.
        message = html_escape(
            "Invalid Git repository name '%s'. %s" %
            (invalid_name, GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE))
        self.assertInvalidBranchName(
            requester, path, message, permission="write")

    def test_translatePath_create_unicode_name(self):
        # Creating a repository with a non-ASCII invalid name fails.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        invalid_name = u"invalid\N{LATIN SMALL LETTER E WITH ACUTE}"
        path = u"/~%s/%s/+git/%s" % (
            requester.name, project.name, invalid_name)
        # LaunchpadValidationError unfortunately assumes its output is
        # always HTML, so it ends up double-escaped in XML-RPC faults.
        message = html_escape(
            "Invalid Git repository name '%s'. %s" %
            (invalid_name, GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE))
        self.assertInvalidBranchName(
            requester, path, message, permission="write")

    def test_translatePath_create_project_default(self):
        # A repository can be created and immediately set as the default for
        # a project.
        requester = self.factory.makePerson()
        owner = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.RESTRICTED,
            members=[requester])
        project = self.factory.makeProduct(owner=owner)
        repository = self.assertCreates(requester, u"/%s" % project.name)
        self.assertTrue(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(owner, repository.owner)

    def test_translatePath_create_package_default_denied(self):
        # A repository cannot (yet) be created and immediately set as the
        # default for a package.
        requester = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        path = u"/%s/+source/%s" % (
            dsp.distribution.name, dsp.sourcepackagename.name)
        message = (
            "Cannot automatically set the default repository for this target; "
            "push to a named repository instead.")
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")

    def test_translatePath_create_oci_project_default_denied(self):
        # A repository cannot (yet) be created and immediately set as the
        # default for an OCI project.
        requester = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        path = u"/%s/+oci/%s" % (oci_project.pillar.name, oci_project.name)
        message = (
            "Cannot automatically set the default repository for this target; "
            "push to a named repository instead.")
        self.assertPermissionDenied(
            requester, path, message=message, permission="write")

    def test_translatePath_create_project_owner_default(self):
        # A repository can be created and immediately set as its owner's
        # default for a project.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        repository = self.assertCreates(
            requester, u"/~%s/%s" % (requester.name, project.name))
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(requester, repository.owner)

    def test_translatePath_create_project_team_owner_default(self):
        # The owner of a team can create a team-owned repository and
        # immediately set it as that team's default for a project.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(owner=requester)
        project = self.factory.makeProduct()
        repository = self.assertCreates(
            requester, u"/~%s/%s" % (team.name, project.name))
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(team, repository.owner)

    def test_translatePath_create_project_team_member_default(self):
        # A non-owner member of a team can create a team-owned repository
        # and immediately set it as that team's default for a project.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(members=[requester])
        project = self.factory.makeProduct()
        repository = self.assertCreates(
            requester, u"/~%s/%s" % (team.name, project.name))
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(team, repository.owner)

    def test_translatePath_create_package_owner_default(self):
        # A repository can be created and immediately set as its owner's
        # default for a package.
        requester = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        path = u"/~%s/%s/+source/%s" % (
            requester.name, dsp.distribution.name, dsp.sourcepackagename.name)
        repository = self.assertCreates(requester, path)
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(requester, repository.owner)

    def test_translatePath_create_package_team_owner_default(self):
        # The owner of a team can create a team-owned repository and
        # immediately set it as that team's default for a package.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(owner=requester)
        dsp = self.factory.makeDistributionSourcePackage()
        path = u"/~%s/%s/+source/%s" % (
            team.name, dsp.distribution.name, dsp.sourcepackagename.name)
        repository = self.assertCreates(requester, path)
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(team, repository.owner)

    def test_translatePath_create_package_team_member_default(self):
        # A non-owner member of a team can create a team-owned repository
        # and immediately set it as that team's default for a package.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(members=[requester])
        dsp = self.factory.makeDistributionSourcePackage()
        path = u"/~%s/%s/+source/%s" % (
            team.name, dsp.distribution.name, dsp.sourcepackagename.name)
        repository = self.assertCreates(requester, path)
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(team, repository.owner)

    def test_translatePath_create_broken_hosting_service(self):
        # If the hosting service is down, trying to create a repository
        # fails and doesn't leave junk around in the Launchpad database.
        self.hosting_fixture.create.failure = GitRepositoryCreationFault(
            "nothing here", path="123")
        requester = self.factory.makePerson()
        initial_count = getUtility(IAllGitRepositories).count()
        oops_id = self.assertOopsOccurred(
            requester, u"/~%s/+git/random" % requester.name,
            permission="write")
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count())
        # The error report OOPS ID should match the fault, and the traceback
        # text should show the underlying exception.
        self.assertEqual(1, len(self.oopses))
        self.assertEqual(oops_id, self.oopses[0]["id"])
        self.assertIn(
            "GitRepositoryCreationFault: nothing here",
            self.oopses[0]["tb_text"])

    def test_translatePath_code_import(self):
        # A code import worker with a suitable macaroon can write to a
        # repository associated with a running code import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret")
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT)
            for _ in range(2)]
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs]
        path = u"/%s" % code_imports[0].git_repository.unique_name
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="write",
            macaroon_raw=macaroons[0].serialize())
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertTranslates(
            LAUNCHPAD_SERVICES, path, code_imports[0].git_repository, True,
            permission="write", macaroon_raw=macaroons[0].serialize())
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="write",
            macaroon_raw=macaroons[1].serialize())
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="write",
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname, identifier="another",
                key="another-secret").serialize())
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="write",
            macaroon_raw="nonsense")
        self.assertUnauthorized(
            code_imports[0].registrant, path, permission="write",
            macaroon_raw=macaroons[0].serialize())

    def test_translatePath_private_code_import(self):
        # A code import worker with a suitable macaroon can write to a
        # repository associated with a running private code import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret")
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT)
            for _ in range(2)]
        private_repository = code_imports[0].git_repository
        removeSecurityProxy(private_repository).transitionToInformationType(
            InformationType.PRIVATESECURITY, private_repository.owner)
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs]
        path = u"/%s" % code_imports[0].git_repository.unique_name
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="write",
            macaroon_raw=macaroons[0].serialize())
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertTranslates(
            LAUNCHPAD_SERVICES, path, code_imports[0].git_repository, True,
            permission="write", macaroon_raw=macaroons[0].serialize(),
            private=True)
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="write",
            macaroon_raw=macaroons[1].serialize())
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="write",
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname, identifier="another",
                key="another-secret").serialize())
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="write",
            macaroon_raw="nonsense")
        self.assertUnauthorized(
            code_imports[0].registrant, path, permission="write",
            macaroon_raw=macaroons[0].serialize())

    def test_translatePath_private_snap_build(self):
        # A builder with a suitable macaroon can read from a repository
        # associated with a running private snap build.
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret")
        with person_logged_in(self.factory.makePerson()) as owner:
            refs = [
                self.factory.makeGitRefs(
                    owner=owner, information_type=InformationType.USERDATA)[0]
                for _ in range(2)]
            builds = [
                self.factory.makeSnapBuild(
                    requester=owner, owner=owner, git_ref=ref, private=True)
                for ref in refs]
            issuer = getUtility(IMacaroonIssuer, "snap-build")
            macaroons = [
                removeSecurityProxy(issuer).issueMacaroon(build)
                for build in builds]
            repository = refs[0].repository
            path = u"/%s" % repository.unique_name
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="write",
            macaroon_raw=macaroons[0].serialize())
        removeSecurityProxy(builds[0]).updateStatus(BuildStatus.BUILDING)
        self.assertTranslates(
            LAUNCHPAD_SERVICES, path, repository, False, permission="read",
            macaroon_raw=macaroons[0].serialize(), private=True)
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="read",
            macaroon_raw=macaroons[1].serialize())
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="read",
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname, identifier="another",
                key="another-secret").serialize())
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES, path, permission="read",
            macaroon_raw="nonsense")
        self.assertUnauthorized(
            repository.registrant, path, permission="read",
            macaroon_raw=macaroons[0].serialize())

    def test_translatePath_user_macaroon(self):
        # A user with a suitable macaroon can write to the corresponding
        # repository, but not others, even if they own them.
        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=requester) for _ in range(2)]
        repositories.append(self.factory.makeGitRepository(
            owner=requester, information_type=InformationType.PRIVATESECURITY))
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        with person_logged_in(requester):
            macaroons = [
                removeSecurityProxy(issuer).issueMacaroon(
                    repository, user=requester)
                for repository in repositories]
            paths = [
                u"/%s" % repository.unique_name for repository in repositories]
        for i, repository in enumerate(repositories):
            for j, macaroon in enumerate(macaroons):
                login(ANONYMOUS)
                if i == j:
                    self.assertTranslates(
                        requester, paths[i], repository, True,
                        permission="write", macaroon_raw=macaroon.serialize(),
                        private=(i == 2))
                else:
                    self.assertUnauthorized(
                        requester, paths[i], permission="write",
                        macaroon_raw=macaroon.serialize())
            login(ANONYMOUS)
            self.assertUnauthorized(
                requester, paths[i], permission="write",
                macaroon_raw=Macaroon(
                    location=config.vhost.mainsite.hostname,
                    identifier="another", key="another-secret").serialize())
            login(ANONYMOUS)
            self.assertUnauthorized(
                requester, paths[i], permission="write",
                macaroon_raw="nonsense")

    def test_translatePath_user_mismatch(self):
        # translatePath refuses macaroons in the case where the user doesn't
        # match what the issuer claims was verified.  (We use a dummy issuer
        # for this, since this is a stopgap check to defend against issuer
        # bugs; and we test read permissions since write permissions for
        # internal macaroons are restricted to particular named issuers.)
        issuer = DummyMacaroonIssuer()
        self.useFixture(ZopeUtilityFixture(
            issuer, IMacaroonIssuer, name="test"))
        repository = self.factory.makeGitRepository()
        path = u"/%s" % repository.unique_name
        macaroon = issuer.issueMacaroon(repository)
        requesters = [self.factory.makePerson() for _ in range(2)]
        for verified_user, authorized, unauthorized in (
                (NO_USER, [LAUNCHPAD_SERVICES], requesters + [None]),
                (requesters[0], [requesters[0]],
                 [LAUNCHPAD_SERVICES, requesters[1], None]),
                (None, [], [LAUNCHPAD_SERVICES] + requesters + [None]),
                ):
            issuer._verified_user = verified_user
            for requester in authorized:
                login(ANONYMOUS)
                self.assertTranslates(
                    requester, path, repository, False, permission="read",
                    macaroon_raw=macaroon.serialize())
            for requester in unauthorized:
                login(ANONYMOUS)
                self.assertUnauthorized(
                    requester, path, permission="read",
                    macaroon_raw=macaroon.serialize())

    def test_notify(self):
        # The notify call creates a GitRefScanJob.
        repository = self.factory.makeGitRepository()
        self.assertIsNone(self.git_api.notify(repository.getInternalPath()))
        job_source = getUtility(IGitRefScanJobSource)
        [job] = list(job_source.iterReady())
        self.assertEqual(repository, job.repository)

    def test_notify_missing_repository(self):
        # A notify call on a non-existent repository returns a fault and
        # does not create a job.
        self.assertFault(faults.NotFound, self.git_api.notify, "10000")
        job_source = getUtility(IGitRefScanJobSource)
        self.assertEqual([], list(job_source.iterReady()))

    def test_notify_private(self):
        # notify works on private repos.
        with admin_logged_in():
            repository = self.factory.makeGitRepository(
                information_type=InformationType.PRIVATESECURITY)
            path = repository.getInternalPath()
        self.assertIsNone(self.git_api.notify(path))
        job_source = getUtility(IGitRefScanJobSource)
        [job] = list(job_source.iterReady())
        self.assertEqual(repository, job.repository)

    def test_authenticateWithPassword(self):
        self.assertFault(
            faults.Unauthorized,
            self.git_api.authenticateWithPassword, "foo", "bar")

    def test_authenticateWithPassword_code_import(self):
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret")
        code_import = self.factory.makeCodeImport(
            target_rcs_type=TargetRevisionControlSystems.GIT)
        with celebrity_logged_in("vcs_imports"):
            job = self.factory.makeCodeImportJob(code_import=code_import)
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroon = removeSecurityProxy(issuer).issueMacaroon(job)
        self.assertEqual(
            {"macaroon": macaroon.serialize(), "user": "+launchpad-services"},
            self.git_api.authenticateWithPassword("", macaroon.serialize()))
        other_macaroon = Macaroon(identifier="another", key="another-secret")
        self.assertFault(
            faults.Unauthorized,
            self.git_api.authenticateWithPassword,
            "", other_macaroon.serialize())
        self.assertFault(
            faults.Unauthorized,
            self.git_api.authenticateWithPassword, "", "nonsense")

    def test_authenticateWithPassword_private_snap_build(self):
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret")
        with person_logged_in(self.factory.makePerson()) as owner:
            [ref] = self.factory.makeGitRefs(
                owner=owner, information_type=InformationType.USERDATA)
            build = self.factory.makeSnapBuild(
                requester=owner, owner=owner, git_ref=ref, private=True)
            issuer = getUtility(IMacaroonIssuer, "snap-build")
            macaroon = removeSecurityProxy(issuer).issueMacaroon(build)
        self.assertEqual(
            {"macaroon": macaroon.serialize(), "user": "+launchpad-services"},
            self.git_api.authenticateWithPassword("", macaroon.serialize()))
        other_macaroon = Macaroon(identifier="another", key="another-secret")
        self.assertFault(
            faults.Unauthorized,
            self.git_api.authenticateWithPassword,
            "", other_macaroon.serialize())
        self.assertFault(
            faults.Unauthorized,
            self.git_api.authenticateWithPassword, "", "nonsense")

    def test_authenticateWithPassword_user_macaroon(self):
        # A user with a suitable macaroon can authenticate using it, in
        # which case we return both the macaroon and the uid for use by
        # later calls.
        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        macaroon = removeSecurityProxy(issuer).issueMacaroon(
            self.factory.makeGitRepository(owner=requester), user=requester)
        self.assertEqual(
            {"macaroon": macaroon.serialize(), "uid": requester.id},
            self.git_api.authenticateWithPassword(
                requester.name, macaroon.serialize()))
        self.assertFault(
            faults.Unauthorized,
            self.git_api.authenticateWithPassword, "", macaroon.serialize())
        self.assertFault(
            faults.Unauthorized,
            self.git_api.authenticateWithPassword,
            "nonexistent", macaroon.serialize())
        other_macaroon = Macaroon(identifier="another", key="another-secret")
        self.assertFault(
            faults.Unauthorized,
            self.git_api.authenticateWithPassword,
            requester.name, other_macaroon.serialize())
        self.assertFault(
            faults.Unauthorized,
            self.git_api.authenticateWithPassword, requester.name, "nonsense")

    def test_authenticateWithPassword_user_mismatch(self):
        # authenticateWithPassword refuses macaroons in the case where the
        # user doesn't match what the issuer claims was verified.  (We use a
        # dummy issuer for this, since this is a stopgap check to defend
        # against issuer bugs; and we test read permissions since write
        # permissions for internal macaroons are restricted to particular
        # named issuers.)
        issuer = DummyMacaroonIssuer()
        self.useFixture(ZopeUtilityFixture(
            issuer, IMacaroonIssuer, name="test"))
        macaroon = issuer.issueMacaroon(self.factory.makeGitRepository())
        requesters = [self.factory.makePerson() for _ in range(2)]
        for verified_user, authorized, unauthorized in (
                (NO_USER, [LAUNCHPAD_SERVICES], requesters),
                (requesters[0], [requesters[0]],
                 [LAUNCHPAD_SERVICES, requesters[1]]),
                (None, [], [LAUNCHPAD_SERVICES] + requesters),
                ):
            issuer._verified_user = verified_user
            for requester in authorized:
                login(ANONYMOUS)
                expected_auth_params = {"macaroon": macaroon.serialize()}
                if requester == LAUNCHPAD_SERVICES:
                    name = requester
                    expected_auth_params["user"] = requester
                else:
                    name = requester.name
                    expected_auth_params["uid"] = requester.id
                self.assertEqual(
                    expected_auth_params,
                    self.git_api.authenticateWithPassword(
                        name, macaroon.serialize()))
            for requester in unauthorized:
                login(ANONYMOUS)
                name = (
                    requester if requester == LAUNCHPAD_SERVICES
                    else requester.name)
                self.assertFault(
                    faults.Unauthorized,
                    self.git_api.authenticateWithPassword,
                    name, macaroon.serialize())

    def test_checkRefPermissions_code_import(self):
        # A code import worker with a suitable macaroon has repository owner
        # privileges on a repository associated with a running code import
        # job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret")
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT)
            for _ in range(2)]
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs]
        repository = code_imports[0].git_repository
        ref_path = b"refs/heads/master"
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path], {ref_path: []},
            macaroon_raw=macaroons[0].serialize())
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path],
            {ref_path: ["create", "push", "force_push"]},
            macaroon_raw=macaroons[0].serialize())
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path], {ref_path: []},
            macaroon_raw=macaroons[1].serialize())
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path], {ref_path: []},
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname, identifier="another",
                key="another-secret").serialize())
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path], {ref_path: []},
            macaroon_raw="nonsense")
        self.assertHasRefPermissions(
            code_imports[0].registrant, repository, [ref_path], {ref_path: []},
            macaroon_raw=macaroons[0].serialize())

    def test_checkRefPermissions_private_code_import(self):
        # A code import worker with a suitable macaroon has repository owner
        # privileges on a repository associated with a running private code
        # import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret")
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT)
            for _ in range(2)]
        private_repository = code_imports[0].git_repository
        removeSecurityProxy(private_repository).transitionToInformationType(
            InformationType.PRIVATESECURITY, private_repository.owner)
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs]
        repository = code_imports[0].git_repository
        ref_path = b"refs/heads/master"
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path], {ref_path: []},
            macaroon_raw=macaroons[0].serialize())
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path],
            {ref_path: ["create", "push", "force_push"]},
            macaroon_raw=macaroons[0].serialize())
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path], {ref_path: []},
            macaroon_raw=macaroons[1].serialize())
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path], {ref_path: []},
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname, identifier="another",
                key="another-secret").serialize())
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, repository, [ref_path], {ref_path: []},
            macaroon_raw="nonsense")
        self.assertHasRefPermissions(
            code_imports[0].registrant, repository, [ref_path], {ref_path: []},
            macaroon_raw=macaroons[0].serialize())

    def test_checkRefPermissions_private_snap_build(self):
        # A builder with a suitable macaroon cannot write to a repository,
        # even if it is associated with a running private snap build.
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret")
        with person_logged_in(self.factory.makePerson()) as owner:
            [ref] = self.factory.makeGitRefs(
                owner=owner, information_type=InformationType.USERDATA)
            build = self.factory.makeSnapBuild(
                requester=owner, owner=owner, git_ref=ref, private=True)
            issuer = getUtility(IMacaroonIssuer, "snap-build")
            macaroon = removeSecurityProxy(issuer).issueMacaroon(build)
            build.updateStatus(BuildStatus.BUILDING)
            path = ref.path.encode("UTF-8")
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES, ref.repository, [path], {path: []},
            macaroon_raw=macaroon.serialize())

    def test_checkRefPermissions_user_macaroon(self):
        # A user with a suitable macaroon has their ordinary privileges on
        # the corresponding repository, but not others, even if they own
        # them.
        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=requester) for _ in range(2)]
        repositories.append(self.factory.makeGitRepository(
            owner=requester, information_type=InformationType.PRIVATESECURITY))
        ref_path = b"refs/heads/master"
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        with person_logged_in(requester):
            macaroons = [
                removeSecurityProxy(issuer).issueMacaroon(
                    repository, user=requester)
                for repository in repositories]
        for i, repository in enumerate(repositories):
            for j, macaroon in enumerate(macaroons):
                login(ANONYMOUS)
                if i == j:
                    expected_permissions = ["create", "push", "force_push"]
                else:
                    expected_permissions = []
                self.assertHasRefPermissions(
                    requester, repository, [ref_path],
                    {ref_path: expected_permissions},
                    macaroon_raw=macaroon.serialize())
            login(ANONYMOUS)
            self.assertHasRefPermissions(
                None, repository, [ref_path], {ref_path: []},
                macaroon_raw=macaroon.serialize())
            login(ANONYMOUS)
            self.assertHasRefPermissions(
                self.factory.makePerson(), repository, [ref_path],
                {ref_path: []}, macaroon_raw=macaroon.serialize())
            login(ANONYMOUS)
            self.assertHasRefPermissions(
                requester, repository, [ref_path], {ref_path: []},
                macaroon_raw=Macaroon(
                    location=config.vhost.mainsite.hostname,
                    identifier="another", key="another-secret").serialize())
            login(ANONYMOUS)
            self.assertHasRefPermissions(
                requester, repository, [ref_path], {ref_path: []},
                macaroon_raw="nonsense")

    def test_checkRefPermissions_user_mismatch(self):
        # checkRefPermissions refuses macaroons in the case where the user
        # doesn't match what the issuer claims was verified.  (We use a
        # dummy issuer for this, since this is a stopgap check to defend
        # against issuer bugs.)
        issuer = DummyMacaroonIssuer()
        # Claim to be the code-import-job issuer.  This is a bit weird, but
        # it gets us past the difficulty that only certain named issuers are
        # allowed to confer write permissions.
        issuer.identifier = "code-import-job"
        self.useFixture(ZopeUtilityFixture(
            issuer, IMacaroonIssuer, name="code-import-job"))
        requesters = [self.factory.makePerson() for _ in range(2)]
        owner = self.factory.makeTeam(members=requesters)
        repository = self.factory.makeGitRepository(owner=owner)
        ref_path = b"refs/heads/master"
        macaroon = issuer.issueMacaroon(repository)
        for verified_user, authorized, unauthorized in (
                (NO_USER, [LAUNCHPAD_SERVICES], requesters + [None]),
                (requesters[0], [requesters[0]],
                 [LAUNCHPAD_SERVICES, requesters[1], None]),
                (None, [], [LAUNCHPAD_SERVICES] + requesters + [None]),
                ):
            issuer._verified_user = verified_user
            for requester in authorized:
                login(ANONYMOUS)
                self.assertHasRefPermissions(
                    requester, repository, [ref_path],
                    {ref_path: ["create", "push", "force_push"]},
                    macaroon_raw=macaroon.serialize())
            for requester in unauthorized:
                login(ANONYMOUS)
                self.assertHasRefPermissions(
                    requester, repository, [ref_path], {ref_path: []},
                    macaroon_raw=macaroon.serialize())


class TestGitAPISecurity(TestGitAPIMixin, TestCaseWithFactory):
    """Slow tests for `IGitAPI`.

    These use AppServerLayer to check that `run_with_login` is behaving
    itself properly.
    """

    layer = AppServerLayer
