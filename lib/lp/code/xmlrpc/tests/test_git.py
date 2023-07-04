# Copyright 2015-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the internal Git API."""

import hashlib
import uuid
import xmlrpc.client
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import six
from fixtures import FakeLogger
from pymacaroons import Macaroon
from storm.store import Store
from testtools.matchers import (
    Equals,
    IsInstance,
    MatchesAll,
    MatchesListwise,
    MatchesRegex,
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
    GitRepositoryStatus,
    GitRepositoryType,
    TargetRevisionControlSystems,
)
from lp.code.errors import GitRepositoryCreationFault
from lp.code.interfaces.codehosting import LAUNCHPAD_SERVICES
from lp.code.interfaces.codeimportjob import ICodeImportJobWorkflow
from lp.code.interfaces.gitcollection import IAllGitRepositories
from lp.code.interfaces.gitjob import IGitRefScanJobSource
from lp.code.interfaces.gitlookup import IGitLookup
from lp.code.interfaces.gitrepository import (
    GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE,
    IGitRepository,
    IGitRepositorySet,
)
from lp.code.model.gitjob import GitRefScanJob
from lp.code.tests.helpers import GitHostingFixture
from lp.code.xmlrpc.git import GIT_ASYNC_CREATE_REPO
from lp.registry.enums import TeamMembershipPolicy
from lp.services.auth.enums import AccessTokenScope
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.identity.interfaces.account import AccountStatus
from lp.services.job.runner import JobRunner
from lp.services.macaroons.interfaces import (
    NO_USER,
    BadMacaroonContext,
    IMacaroonIssuer,
)
from lp.services.macaroons.model import MacaroonIssuerBase
from lp.services.webapp import canonical_url
from lp.services.webapp.escaping import html_escape
from lp.snappy.interfaces.snap import SNAP_TESTING_FLAGS
from lp.testing import (
    ANONYMOUS,
    TestCaseWithFactory,
    admin_logged_in,
    celebrity_logged_in,
    login,
    person_logged_in,
)
from lp.testing.dbuser import dbuser
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import AppServerLayer, LaunchpadFunctionalLayer
from lp.testing.xmlrpc import MatchesFault, XMLRPCTestTransport
from lp.xmlrpc import faults


def _make_auth_params(
    requester,
    can_authenticate=False,
    macaroon_raw=None,
    access_token_id=None,
):
    auth_params = {
        "can-authenticate": can_authenticate,
        "request-id": str(uuid.uuid4()),
    }
    if requester == LAUNCHPAD_SERVICES:
        auth_params["user"] = LAUNCHPAD_SERVICES
    elif requester is not None:
        auth_params["uid"] = requester.id
    if macaroon_raw is not None:
        auth_params["macaroon"] = macaroon_raw
    if access_token_id is not None:
        # turnip marshals its authentication parameters as strings even if
        # it received them from authenticateWithPassword as integers, so
        # emulate it.
        auth_params["access-token"] = str(access_token_id)
    return auth_params


@implementer(IMacaroonIssuer)
class FakeMacaroonIssuer(MacaroonIssuerBase):
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


class TestGitAPIMixin:
    """Helper methods for `IGitAPI` tests, and security-relevant tests."""

    def setUp(self):
        super().setUp()
        self.git_api = xmlrpc.client.ServerProxy(
            "http://xmlrpc-private.launchpad.test:8087/git",
            transport=XMLRPCTestTransport(),
        )
        self.hosting_fixture = self.useFixture(GitHostingFixture())
        self.repository_set = getUtility(IGitRepositorySet)
        self.useFixture(FeatureFixture({GIT_ASYNC_CREATE_REPO: True}))

    def assertFault(
        self, expected_fault, request_id, func_name, *args, **kwargs
    ):
        """Assert that a call raises the expected fault."""
        with FakeLogger() as logger:
            fault = self.assertRaises(
                xmlrpc.client.Fault,
                getattr(self.git_api, func_name),
                *args,
                **kwargs,
            )
            self.assertThat(fault, MatchesFault(expected_fault))
            self.assertThat(
                logger.output,
                MatchesRegex(
                    r"\[request-id=%s\] Request received: %s.*\n"
                    r"\[request-id=%s\] %s failed: .* %s:.*"
                    % (
                        request_id or ".*",
                        func_name,
                        request_id or ".*",
                        func_name,
                        fault.faultCode,
                    )
                ),
            )
        return fault

    def assertDoesNotFault(self, request_id, func_name, *args, **kwargs):
        """Assert that a call does not raise a fault."""
        with FakeLogger() as logger:
            results = getattr(self.git_api, func_name)(*args, **kwargs)
            self.assertThat(
                logger.output,
                MatchesRegex(
                    r"\[request-id=%s\] Request received: %s.*\n"
                    r"\[request-id=%s\] %s succeeded.*"
                    % (
                        request_id or ".*",
                        func_name,
                        request_id or ".*",
                        func_name,
                    )
                ),
            )
        return results

    def assertGitRepositoryNotFound(
        self,
        requester,
        path,
        permission="read",
        can_authenticate=False,
        **auth_kwargs
    ):
        """Assert that the given path cannot be translated."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate, **auth_kwargs
        )
        request_id = auth_params["request-id"]
        self.assertFault(
            faults.GitRepositoryNotFound(path.strip("/")),
            request_id,
            "translatePath",
            path,
            permission,
            auth_params,
        )

    def assertPermissionDenied(
        self,
        requester,
        path,
        message="Permission denied.",
        permission="read",
        can_authenticate=False,
        **auth_kwargs
    ):
        """Assert that looking at the given path returns PermissionDenied."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate, **auth_kwargs
        )
        request_id = auth_params["request-id"]
        self.assertFault(
            faults.PermissionDenied(message),
            request_id,
            "translatePath",
            path,
            permission,
            auth_params,
        )

    def assertUnauthorized(
        self,
        requester,
        path,
        message="Authorisation required.",
        permission="read",
        can_authenticate=False,
        **auth_kwargs
    ):
        """Assert that looking at the given path returns Unauthorized."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate, **auth_kwargs
        )
        request_id = auth_params["request-id"]
        self.assertFault(
            faults.Unauthorized(message),
            request_id,
            "translatePath",
            path,
            permission,
            auth_params,
        )

    def assertNotFound(
        self,
        requester,
        path,
        message,
        permission="read",
        can_authenticate=False,
    ):
        """Assert that looking at the given path returns NotFound."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate
        )
        request_id = auth_params["request-id"]
        self.assertFault(
            faults.NotFound(message),
            request_id,
            "translatePath",
            path,
            permission,
            auth_params,
        )

    def assertInvalidSourcePackageName(
        self, requester, path, name, permission="read", can_authenticate=False
    ):
        """Assert that looking at the given path returns
        InvalidSourcePackageName."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate
        )
        request_id = auth_params["request-id"]
        self.assertFault(
            faults.InvalidSourcePackageName(name),
            request_id,
            "translatePath",
            path,
            permission,
            auth_params,
        )

    def assertInvalidBranchName(
        self,
        requester,
        path,
        message,
        permission="read",
        can_authenticate=False,
    ):
        """Assert that looking at the given path returns InvalidBranchName."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate
        )
        request_id = auth_params["request-id"]
        self.assertFault(
            faults.InvalidBranchName(Exception(message)),
            request_id,
            "translatePath",
            path,
            permission,
            auth_params,
        )

    def assertOopsOccurred(
        self, requester, path, permission="read", can_authenticate=False
    ):
        """Assert that looking at the given path OOPSes."""
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate
        )
        request_id = auth_params["request-id"]
        fault = self.assertFault(
            faults.OopsOccurred,
            request_id,
            "translatePath",
            path,
            permission,
            auth_params,
        )
        prefix = (
            "An unexpected error has occurred while creating a Git "
            "repository. Please report a Launchpad bug and quote: "
        )
        self.assertStartsWith(fault.faultString, prefix)
        return fault.faultString[len(prefix) :].rstrip(".")

    def assertTranslates(
        self,
        requester,
        path,
        repository,
        permission="read",
        can_authenticate=False,
        readable=True,
        writable=False,
        trailing="",
        private=False,
        **auth_kwargs
    ):
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate, **auth_kwargs
        )
        request_id = auth_params["request-id"]
        translation = self.assertDoesNotFault(
            request_id, "translatePath", path, permission, auth_params
        )
        login(ANONYMOUS)
        self.assertEqual(
            {
                "path": removeSecurityProxy(repository).getInternalPath(),
                "readable": readable,
                "writable": writable,
                "trailing": trailing,
                "private": private,
            },
            translation,
        )

    def assertConfirmsRepoCreation(
        self, requester, git_repository, can_authenticate=True, **auth_kwargs
    ):
        # Puts some refs in git hosting, to make sure we scanned them.
        sha1 = lambda x: hashlib.sha1(x).hexdigest()
        self.hosting_fixture = self.useFixture(
            GitHostingFixture(
                refs={
                    "refs/heads/master": {
                        "object": {
                            "sha1": sha1(b"master-branch"),
                            "type": "commit",
                        },
                    },
                    "refs/heads/foo": {
                        "object": {
                            "sha1": sha1(b"foo-branch"),
                            "type": "commit",
                        },
                    },
                }
            )
        )
        translated_path = git_repository.getInternalPath()
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate, **auth_kwargs
        )
        request_id = auth_params["request-id"]
        result = self.assertDoesNotFault(
            request_id, "confirmRepoCreation", translated_path, auth_params
        )
        # Run the ref scan job.
        ref_scan_jobs = list(GitRefScanJob.iterReady())
        self.assertEqual(1, len(ref_scan_jobs))
        with dbuser("branchscanner"):
            JobRunner(ref_scan_jobs).runAll()
        login(ANONYMOUS)
        self.assertIsNone(result)
        Store.of(git_repository).invalidate(git_repository)
        self.assertEqual(GitRepositoryStatus.AVAILABLE, git_repository.status)
        # Should have checked the refs at some point.
        excluded_prefixes = config.codehosting.git_exclude_ref_prefixes
        self.assertEqual(
            [
                (
                    (git_repository.getInternalPath(),),
                    dict(exclude_prefixes=excluded_prefixes.split(",")),
                )
            ],
            self.hosting_fixture.getRefs.calls,
        )
        self.assertEqual(2, git_repository.refs.count())
        self.assertEqual(
            {"refs/heads/foo", "refs/heads/master"},
            {i.path for i in git_repository.refs},
        )
        self.assertEqual(
            {sha1(b"foo-branch"), sha1(b"master-branch")},
            {i.commit_sha1 for i in git_repository.refs},
        )

    def assertConfirmRepoCreationFails(
        self,
        failure,
        requester,
        git_repository,
        can_authenticate=True,
        **auth_kwargs
    ):
        translated_path = git_repository.getInternalPath()
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate, **auth_kwargs
        )
        request_id = auth_params["request-id"]
        original_status = git_repository.status
        self.assertFault(
            failure,
            request_id,
            "confirmRepoCreation",
            translated_path,
            auth_params,
        )
        store = Store.of(git_repository)
        if store:
            store.invalidate(git_repository)
        self.assertEqual(original_status, git_repository.status)

    def assertConfirmRepoCreationUnauthorized(
        self, requester, git_repository, can_authenticate=True, **auth_kwargs
    ):
        failure = faults.Unauthorized
        self.assertConfirmRepoCreationFails(
            failure,
            requester,
            git_repository,
            can_authenticate=can_authenticate,
            **auth_kwargs,
        )

    def assertAbortsRepoCreation(
        self, requester, git_repository, can_authenticate=True, **auth_kwargs
    ):
        translated_path = git_repository.getInternalPath()
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate, **auth_kwargs
        )
        request_id = auth_params["request-id"]
        result = self.assertDoesNotFault(
            request_id, "abortRepoCreation", translated_path, auth_params
        )
        login(ANONYMOUS)
        self.assertIsNone(result)
        self.assertIsNone(
            getUtility(IGitLookup).getByHostingPath(translated_path)
        )

    def assertAbortRepoCreationFails(
        self,
        failure,
        requester,
        git_repository,
        can_authenticate=True,
        **auth_kwargs
    ):
        translated_path = git_repository.getInternalPath()
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate, **auth_kwargs
        )
        request_id = auth_params["request-id"]
        original_status = git_repository.status
        self.assertFault(
            failure,
            request_id,
            "abortRepoCreation",
            translated_path,
            auth_params,
        )

        # If it's not expected to fail because the repo isn't there,
        # make sure the repository was not changed in any way.
        if not isinstance(failure, faults.GitRepositoryNotFound):
            repo = removeSecurityProxy(
                getUtility(IGitLookup).getByHostingPath(translated_path)
            )
            self.assertEqual(GitRepositoryStatus.CREATING, repo.status)
            self.assertEqual(original_status, git_repository.status)

    def assertAbortRepoCreationUnauthorized(
        self, requester, git_repository, can_authenticate=True, **auth_kwargs
    ):
        failure = faults.Unauthorized
        self.assertAbortRepoCreationFails(
            failure,
            requester,
            git_repository,
            can_authenticate=can_authenticate,
            **auth_kwargs,
        )

    def assertCreates(
        self,
        requester,
        path,
        can_authenticate=False,
        private=False,
        async_create=True,
    ):
        auth_params = _make_auth_params(
            requester, can_authenticate=can_authenticate
        )
        request_id = auth_params["request-id"]
        translation = self.assertDoesNotFault(
            request_id, "translatePath", path, "write", auth_params
        )
        login(ANONYMOUS)
        repository = getUtility(IGitRepositorySet).getByPath(
            requester, path.lstrip("/")
        )
        self.assertIsNotNone(repository)
        self.assertEqual(requester, repository.registrant)

        cloned_from = repository.getClonedFrom()
        expected_translation = {
            "path": repository.getInternalPath(),
            "readable": True,
            "writable": True,
            "trailing": "",
            "private": private,
        }

        # This should be the case if GIT_ASYNC_CREATE_REPO feature flag is
        # enabled.
        if async_create:
            expected_translation["creation_params"] = {
                "clone_from": (
                    cloned_from.getInternalPath() if cloned_from else None
                )
            }
            expected_status = GitRepositoryStatus.CREATING
            expected_hosting_calls = 0
            expected_hosting_call_args = []
            expected_hosting_call_kwargs = []
        else:
            expected_status = GitRepositoryStatus.AVAILABLE
            expected_hosting_calls = 1
            expected_hosting_call_args = [(repository.getInternalPath(),)]
            expected_hosting_call_kwargs = [
                {
                    "clone_from": (
                        cloned_from.getInternalPath() if cloned_from else None
                    ),
                    "async_create": False,
                }
            ]

        self.assertEqual(GitRepositoryType.HOSTED, repository.repository_type)
        self.assertEqual(expected_translation, translation)
        self.assertEqual(
            expected_hosting_calls, self.hosting_fixture.create.call_count
        )
        self.assertEqual(
            expected_hosting_call_args,
            self.hosting_fixture.create.extract_args(),
        )
        self.assertEqual(
            expected_hosting_call_kwargs,
            self.hosting_fixture.create.extract_kwargs(),
        )
        self.assertEqual(expected_status, repository.status)
        return repository

    def assertCreatesFromClone(
        self, requester, path, cloned_from, can_authenticate=False
    ):
        self.assertCreates(requester, path, can_authenticate)
        self.assertEqual(0, self.hosting_fixture.create.call_count)

    def assertHasRefPermissions(
        self, requester, repository, ref_paths, permissions, **auth_kwargs
    ):
        auth_params = _make_auth_params(requester, **auth_kwargs)
        request_id = auth_params["request-id"]
        translated_path = removeSecurityProxy(repository).getInternalPath()
        ref_paths = [xmlrpc.client.Binary(ref_path) for ref_path in ref_paths]
        results = self.assertDoesNotFault(
            request_id,
            "checkRefPermissions",
            translated_path,
            ref_paths,
            auth_params,
        )
        self.assertThat(
            results,
            MatchesSetwise(
                *(
                    MatchesListwise(
                        [
                            MatchesAll(
                                IsInstance(xmlrpc.client.Binary),
                                MatchesStructure.byEquality(data=ref_path),
                            ),
                            Equals(ref_permissions),
                        ]
                    )
                    for ref_path, ref_permissions in permissions.items()
                )
            ),
        )

    def assertHasMergeProposalURL(
        self, repository, pushed_branch, auth_params
    ):
        base_url = canonical_url(repository, rootsite="code")
        expected_mp_url = "%s/+ref/%s/+register-merge" % (
            base_url,
            quote(pushed_branch),
        )
        result = self.git_api.getMergeProposalURL(
            repository.getInternalPath(), pushed_branch, auth_params
        )
        self.assertEqual(expected_mp_url, result)

    def test_translatePath_private_repository(self):
        requester = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                owner=requester, information_type=InformationType.USERDATA
            )
        )
        path = "/%s" % repository.unique_name
        self.assertTranslates(
            requester, path, repository, writable=True, private=True
        )

    def test_translatePath_cannot_see_private_repository(self):
        requester = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        path = "/%s" % repository.unique_name
        self.assertGitRepositoryNotFound(requester, path)

    def test_translatePath_anonymous_cannot_see_private_repository(self):
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        path = "/%s" % repository.unique_name
        self.assertGitRepositoryNotFound(None, path, can_authenticate=False)
        self.assertUnauthorized(None, path, can_authenticate=True)

    def test_translatePath_anonymous_cannot_see_private_distro_repository(
        self,
    ):
        with person_logged_in(self.factory.makePerson()) as owner:
            distro = self.factory.makeDistribution(
                owner=owner, information_type=InformationType.PROPRIETARY
            )
            dsp = self.factory.makeDistributionSourcePackage(
                distribution=distro
            )
            repository = removeSecurityProxy(
                self.factory.makeGitRepository(
                    registrant=owner, owner=owner, target=dsp
                )
            )
            path = "/%s" % repository.unique_name
        self.assertGitRepositoryNotFound(None, path, can_authenticate=False)
        self.assertUnauthorized(None, path, can_authenticate=True)

    def test_translatePath_team_unowned(self):
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(self.factory.makePerson())
        repository = self.factory.makeGitRepository(owner=team)
        path = "/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository, writable=False)
        self.assertPermissionDenied(requester, path, permission="write")

    def test_translatePath_imported(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(
            owner=requester, repository_type=GitRepositoryType.IMPORTED
        )
        path = "/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository, writable=False)
        self.assertPermissionDenied(requester, path, permission="write")

    def test_translatePath_create_personal_team_denied(self):
        # translatePath refuses to create a personal repository for a team
        # of which the requester is not a member.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam()
        message = "%s is not a member of %s" % (
            requester.displayname,
            team.displayname,
        )
        self.assertPermissionDenied(
            requester,
            "/~%s/+git/random" % team.name,
            message=message,
            permission="write",
        )

    def test_translatePath_create_other_user(self):
        # Creating a repository for another user fails.
        requester = self.factory.makePerson()
        other_person = self.factory.makePerson()
        project = self.factory.makeProduct()
        name = self.factory.getUniqueString()
        path = "/~%s/%s/+git/%s" % (other_person.name, project.name, name)
        message = "%s cannot create Git repositories owned by %s" % (
            requester.displayname,
            other_person.displayname,
        )
        self.assertPermissionDenied(
            requester, path, message=message, permission="write"
        )

    def test_translatePath_create_project_not_owner(self):
        # Somebody without edit permission on the project cannot create a
        # repository and immediately set it as the default for that project.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        path = "/%s" % project.name
        message = "%s cannot create Git repositories owned by %s" % (
            requester.displayname,
            project.owner.displayname,
        )
        initial_count = getUtility(IAllGitRepositories).count()
        self.assertPermissionDenied(
            requester, path, message=message, permission="write"
        )
        # No repository was created.
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count()
        )

    def test_translatePath_create_oci_project_not_owner(self):
        # Somebody without edit permission on the OCI project cannot create
        # a repository and immediately set it as the default for that
        # project.
        requester = self.factory.makePerson()
        distribution = self.factory.makeDistribution(
            oci_project_admin=self.factory.makeTeam()
        )
        oci_project = self.factory.makeOCIProject(pillar=distribution)
        path = "/%s/+oci/%s" % (oci_project.pillar.name, oci_project.name)
        message = "%s is not a member of %s" % (
            requester.displayname,
            oci_project.pillar.oci_project_admin.displayname,
        )
        initial_count = getUtility(IAllGitRepositories).count()
        self.assertPermissionDenied(
            requester, path, message=message, permission="write"
        )
        # No repository was created.
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count()
        )

    def test_translatePath_grant_to_other(self):
        requester = self.factory.makePerson()
        other_person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        rule = self.factory.makeGitRule(
            repository, ref_pattern="refs/heads/stable/next"
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=other_person, can_force_push=True
        )
        path = "/%s" % repository.unique_name
        self.assertTranslates(
            other_person, path, repository, writable=True, private=False
        )

    def test_translatePath_grant_but_no_access(self):
        requester = self.factory.makePerson()
        grant_person = self.factory.makePerson()
        other_person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        rule = self.factory.makeGitRule(
            repository, ref_pattern="refs/heads/stable/next"
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=grant_person, can_force_push=True
        )
        path = "/%s" % repository.unique_name
        self.assertTranslates(
            other_person, path, repository, writable=False, private=False
        )

    def test_translatePath_grant_to_other_private(self):
        requester = self.factory.makePerson()
        other_person = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(
                owner=requester, information_type=InformationType.USERDATA
            )
        )
        rule = self.factory.makeGitRule(
            repository, ref_pattern="refs/heads/stable/next"
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=other_person, can_force_push=True
        )
        path = "/%s" % repository.unique_name
        self.assertGitRepositoryNotFound(
            other_person, path, can_authenticate=True
        )

    def _make_scenario_one_repository(self):
        user_a = self.factory.makePerson()
        user_b = self.factory.makePerson()
        user_c = self.factory.makePerson()
        stable_team = self.factory.makeTeam(members=[user_a, user_b])
        next_team = self.factory.makeTeam(members=[user_b, user_c])

        repository = removeSecurityProxy(
            self.factory.makeGitRepository(owner=user_a)
        )

        rule = self.factory.makeGitRule(
            repository, ref_pattern="refs/heads/stable/next"
        )
        self.factory.makeGitRuleGrant(
            rule=rule,
            grantee=GitGranteeType.REPOSITORY_OWNER,
            can_force_push=True,
        )

        rule = self.factory.makeGitRule(
            repository, ref_pattern="refs/heads/stable/protected"
        )
        self.factory.makeGitRuleGrant(rule=rule, grantee=stable_team)

        rule = self.factory.makeGitRule(
            repository, ref_pattern="refs/heads/archived/*"
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=GitGranteeType.REPOSITORY_OWNER
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=user_b, can_create=True
        )

        rule = self.factory.makeGitRule(
            repository, ref_pattern="refs/heads/stable/*"
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=stable_team, can_push=True
        )

        rule = self.factory.makeGitRule(
            repository, ref_pattern="refs/heads/*/next"
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=next_team, can_force_push=True
        )

        rule = self.factory.makeGitRule(repository, ref_pattern="refs/tags/*")
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=GitGranteeType.REPOSITORY_OWNER, can_create=True
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=stable_team, can_create=True
        )

        test_ref_paths = [
            b"refs/heads/stable/next",
            b"refs/heads/stable/protected",
            b"refs/heads/stable/foo",
            b"refs/heads/archived/foo",
            b"refs/heads/foo/next",
            b"refs/heads/unprotected",
            b"refs/tags/1.0",
        ]

        return (
            user_a,
            user_b,
            user_c,
            stable_team,
            next_team,
            repository,
            test_ref_paths,
        )

    def test_checkRefPermissions_scenario_one_user_a(self):
        user_a, _, _, _, _, repo, paths = self._make_scenario_one_repository()
        self.assertHasRefPermissions(
            user_a,
            repo,
            paths,
            {
                b"refs/heads/stable/next": ["push", "force_push"],
                b"refs/heads/stable/protected": ["create", "push"],
                b"refs/heads/stable/foo": ["create", "push"],
                b"refs/heads/archived/foo": [],
                b"refs/heads/foo/next": ["create", "push"],
                b"refs/heads/unprotected": ["create", "push", "force_push"],
                b"refs/tags/1.0": ["create"],
            },
        )

    def test_checkRefPermissions_scenario_one_user_b(self):
        _, user_b, _, _, _, repo, paths = self._make_scenario_one_repository()
        self.assertHasRefPermissions(
            user_b,
            repo,
            paths,
            {
                b"refs/heads/stable/next": ["push", "force_push"],
                b"refs/heads/stable/protected": [],
                b"refs/heads/stable/foo": ["push"],
                b"refs/heads/archived/foo": ["create"],
                b"refs/heads/foo/next": ["push", "force_push"],
                b"refs/heads/unprotected": [],
                b"refs/tags/1.0": ["create"],
            },
        )

    def test_checkRefPermissions_scenario_one_user_c(self):
        _, _, user_c, _, _, repo, paths = self._make_scenario_one_repository()
        self.assertHasRefPermissions(
            user_c,
            repo,
            paths,
            {
                b"refs/heads/stable/next": ["push", "force_push"],
                b"refs/heads/stable/protected": [],
                b"refs/heads/stable/foo": [],
                b"refs/heads/archived/foo": [],
                b"refs/heads/foo/next": ["push", "force_push"],
                b"refs/heads/unprotected": [],
                b"refs/tags/1.0": [],
            },
        )

    def test_checkRefPermissions_scenario_one_user_d(self):
        user_d = self.factory.makePerson()
        _, _, _, _, _, repo, paths = self._make_scenario_one_repository()
        self.assertHasRefPermissions(
            user_d,
            repo,
            paths,
            {
                b"refs/heads/stable/next": [],
                b"refs/heads/stable/protected": [],
                b"refs/heads/stable/foo": [],
                b"refs/heads/archived/foo": [],
                b"refs/heads/foo/next": [],
                b"refs/heads/unprotected": [],
                b"refs/tags/1.0": [],
            },
        )

    def _make_scenario_two_repository(self):
        user_a = self.factory.makePerson()
        user_b = self.factory.makePerson()

        repository = removeSecurityProxy(
            self.factory.makeGitRepository(owner=user_a)
        )

        rule = self.factory.makeGitRule(
            repository, ref_pattern="refs/heads/master"
        )
        self.factory.makeGitRuleGrant(rule=rule, grantee=user_b, can_push=True)

        rule = self.factory.makeGitRule(repository, ref_pattern="refs/heads/*")
        self.factory.makeGitRuleGrant(
            rule=rule,
            grantee=GitGranteeType.REPOSITORY_OWNER,
            can_create=True,
            can_push=True,
            can_force_push=True,
        )

        rule = self.factory.makeGitRule(repository, ref_pattern="refs/tags/*")
        self.factory.makeGitRuleGrant(rule=rule, grantee=user_b, can_push=True)

        test_ref_paths = [
            b"refs/heads/master",
            b"refs/heads/foo",
            b"refs/tags/1.0",
            b"refs/other",
        ]
        return user_a, user_b, repository, test_ref_paths

    def test_checkRefPermissions_scenario_two_user_a(self):
        user_a, _, repo, paths = self._make_scenario_two_repository()
        self.assertHasRefPermissions(
            user_a,
            repo,
            paths,
            {
                b"refs/heads/master": ["create", "push", "force_push"],
                b"refs/heads/foo": ["create", "push", "force_push"],
                b"refs/tags/1.0": ["create", "push"],
                b"refs/other": ["create", "push", "force_push"],
            },
        )

    def test_checkRefPermissions_scenario_two_user_b(self):
        _, user_b, repo, paths = self._make_scenario_two_repository()
        self.assertHasRefPermissions(
            user_b,
            repo,
            paths,
            {
                b"refs/heads/master": ["push"],
                b"refs/heads/foo": [],
                b"refs/tags/1.0": ["push"],
                b"refs/other": [],
            },
        )

    def test_checkRefPermissions_scenario_two_user_c(self):
        _, _, repo, paths = self._make_scenario_two_repository()
        user_c = self.factory.makePerson()
        self.assertHasRefPermissions(
            user_c,
            repo,
            paths,
            {
                b"refs/heads/master": [],
                b"refs/heads/foo": [],
                b"refs/tags/1.0": [],
                b"refs/other": [],
            },
        )

    def test_checkRefPermissions_bytes(self):
        owner = self.factory.makePerson()
        grantee = self.factory.makePerson()
        no_privileges = self.factory.makePerson()
        repository = removeSecurityProxy(
            self.factory.makeGitRepository(owner=owner)
        )
        self.factory.makeGitRuleGrant(
            repository=repository,
            ref_pattern="refs/heads/next/*",
            grantee=grantee,
            can_push=True,
        )
        paths = [
            # Properly-encoded UTF-8.
            "refs/heads/next/\N{BLACK HEART SUIT}".encode(),
            # Non-UTF-8.  (git does not require any particular encoding for
            # ref paths; non-UTF-8 ones won't work well everywhere, but it's
            # at least possible to round-trip them through Launchpad.)
            b"refs/heads/next/\x80",
        ]

        self.assertHasRefPermissions(
            grantee, repository, paths, {path: ["push"] for path in paths}
        )
        login(ANONYMOUS)
        self.assertHasRefPermissions(
            no_privileges, repository, paths, {path: [] for path in paths}
        )

    def test_checkRefPermissions_nonexistent_repository(self):
        requester = self.factory.makePerson()
        self.assertFault(
            faults.GitRepositoryNotFound("nonexistent"),
            None,
            "checkRefPermissions",
            "nonexistent",
            [],
            {"uid": requester.id},
        )

    def test_getMergeProposalURL__nonexistent_repository(self):
        requester = self.factory.makePerson()
        self.assertFault(
            faults.GitRepositoryNotFound("nonexistent"),
            None,
            "getMergeProposalURL",
            "nonexistent",
            "branch1",
            {"uid": requester.id},
        )


class TestGitAPI(TestGitAPIMixin, TestCaseWithFactory):
    """Tests for the implementation of `IGitAPI`."""

    layer = LaunchpadFunctionalLayer

    def test_confirm_git_repository_creation(self):
        owner = self.factory.makePerson()
        repo = removeSecurityProxy(self.factory.makeGitRepository(owner=owner))
        repo.status = GitRepositoryStatus.CREATING
        self.assertConfirmsRepoCreation(owner, repo)

    def test_launchpad_service_confirm_git_repository_creation(self):
        owner = self.factory.makePerson()
        repo = removeSecurityProxy(self.factory.makeGitRepository(owner=owner))
        repo.status = GitRepositoryStatus.CREATING
        self.assertConfirmsRepoCreation(LAUNCHPAD_SERVICES, repo)

    def test_only_requester_can_confirm_git_repository_creation(self):
        requester = self.factory.makePerson()
        repo = removeSecurityProxy(self.factory.makeGitRepository())
        repo.status = GitRepositoryStatus.CREATING

        self.assertConfirmRepoCreationUnauthorized(requester, repo)

    def test_confirm_git_repository_creation_of_non_existing_repository(self):
        owner = self.factory.makePerson()
        repo = removeSecurityProxy(self.factory.makeGitRepository(owner=owner))
        repo.status = GitRepositoryStatus.CREATING
        repo.destroySelf()

        expected_failure = faults.GitRepositoryNotFound(str(repo.id))
        self.assertConfirmRepoCreationFails(expected_failure, owner, repo)

    def test_confirm_git_repository_creation_public_code_import(self):
        # A code import worker with a suitable macaroon can write to a
        # repository associated with a running code import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]

        repo = removeSecurityProxy(code_imports[0].git_repository)
        repo.status = GitRepositoryStatus.CREATING

        self.assertConfirmRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[0].serialize()
        )
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertConfirmRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[1].serialize()
        )
        self.assertConfirmRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES,
            repo,
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertConfirmRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw="nonsense"
        )
        self.assertConfirmRepoCreationUnauthorized(
            code_imports[0].registrant,
            repo,
            macaroon_raw=macaroons[0].serialize(),
        )
        self.assertConfirmsRepoCreation(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[0].serialize()
        )

    def test_confirm_git_repository_creation_private_code_import(self):
        # A code import worker with a suitable macaroon can write to a
        # repository associated with a running private code import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        private_repository = code_imports[0].git_repository
        removeSecurityProxy(private_repository).transitionToInformationType(
            InformationType.PRIVATESECURITY, private_repository.owner
        )
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]

        repo = removeSecurityProxy(code_imports[0].git_repository)
        repo.status = GitRepositoryStatus.CREATING

        self.assertConfirmRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[0].serialize()
        )
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertConfirmRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[1].serialize()
        )
        self.assertConfirmRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES,
            repo,
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertConfirmRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw="nonsense"
        )
        self.assertConfirmRepoCreationUnauthorized(
            code_imports[0].registrant,
            repo,
            macaroon_raw=macaroons[0].serialize(),
        )
        self.assertConfirmsRepoCreation(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[0].serialize()
        )

    def test_confirm_git_repository_creation_user_macaroon(self):
        # A user with a suitable macaroon can write to the corresponding
        # repository, but not others, even if they own them.
        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=requester) for _ in range(2)
        ]
        repositories.append(
            self.factory.makeGitRepository(
                owner=requester,
                information_type=InformationType.PRIVATESECURITY,
            )
        )
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        with person_logged_in(requester):
            macaroons = [
                removeSecurityProxy(issuer).issueMacaroon(
                    repository, user=requester
                )
                for repository in repositories
            ]
        for i, repository in enumerate(repositories):
            login(ANONYMOUS)
            repository = removeSecurityProxy(repository)
            repository.status = GitRepositoryStatus.CREATING

            correct_macaroon = macaroons[i]
            wrong_macaroon = macaroons[(i + 1) % len(macaroons)]

            self.assertConfirmRepoCreationUnauthorized(
                requester, repository, macaroon_raw=wrong_macaroon.serialize()
            )
            self.assertConfirmRepoCreationUnauthorized(
                requester,
                repository,
                macaroon_raw=Macaroon(
                    location=config.vhost.mainsite.hostname,
                    identifier="another",
                    key="another-secret",
                ).serialize(),
            )
            self.assertConfirmRepoCreationUnauthorized(
                requester, repository, macaroon_raw="nonsense"
            )
            self.assertConfirmsRepoCreation(
                requester,
                repository,
                macaroon_raw=correct_macaroon.serialize(),
            )

    def test_confirm_git_repository_creation_user_mismatch(self):
        # confirmRepoCreation refuses macaroons in the case where the user
        # doesn't match what the issuer claims was verified.
        issuer = FakeMacaroonIssuer()

        self.useFixture(
            ZopeUtilityFixture(issuer, IMacaroonIssuer, name="test")
        )
        repository = self.factory.makeGitRepository()

        macaroon = issuer.issueMacaroon(repository)
        requesters = [self.factory.makePerson() for _ in range(2)]
        for verified_user, unauthorized in (
            (NO_USER, requesters + [None]),
            (requesters[0], [LAUNCHPAD_SERVICES, requesters[1], None]),
            (None, [LAUNCHPAD_SERVICES] + requesters + [None]),
        ):
            repository = removeSecurityProxy(repository)
            repository.status = GitRepositoryStatus.CREATING
            issuer._verified_user = verified_user
            for requester in unauthorized:
                login(ANONYMOUS)
                self.assertConfirmRepoCreationUnauthorized(
                    requester, repository, macaroon_raw=macaroon.serialize()
                )

    def test_confirm_git_repository_access_token(self):
        # An access token cannot be used to authorize confirming repository
        # creation.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(
            owner=requester, status=GitRepositoryStatus.CREATING
        )
        _, token = self.factory.makeAccessToken(
            owner=requester,
            target=repository,
            scopes=[AccessTokenScope.REPOSITORY_PUSH],
        )
        self.assertConfirmRepoCreationUnauthorized(
            requester,
            repository,
            access_token_id=removeSecurityProxy(token).id,
        )

    def test_abort_repo_creation(self):
        requester = self.factory.makePerson()
        repo = self.factory.makeGitRepository(owner=requester)
        repo = removeSecurityProxy(repo)
        repo.status = GitRepositoryStatus.CREATING
        self.assertAbortsRepoCreation(requester, repo)

    def test_launchpad_service_abort_git_repository_creation(self):
        owner = self.factory.makePerson()
        repo = removeSecurityProxy(self.factory.makeGitRepository(owner=owner))
        repo.status = GitRepositoryStatus.CREATING
        self.assertAbortsRepoCreation(LAUNCHPAD_SERVICES, repo)

    def test_only_requester_can_abort_git_repository_creation(self):
        requester = self.factory.makePerson()
        repo = removeSecurityProxy(self.factory.makeGitRepository())
        repo.status = GitRepositoryStatus.CREATING

        self.assertAbortRepoCreationUnauthorized(requester, repo)

    def test_abort_git_repository_creation_public_code_import(self):
        # A code import worker with a suitable macaroon can write to a
        # repository associated with a running code import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]

        repo = removeSecurityProxy(code_imports[0].git_repository)
        repo.status = GitRepositoryStatus.CREATING

        self.assertAbortRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[0].serialize()
        )
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertAbortRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[1].serialize()
        )
        self.assertAbortRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES,
            repo,
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertAbortRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw="nonsense"
        )
        self.assertAbortRepoCreationUnauthorized(
            code_imports[0].registrant,
            repo,
            macaroon_raw=macaroons[0].serialize(),
        )
        self.assertConfirmsRepoCreation(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[0].serialize()
        )

    def test_abort_git_repository_creation_private_code_import(self):
        # A code import worker with a suitable macaroon can write to a
        # repository associated with a running private code import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        private_repository = code_imports[0].git_repository
        removeSecurityProxy(private_repository).transitionToInformationType(
            InformationType.PRIVATESECURITY, private_repository.owner
        )
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]

        repo = removeSecurityProxy(code_imports[0].git_repository)
        repo.status = GitRepositoryStatus.CREATING

        self.assertAbortRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[0].serialize()
        )
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertAbortRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[1].serialize()
        )
        self.assertAbortRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES,
            repo,
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertAbortRepoCreationUnauthorized(
            LAUNCHPAD_SERVICES, repo, macaroon_raw="nonsense"
        )
        self.assertAbortRepoCreationUnauthorized(
            code_imports[0].registrant,
            repo,
            macaroon_raw=macaroons[0].serialize(),
        )
        self.assertAbortsRepoCreation(
            LAUNCHPAD_SERVICES, repo, macaroon_raw=macaroons[0].serialize()
        )

    def test_abort_git_repository_creation_user_macaroon(self):
        # A user with a suitable macaroon can write to the corresponding
        # repository, but not others, even if they own them.
        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=requester) for _ in range(2)
        ]
        repositories.append(
            self.factory.makeGitRepository(
                owner=requester,
                information_type=InformationType.PRIVATESECURITY,
            )
        )
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        with person_logged_in(requester):
            macaroons = [
                removeSecurityProxy(issuer).issueMacaroon(
                    repository, user=requester
                )
                for repository in repositories
            ]
        for i, repository in enumerate(repositories):
            login(ANONYMOUS)
            repository = removeSecurityProxy(repository)
            repository.status = GitRepositoryStatus.CREATING

            correct_macaroon = macaroons[i]
            wrong_macaroon = macaroons[(i + 1) % len(macaroons)]

            self.assertAbortRepoCreationUnauthorized(
                requester, repository, macaroon_raw=wrong_macaroon.serialize()
            )
            self.assertAbortRepoCreationUnauthorized(
                requester,
                repository,
                macaroon_raw=Macaroon(
                    location=config.vhost.mainsite.hostname,
                    identifier="another",
                    key="another-secret",
                ).serialize(),
            )
            self.assertAbortRepoCreationUnauthorized(
                requester, repository, macaroon_raw="nonsense"
            )
            self.assertAbortsRepoCreation(
                requester,
                repository,
                macaroon_raw=correct_macaroon.serialize(),
            )

    def test_abort_git_repository_creation_user_mismatch(self):
        # confirmRepoCreation refuses macaroons in the case where the user
        # doesn't match what the issuer claims was verified.
        issuer = FakeMacaroonIssuer()

        self.useFixture(
            ZopeUtilityFixture(issuer, IMacaroonIssuer, name="test")
        )
        repository = self.factory.makeGitRepository()

        macaroon = issuer.issueMacaroon(repository)
        requesters = [self.factory.makePerson() for _ in range(2)]
        for verified_user, unauthorized in (
            (NO_USER, requesters + [None]),
            (requesters[0], [LAUNCHPAD_SERVICES, requesters[1], None]),
            (None, [LAUNCHPAD_SERVICES] + requesters + [None]),
        ):
            repository = removeSecurityProxy(repository)
            repository.status = GitRepositoryStatus.CREATING
            issuer._verified_user = verified_user
            for requester in unauthorized:
                login(ANONYMOUS)
                self.assertAbortRepoCreationUnauthorized(
                    requester, repository, macaroon_raw=macaroon.serialize()
                )

    def test_abort_git_repository_access_token(self):
        # An access token cannot be used to authorize aborting repository
        # creation.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(
            owner=requester, status=GitRepositoryStatus.CREATING
        )
        _, token = self.factory.makeAccessToken(
            owner=requester,
            target=repository,
            scopes=[AccessTokenScope.REPOSITORY_PUSH],
        )
        self.assertAbortRepoCreationUnauthorized(
            requester,
            repository,
            access_token_id=removeSecurityProxy(token).id,
        )

    def test_abort_git_repository_creation_of_non_existing_repository(self):
        owner = self.factory.makePerson()
        repo = removeSecurityProxy(self.factory.makeGitRepository(owner=owner))
        repo.status = GitRepositoryStatus.CREATING
        repo.destroySelf()

        expected_failure = faults.GitRepositoryNotFound(str(repo.id))
        self.assertAbortRepoCreationFails(expected_failure, owner, repo)

    def test_translatePath_cannot_translate(self):
        # Sometimes translatePath will not know how to translate a path.
        # When this happens, it returns a Fault saying so, including the
        # path it couldn't translate.
        requester = self.factory.makePerson()
        self.assertGitRepositoryNotFound(requester, "/untranslatable")

    def test_translatePath_repository(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = "/%s" % repository.unique_name
        self.assertTranslates(requester, path, repository)

    def test_translatePath_repository_with_no_leading_slash(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = repository.unique_name
        self.assertTranslates(requester, path, repository)

    def test_translatePath_repository_with_trailing_slash(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = "/%s/" % repository.unique_name
        self.assertTranslates(requester, path, repository)

    def test_translatePath_repository_with_trailing_segments(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        path = "/%s/foo/bar" % repository.unique_name
        self.assertTranslates(requester, path, repository, trailing="foo/bar")

    def test_translatePath_no_such_repository(self):
        requester = self.factory.makePerson()
        path = "/%s/+git/no-such-repository" % requester.name
        self.assertGitRepositoryNotFound(requester, path)

    def test_translatePath_no_such_repository_non_ascii(self):
        requester = self.factory.makePerson()
        path = "/%s/+git/\N{LATIN SMALL LETTER I WITH DIAERESIS}" % (
            requester.name
        )
        self.assertGitRepositoryNotFound(requester, path)

    def test_translatePath_anonymous_public_repository(self):
        repository = self.factory.makeGitRepository()
        path = "/%s" % repository.unique_name
        self.assertTranslates(
            None, path, repository, can_authenticate=False, writable=False
        )
        self.assertTranslates(
            None, path, repository, can_authenticate=True, writable=False
        )

    def test_translatePath_owned(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        path = "/%s" % repository.unique_name
        self.assertTranslates(
            requester, path, repository, permission="write", writable=True
        )

    def test_translatePath_team_owned(self):
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(requester)
        repository = self.factory.makeGitRepository(owner=team)
        path = "/%s" % repository.unique_name
        self.assertTranslates(
            requester, path, repository, permission="write", writable=True
        )

    def test_translatePath_shortened_path(self):
        # translatePath translates the shortened path to a repository.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        with person_logged_in(repository.target.owner):
            getUtility(IGitRepositorySet).setDefaultRepository(
                repository.target, repository
            )
        path = "/%s" % repository.target.name
        self.assertTranslates(requester, path, repository)

    def test_translatePath_create_project_async(self):
        # translatePath creates a project repository that doesn't exist, if
        # it can.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        self.assertCreates(
            requester, "/~%s/%s/+git/random" % (requester.name, project.name)
        )

    def test_translatePath_create_project_sync(self):
        self.useFixture(FeatureFixture({GIT_ASYNC_CREATE_REPO: ""}))
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        self.assertCreates(
            requester,
            "/~%s/%s/+git/random" % (requester.name, project.name),
            async_create=False,
        )

    def test_translatePath_create_project_blocks_duplicate_calls(self):
        # translatePath creates a project repository that doesn't exist,
        # but blocks any further request to create the same repository.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        path = "/~%s/%s/+git/random" % (requester.name, project.name)
        self.assertCreates(requester, path)

        auth_params = _make_auth_params(requester, can_authenticate=True)
        request_id = auth_params["request-id"]
        self.assertFault(
            faults.GitRepositoryBeingCreated,
            request_id,
            "translatePath",
            path,
            "write",
            auth_params,
        )

    def test_translatePath_create_project_clone_from_target_default(self):
        # translatePath creates a project repository cloned from the target
        # default if it exists.
        target = self.factory.makeProduct()
        repository = self.factory.makeGitRepository(
            owner=target.owner, target=target
        )
        with person_logged_in(target.owner):
            self.repository_set.setDefaultRepository(target, repository)
            self.assertCreatesFromClone(
                target.owner,
                "/~%s/%s/+git/random" % (target.owner.name, target.name),
                repository,
            )

    def test_translatePath_create_project_clone_from_owner_default(self):
        # translatePath creates a project repository cloned from the owner
        # default if it exists and the target default does not.
        target = self.factory.makeProduct()
        repository = self.factory.makeGitRepository(
            owner=target.owner, target=target
        )
        with person_logged_in(target.owner) as user:
            self.repository_set.setDefaultRepositoryForOwner(
                target.owner, target, repository, user
            )
            self.assertCreatesFromClone(
                target.owner,
                "/~%s/%s/+git/random" % (target.owner.name, target.name),
                repository,
            )

    def test_translatePath_create_package(self):
        # translatePath creates a package repository that doesn't exist, if
        # it can.
        requester = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        self.assertCreates(
            requester,
            "/~%s/%s/+source/%s/+git/random"
            % (
                requester.name,
                dsp.distribution.name,
                dsp.sourcepackagename.name,
            ),
        )

    def test_translatePath_create_oci_project(self):
        # translatePath creates an OCI project repository that doesn't
        # exist, if it can.
        requester = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        self.assertCreates(
            requester,
            "/~%s/%s/+oci/%s/+git/random"
            % (requester.name, oci_project.pillar.name, oci_project.name),
        )

    def test_translatePath_create_personal(self):
        # translatePath creates a personal repository that doesn't exist, if
        # it can.
        requester = self.factory.makePerson()
        self.assertCreates(requester, "/~%s/+git/random" % requester.name)

    def test_translatePath_create_personal_team(self):
        # translatePath creates a personal repository for a team of which
        # the requester is a member.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(members=[requester])
        self.assertCreates(requester, "/~%s/+git/random" % team.name)

    def test_translatePath_create_native_string(self):
        # On Python 2, ASCII strings come in as native strings, not Unicode
        # strings. They work fine too.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        path = "/~%s/%s/+git/random" % (requester.name, project.name)
        self.assertCreates(requester, six.ensure_str(path))

    def test_translatePath_anonymous_cannot_create(self):
        # Anonymous users cannot create repositories.
        project = self.factory.makeProject()
        self.assertGitRepositoryNotFound(
            None,
            "/%s" % project.name,
            permission="write",
            can_authenticate=False,
        )
        self.assertUnauthorized(
            None,
            "/%s" % project.name,
            permission="write",
            can_authenticate=True,
        )

    def test_translatePath_create_invalid_namespace(self):
        # Trying to create a repository at a path that isn't valid for Git
        # repositories returns a PermissionDenied fault.
        requester = self.factory.makePerson()
        path = "/~%s" % requester.name
        message = "'%s' is not a valid Git repository path." % path.strip("/")
        self.assertPermissionDenied(
            requester, path, message=message, permission="write"
        )

    def test_translatePath_create_no_such_person(self):
        # Creating a repository for a non-existent person fails.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester,
            "/~nonexistent/+git/random",
            "User/team 'nonexistent' does not exist.",
            permission="write",
        )

    def test_translatePath_create_no_such_project(self):
        # Creating a repository for a non-existent project fails.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester,
            "/~%s/nonexistent/+git/random" % requester.name,
            "Project 'nonexistent' does not exist.",
            permission="write",
        )

    def test_translatePath_create_no_such_person_or_project(self):
        # If neither the person nor the project are found, then the missing
        # person is reported in preference.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester,
            "/~nonexistent/nonexistent/+git/random",
            "User/team 'nonexistent' does not exist.",
            permission="write",
        )

    def test_translatePath_create_invalid_project(self):
        # Creating a repository with an invalid project name fails.
        requester = self.factory.makePerson()
        self.assertNotFound(
            requester,
            "/_bad_project/+git/random",
            "Project '_bad_project' does not exist.",
            permission="write",
        )

    def test_translatePath_create_missing_sourcepackagename(self):
        # If translatePath is asked to create a repository for a missing
        # source package, it will create the source package.
        requester = self.factory.makePerson()
        distro = self.factory.makeDistribution()
        repository_name = self.factory.getUniqueString()
        path = "/~%s/%s/+source/new-package/+git/%s" % (
            requester.name,
            distro.name,
            repository_name,
        )
        repository = self.assertCreates(requester, path)
        self.assertEqual(
            "new-package", repository.target.sourcepackagename.name
        )

    def test_translatePath_create_invalid_sourcepackagename(self):
        # Creating a repository for an invalid source package name fails.
        requester = self.factory.makePerson()
        distro = self.factory.makeDistribution()
        repository_name = self.factory.getUniqueString()
        path = "/~%s/%s/+source/new package/+git/%s" % (
            requester.name,
            distro.name,
            repository_name,
        )
        self.assertInvalidSourcePackageName(
            requester, path, "new package", permission="write"
        )

    def test_translatePath_create_bad_name(self):
        # Creating a repository with an invalid name fails.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        invalid_name = "invalid name!"
        path = "/~%s/%s/+git/%s" % (requester.name, project.name, invalid_name)
        # LaunchpadValidationError unfortunately assumes its output is
        # always HTML, so it ends up double-escaped in XML-RPC faults.
        message = html_escape(
            "Invalid Git repository name '%s'. %s"
            % (invalid_name, GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE)
        )
        self.assertInvalidBranchName(
            requester, path, message, permission="write"
        )

    def test_translatePath_create_unicode_name(self):
        # Creating a repository with a non-ASCII invalid name fails.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        invalid_name = "invalid\N{LATIN SMALL LETTER E WITH ACUTE}"
        path = "/~%s/%s/+git/%s" % (requester.name, project.name, invalid_name)
        # LaunchpadValidationError unfortunately assumes its output is
        # always HTML, so it ends up double-escaped in XML-RPC faults.
        message = html_escape(
            "Invalid Git repository name '%s'. %s"
            % (invalid_name, GIT_REPOSITORY_NAME_VALIDATION_ERROR_MESSAGE)
        )
        self.assertInvalidBranchName(
            requester, path, message, permission="write"
        )

    def test_translatePath_create_project_default(self):
        # A repository can be created and immediately set as the default for
        # a project.
        requester = self.factory.makePerson()
        owner = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.RESTRICTED,
            members=[requester],
        )
        project = self.factory.makeProduct(owner=owner)
        repository = self.assertCreates(requester, "/%s" % project.name)
        self.assertTrue(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(owner, repository.owner)

    def test_translatePath_create_package_default_denied(self):
        # A repository cannot (yet) be created and immediately set as the
        # default for a package.
        requester = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        path = "/%s/+source/%s" % (
            dsp.distribution.name,
            dsp.sourcepackagename.name,
        )
        message = (
            "Cannot automatically set the default repository for this target; "
            "push to a named repository instead."
        )
        self.assertPermissionDenied(
            requester, path, message=message, permission="write"
        )

    def test_translatePath_create_oci_project_default(self):
        # A repository can be created and immediately set as the default for
        # an OCI project.
        requester = self.factory.makePerson()
        oci_project_admin = self.factory.makeTeam(members=[requester])
        distribution = self.factory.makeDistribution(
            oci_project_admin=oci_project_admin
        )
        oci_project = self.factory.makeOCIProject(pillar=distribution)
        repository = self.assertCreates(
            requester,
            "/%s/+oci/%s" % (oci_project.pillar.name, oci_project.name),
        )
        self.assertTrue(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(oci_project_admin, repository.owner)

    def test_translatePath_create_oci_project_default_no_admin(self):
        # If the OCI project's distribution has no OCI project admin, then a
        # repository cannot (yet) be created and immediately set as the
        # default for that OCI project.
        requester = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        path = "/%s/+oci/%s" % (oci_project.pillar.name, oci_project.name)
        message = (
            "Cannot automatically set the default repository for this target; "
            "push to a named repository instead."
        )
        initial_count = getUtility(IAllGitRepositories).count()
        self.assertPermissionDenied(
            requester, path, message=message, permission="write"
        )
        # No repository was created.
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count()
        )

    def test_translatePath_create_project_owner_default(self):
        # A repository can be created and immediately set as its owner's
        # default for a project.
        requester = self.factory.makePerson()
        project = self.factory.makeProduct()
        repository = self.assertCreates(
            requester, "/~%s/%s" % (requester.name, project.name)
        )
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
            requester, "/~%s/%s" % (team.name, project.name)
        )
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
            requester, "/~%s/%s" % (team.name, project.name)
        )
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(team, repository.owner)

    def test_translatePath_create_package_owner_default(self):
        # A repository can be created and immediately set as its owner's
        # default for a package.
        requester = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        path = "/~%s/%s/+source/%s" % (
            requester.name,
            dsp.distribution.name,
            dsp.sourcepackagename.name,
        )
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
        path = "/~%s/%s/+source/%s" % (
            team.name,
            dsp.distribution.name,
            dsp.sourcepackagename.name,
        )
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
        path = "/~%s/%s/+source/%s" % (
            team.name,
            dsp.distribution.name,
            dsp.sourcepackagename.name,
        )
        repository = self.assertCreates(requester, path)
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(team, repository.owner)

    def test_translatePath_create_oci_project_owner_default(self):
        # A repository can be created and immediately set as its owner's
        # default for an OCI project.
        requester = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        path = "/~%s/%s/+oci/%s" % (
            requester.name,
            oci_project.pillar.name,
            oci_project.name,
        )
        repository = self.assertCreates(requester, path)
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(requester, repository.owner)

    def test_translatePath_create_oci_project_team_owner_default(self):
        # The owner of a team can create a team-owned repository and
        # immediately set it as that team's default for an OCI project.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(owner=requester)
        oci_project = self.factory.makeOCIProject()
        path = "/~%s/%s/+oci/%s" % (
            team.name,
            oci_project.pillar.name,
            oci_project.name,
        )
        repository = self.assertCreates(requester, path)
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(team, repository.owner)

    def test_translatePath_create_oci_project_team_member_default(self):
        # A non-owner member of a team can create a team-owned repository
        # and immediately set it as that team's default for an OCI project.
        requester = self.factory.makePerson()
        team = self.factory.makeTeam(members=[requester])
        oci_project = self.factory.makeOCIProject()
        path = "/~%s/%s/+oci/%s" % (
            team.name,
            oci_project.pillar.name,
            oci_project.name,
        )
        repository = self.assertCreates(requester, path)
        self.assertFalse(repository.target_default)
        self.assertTrue(repository.owner_default)
        self.assertEqual(team, repository.owner)

    def test_translatePath_create_broken_hosting_service(self):
        # If the hosting service is down, trying to create a repository
        # fails and doesn't leave junk around in the Launchpad database.
        self.useFixture(FeatureFixture({GIT_ASYNC_CREATE_REPO: ""}))
        self.hosting_fixture.create.failure = GitRepositoryCreationFault(
            "nothing here", path="123"
        )
        requester = self.factory.makePerson()
        initial_count = getUtility(IAllGitRepositories).count()
        oops_id = self.assertOopsOccurred(
            requester, "/~%s/+git/random" % requester.name, permission="write"
        )
        login(ANONYMOUS)
        self.assertEqual(
            initial_count, getUtility(IAllGitRepositories).count()
        )
        # The error report OOPS ID should match the fault, and the traceback
        # text should show the underlying exception.
        self.assertEqual(1, len(self.oopses))
        self.assertEqual(oops_id, self.oopses[0]["id"])
        self.assertIn(
            "GitRepositoryCreationFault: nothing here",
            self.oopses[0]["tb_text"],
        )

    def test_translatePath_code_import(self):
        # A code import worker with a suitable macaroon can write to a
        # repository associated with a running code import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]
        path = "/%s" % code_imports[0].git_repository.unique_name
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw=macaroons[0].serialize(),
        )
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertTranslates(
            LAUNCHPAD_SERVICES,
            path,
            code_imports[0].git_repository,
            permission="write",
            macaroon_raw=macaroons[0].serialize(),
            writable=True,
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw=macaroons[1].serialize(),
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw="nonsense",
        )
        self.assertUnauthorized(
            code_imports[0].registrant,
            path,
            permission="write",
            macaroon_raw=macaroons[0].serialize(),
        )

    def test_translatePath_private_code_import(self):
        # A code import worker with a suitable macaroon can write to a
        # repository associated with a running private code import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        private_repository = code_imports[0].git_repository
        removeSecurityProxy(private_repository).transitionToInformationType(
            InformationType.PRIVATESECURITY, private_repository.owner
        )
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]
        path = "/%s" % code_imports[0].git_repository.unique_name
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw=macaroons[0].serialize(),
        )
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertTranslates(
            LAUNCHPAD_SERVICES,
            path,
            code_imports[0].git_repository,
            permission="write",
            macaroon_raw=macaroons[0].serialize(),
            private=True,
            writable=True,
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw=macaroons[1].serialize(),
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw="nonsense",
        )
        self.assertUnauthorized(
            code_imports[0].registrant,
            path,
            permission="write",
            macaroon_raw=macaroons[0].serialize(),
        )

    def test_translatePath_private_code_import_access_token(self):
        # An access token can only allow pulling from a code import
        # repository, not pushing to it.
        code_import = self.factory.makeCodeImport(
            target_rcs_type=TargetRevisionControlSystems.GIT
        )
        repository = code_import.git_repository
        owner = repository.owner
        removeSecurityProxy(repository).transitionToInformationType(
            InformationType.PRIVATESECURITY, owner
        )
        with person_logged_in(owner):
            path = "/%s" % repository.unique_name
            _, token = self.factory.makeAccessToken(
                owner=owner,
                target=repository,
                scopes=[
                    AccessTokenScope.REPOSITORY_PULL,
                    AccessTokenScope.REPOSITORY_PUSH,
                ],
            )
        self.assertTranslates(
            owner,
            path,
            repository,
            permission="read",
            access_token_id=removeSecurityProxy(token).id,
            private=True,
        )
        self.assertPermissionDenied(
            owner,
            path,
            permission="write",
            access_token_id=removeSecurityProxy(token).id,
        )

    def test_translatePath_private_snap_build(self):
        # A builder with a suitable macaroon can read from a repository
        # associated with a running private snap build.
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        owner = self.factory.makePerson()
        with person_logged_in(owner):
            refs = [
                self.factory.makeGitRefs(
                    owner=owner, information_type=InformationType.USERDATA
                )[0]
                for _ in range(2)
            ]
            builds = [
                self.factory.makeSnapBuild(
                    requester=owner, owner=owner, git_ref=ref, private=True
                )
                for ref in refs
            ]
            issuer = getUtility(IMacaroonIssuer, "snap-build")
            macaroons = [
                removeSecurityProxy(issuer).issueMacaroon(build)
                for build in builds
            ]
            repository = refs[0].repository
            registrant = repository.registrant
            path = "/%s" % repository.unique_name
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw=macaroons[0].serialize(),
        )
        with person_logged_in(owner):
            builds[0].updateStatus(BuildStatus.BUILDING)
        self.assertTranslates(
            LAUNCHPAD_SERVICES,
            path,
            repository,
            permission="read",
            macaroon_raw=macaroons[0].serialize(),
            private=True,
            writable=False,
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="read",
            macaroon_raw=macaroons[1].serialize(),
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="read",
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="read",
            macaroon_raw="nonsense",
        )
        self.assertUnauthorized(
            registrant,
            path,
            permission="read",
            macaroon_raw=macaroons[0].serialize(),
        )

    def test_translatePath_private_ci_build(self):
        # A builder with a suitable macaroon can read from a repository
        # associated with a running private CI build.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        with person_logged_in(self.factory.makePerson()) as owner:
            distro = self.factory.makeDistribution(
                owner=owner, information_type=InformationType.PROPRIETARY
            )
            dsp = self.factory.makeDistributionSourcePackage(
                distribution=distro
            )
            repositories = [
                self.factory.makeGitRepository(
                    registrant=owner,
                    owner=owner,
                    information_type=InformationType.PROPRIETARY,
                    target=dsp,
                )
                for _ in range(2)
            ]
            builds = [
                self.factory.makeCIBuild(git_repository=repository)
                for repository in repositories
            ]
            issuer = getUtility(IMacaroonIssuer, "ci-build")
            macaroons = [
                removeSecurityProxy(issuer).issueMacaroon(build)
                for build in builds
            ]
            repository = repositories[0]
            path = "/%s" % repository.unique_name
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="write",
            macaroon_raw=macaroons[0].serialize(),
        )
        removeSecurityProxy(builds[0]).updateStatus(BuildStatus.BUILDING)
        self.assertTranslates(
            LAUNCHPAD_SERVICES,
            path,
            repository,
            permission="read",
            macaroon_raw=macaroons[0].serialize(),
            private=True,
            writable=False,
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="read",
            macaroon_raw=macaroons[1].serialize(),
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="read",
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertUnauthorized(
            LAUNCHPAD_SERVICES,
            path,
            permission="read",
            macaroon_raw="nonsense",
        )
        self.assertUnauthorized(
            removeSecurityProxy(repository).registrant,
            path,
            permission="read",
            macaroon_raw=macaroons[0].serialize(),
        )

    def test_translatePath_user_macaroon(self):
        # A user with a suitable macaroon can write to the corresponding
        # repository, but not others, even if they own them.
        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=requester) for _ in range(2)
        ]
        repositories.append(
            self.factory.makeGitRepository(
                owner=requester,
                information_type=InformationType.PRIVATESECURITY,
            )
        )
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        with person_logged_in(requester):
            macaroons = [
                removeSecurityProxy(issuer).issueMacaroon(
                    repository, user=requester
                )
                for repository in repositories
            ]
            paths = [
                "/%s" % repository.unique_name for repository in repositories
            ]
        for i, repository in enumerate(repositories):
            for j, macaroon in enumerate(macaroons):
                login(ANONYMOUS)
                if i == j:
                    self.assertTranslates(
                        requester,
                        paths[i],
                        repository,
                        permission="write",
                        macaroon_raw=macaroon.serialize(),
                        writable=True,
                        private=(i == 2),
                    )
                else:
                    self.assertUnauthorized(
                        requester,
                        paths[i],
                        permission="write",
                        macaroon_raw=macaroon.serialize(),
                    )
            login(ANONYMOUS)
            self.assertUnauthorized(
                requester,
                paths[i],
                permission="write",
                macaroon_raw=Macaroon(
                    location=config.vhost.mainsite.hostname,
                    identifier="another",
                    key="another-secret",
                ).serialize(),
            )
            login(ANONYMOUS)
            self.assertUnauthorized(
                requester,
                paths[i],
                permission="write",
                macaroon_raw="nonsense",
            )

    def test_translatePath_user_mismatch(self):
        # translatePath refuses macaroons in the case where the user doesn't
        # match what the issuer claims was verified.  (We use a fake issuer
        # for this, since this is a stopgap check to defend against issuer
        # bugs; and we test read permissions since write permissions for
        # internal macaroons are restricted to particular named issuers.)
        issuer = FakeMacaroonIssuer()
        self.useFixture(
            ZopeUtilityFixture(issuer, IMacaroonIssuer, name="test")
        )
        repository = self.factory.makeGitRepository()
        path = "/%s" % repository.unique_name
        macaroon = issuer.issueMacaroon(repository)
        requesters = [self.factory.makePerson() for _ in range(2)]
        for verified_user, authorized, unauthorized in (
            (NO_USER, [LAUNCHPAD_SERVICES], requesters + [None]),
            (
                requesters[0],
                [requesters[0]],
                [LAUNCHPAD_SERVICES, requesters[1], None],
            ),
            (None, [], [LAUNCHPAD_SERVICES] + requesters + [None]),
        ):
            issuer._verified_user = verified_user
            for requester in authorized:
                login(ANONYMOUS)
                self.assertTranslates(
                    requester,
                    path,
                    repository,
                    permission="read",
                    writable=False,
                    macaroon_raw=macaroon.serialize(),
                )
            for requester in unauthorized:
                login(ANONYMOUS)
                self.assertUnauthorized(
                    requester,
                    path,
                    permission="read",
                    macaroon_raw=macaroon.serialize(),
                )

    def test_translatePath_user_access_token_pull(self):
        # A user with a suitable access token can pull from the
        # corresponding repository, but not others, even if they own them.
        requester = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=requester) for _ in range(2)
        ]
        repositories.append(
            self.factory.makeGitRepository(
                owner=requester,
                information_type=InformationType.PRIVATESECURITY,
            )
        )
        tokens = []
        with person_logged_in(requester):
            for repository in repositories:
                _, token = self.factory.makeAccessToken(
                    owner=requester,
                    target=repository,
                    scopes=[AccessTokenScope.REPOSITORY_PULL],
                )
                tokens.append(token)
            paths = [
                "/%s" % repository.unique_name for repository in repositories
            ]
        for i, repository in enumerate(repositories):
            for j, token in enumerate(tokens):
                login(ANONYMOUS)
                if i == j:
                    self.assertTranslates(
                        requester,
                        paths[i],
                        repository,
                        permission="read",
                        access_token_id=removeSecurityProxy(token).id,
                        private=(i == 2),
                    )
                else:
                    self.assertUnauthorized(
                        requester,
                        paths[i],
                        permission="read",
                        access_token_id=removeSecurityProxy(token).id,
                    )

    def test_translatePath_user_access_token_pull_wrong_scope(self):
        # A user with an access token that does not have the repository:pull
        # scope cannot pull from the corresponding repository.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        _, token = self.factory.makeAccessToken(
            owner=requester,
            target=repository,
            scopes=[AccessTokenScope.REPOSITORY_BUILD_STATUS],
        )
        self.assertPermissionDenied(
            requester,
            "/%s" % repository.unique_name,
            permission="read",
            access_token_id=removeSecurityProxy(token).id,
        )

    def test_translatePath_user_access_token_push(self):
        # A user with a suitable access token can push to the corresponding
        # repository, but not others, even if they own them.
        requester = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=requester) for _ in range(2)
        ]
        repositories.append(
            self.factory.makeGitRepository(
                owner=requester,
                information_type=InformationType.PRIVATESECURITY,
            )
        )
        tokens = []
        with person_logged_in(requester):
            for repository in repositories:
                _, token = self.factory.makeAccessToken(
                    owner=requester,
                    target=repository,
                    scopes=[AccessTokenScope.REPOSITORY_PUSH],
                )
                tokens.append(token)
            paths = [
                "/%s" % repository.unique_name for repository in repositories
            ]
        for i, repository in enumerate(repositories):
            for j, token in enumerate(tokens):
                login(ANONYMOUS)
                if i == j:
                    self.assertTranslates(
                        requester,
                        paths[i],
                        repository,
                        permission="write",
                        access_token_id=removeSecurityProxy(token).id,
                        readable=False,
                        writable=True,
                        private=(i == 2),
                    )
                else:
                    self.assertUnauthorized(
                        requester,
                        paths[i],
                        permission="write",
                        access_token_id=removeSecurityProxy(token).id,
                    )

    def test_translatePath_user_access_token_push_wrong_scope(self):
        # A user with an access token that does not have the repository:push
        # scope cannot push to the corresponding repository.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        _, token = self.factory.makeAccessToken(
            owner=requester,
            target=repository,
            scopes=[AccessTokenScope.REPOSITORY_PULL],
        )
        self.assertPermissionDenied(
            requester,
            "/%s" % repository.unique_name,
            permission="write",
            access_token_id=removeSecurityProxy(token).id,
        )

    def test_translatePath_user_access_token_nonexistent(self):
        # Attempting to pass a nonexistent access token ID returns
        # Unauthorized.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        self.assertUnauthorized(
            requester,
            "/%s" % repository.unique_name,
            permission="read",
            access_token_id=0,
        )
        self.assertUnauthorized(
            requester,
            "/%s" % repository.unique_name,
            permission="write",
            access_token_id=0,
        )

    def test_translatePath_user_access_token_non_integer(self):
        # Attempting to pass a non-integer access token ID returns
        # Unauthorized.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        self.assertUnauthorized(
            requester,
            "/%s" % repository.unique_name,
            permission="read",
            access_token_id="string",
        )
        self.assertUnauthorized(
            requester,
            "/%s" % repository.unique_name,
            permission="write",
            access_token_id="string",
        )

    def test_getMergeProposalURL_user(self):
        # A merge proposal URL is returned by LP for a non-default branch
        # pushed by a user that has their ordinary privileges on the
        # corresponding repository.
        requester_owner = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester_owner)
        self.factory.makeGitRefs(
            repository=repository, paths=["refs/heads/master"]
        )
        removeSecurityProxy(repository).default_branch = "refs/heads/master"
        pushed_branch = "branch1"
        self.assertHasMergeProposalURL(
            repository, pushed_branch, {"uid": requester_owner.id}
        )

        # Turnip verifies if the pushed branch is the default branch
        # in a repository and calls LP only for non default branches.
        # Consequently LP will process any incoming branch from Turnip
        # as being non default and produce a merge proposal URL for it.
        self.factory.makeGitRefs(
            repository=repository, paths=["refs/heads/%s" % pushed_branch]
        )
        removeSecurityProxy(repository).default_branch = (
            "refs/heads/%s" % pushed_branch
        )
        self.assertHasMergeProposalURL(
            repository, pushed_branch, {"uid": requester_owner.id}
        )

        requester_non_owner = self.factory.makePerson()
        self.assertHasMergeProposalURL(
            repository, pushed_branch, {"uid": requester_non_owner.id}
        )

    def test_getMergeProposalURL_user_macaroon(self):
        # The merge proposal URL is returned by LP for a non-default branch
        # pushed by a user with a suitable macaroon that
        # has their ordinary privileges on the corresponding repository.

        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        self.factory.makeGitRefs(
            repository=repository, paths=["refs/heads/master"]
        )
        removeSecurityProxy(repository).default_branch = "refs/heads/master"

        pushed_branch = "branch1"
        with person_logged_in(requester):
            macaroon = removeSecurityProxy(issuer).issueMacaroon(
                repository, user=requester
            )
        auth_params = _make_auth_params(
            requester, macaroon_raw=macaroon.serialize()
        )
        self.assertHasMergeProposalURL(repository, pushed_branch, auth_params)

    def test_getMergeProposalURL_user_mismatch(self):
        # getMergeProposalURL refuses macaroons in the case where the
        # user doesn't match what the issuer claims was verified.  (We use a
        # fake issuer for this, since this is a stopgap check to defend
        # against issuer bugs)

        issuer = FakeMacaroonIssuer()
        # Claim to be the code-import-job issuer.  This is a bit weird, but
        # it gets us past the difficulty that only certain named issuers are
        # allowed to confer write permissions.
        issuer.identifier = "code-import-job"
        self.useFixture(
            ZopeUtilityFixture(issuer, IMacaroonIssuer, name="code-import-job")
        )
        requesters = [self.factory.makePerson() for _ in range(2)]
        owner = self.factory.makeTeam(members=requesters)
        repository = self.factory.makeGitRepository(owner=owner)
        self.factory.makeGitRefs(
            repository=repository, paths=["refs/heads/master"]
        )
        removeSecurityProxy(repository).default_branch = "refs/heads/master"
        pushed_branch = "branch1"
        macaroon = issuer.issueMacaroon(repository)

        for verified_user, authorized, unauthorized in (
            (
                requesters[0],
                [requesters[0]],
                [LAUNCHPAD_SERVICES, requesters[1], None],
            ),
            ([None, NO_USER], [], [LAUNCHPAD_SERVICES] + requesters + [None]),
        ):
            issuer._verified_user = verified_user
            for requester in authorized:
                login(ANONYMOUS)
                auth_params = _make_auth_params(
                    requester, macaroon_raw=macaroon.serialize()
                )
                self.assertHasMergeProposalURL(
                    repository, pushed_branch, auth_params
                )
            for requester in unauthorized:
                login(ANONYMOUS)
                auth_params = _make_auth_params(
                    requester, macaroon_raw=macaroon.serialize()
                )

                self.assertFault(
                    faults.Unauthorized,
                    None,
                    "getMergeProposalURL",
                    repository.getInternalPath(),
                    pushed_branch,
                    auth_params,
                )

    def test_getMergeProposalURL_user_access_token(self):
        # The merge proposal URL is returned by LP for a non-default branch
        # pushed by a user with a suitable access token that has their
        # ordinary privileges on the corresponding repository.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        self.factory.makeGitRefs(
            repository=repository, paths=["refs/heads/main"]
        )
        removeSecurityProxy(repository).default_branch = "refs/heads/main"
        _, token = self.factory.makeAccessToken(
            owner=requester,
            target=repository,
            scopes=[AccessTokenScope.REPOSITORY_PUSH],
        )
        auth_params = _make_auth_params(
            requester, access_token_id=removeSecurityProxy(token).id
        )
        self.assertHasMergeProposalURL(repository, "branch", auth_params)

    def test_getMergeProposalURL_user_access_token_wrong_repository(self):
        # getMergeProposalURL refuses access tokens for a different
        # repository.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        self.factory.makeGitRefs(
            repository=repository, paths=["refs/heads/main"]
        )
        removeSecurityProxy(repository).default_branch = "refs/heads/main"
        _, token = self.factory.makeAccessToken(
            owner=requester, scopes=[AccessTokenScope.REPOSITORY_PUSH]
        )
        auth_params = _make_auth_params(
            requester, access_token_id=removeSecurityProxy(token).id
        )
        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            repository.getInternalPath(),
            "branch",
            auth_params,
        )

    def test_getMergeProposalURL_code_import(self):
        # A merge proposal URL from LP to Turnip is not returned for
        # code import job as there is no User at the other end.

        issuer = FakeMacaroonIssuer()
        # Claim to be the code-import-job issuer.  This is a bit weird, but
        # it gets us past the difficulty that only certain named issuers are
        # allowed to confer write permissions.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]
        repository = code_imports[0].git_repository
        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroons[0].serialize()
        )
        pushed_branch = "branch1"
        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            repository.getInternalPath(),
            pushed_branch,
            auth_params,
        )

        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroons[0].serialize()
        )

        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            removeSecurityProxy(repository).getInternalPath(),
            pushed_branch,
            auth_params,
        )

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroons[1].serialize()
        )

        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            removeSecurityProxy(repository).getInternalPath(),
            pushed_branch,
            auth_params,
        )

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES,
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            removeSecurityProxy(repository).getInternalPath(),
            pushed_branch,
            auth_params,
        )

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroon_raw="nonsense"
        )

        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            removeSecurityProxy(repository).getInternalPath(),
            pushed_branch,
            auth_params,
        )

    def test_getMergeProposalURL_private_code_import(self):
        # We do not send the Merge Proposal URL back
        # to a Code Import Job.

        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        private_repository = code_imports[0].git_repository
        removeSecurityProxy(private_repository).transitionToInformationType(
            InformationType.PRIVATESECURITY, private_repository.owner
        )
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]
        repository = code_imports[0].git_repository
        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroons[0].serialize()
        )
        pushed_branch = "branch1"

        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            removeSecurityProxy(repository).getInternalPath(),
            pushed_branch,
            auth_params,
        )

        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroons[1].serialize()
        )

        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            removeSecurityProxy(repository).getInternalPath(),
            pushed_branch,
            auth_params,
        )

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES,
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )

        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            removeSecurityProxy(repository).getInternalPath(),
            pushed_branch,
            auth_params,
        )

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroon_raw="nonsense"
        )

        self.assertFault(
            faults.Unauthorized,
            None,
            "getMergeProposalURL",
            removeSecurityProxy(repository).getInternalPath(),
            pushed_branch,
            auth_params,
        )

    def test_notify(self):
        # The notify call creates a GitRefScanJob.
        repository = self.factory.makeGitRepository()
        self.assertIsNone(
            self.assertDoesNotFault(
                None,
                "notify",
                repository.getInternalPath(),
                {"loose_object_count": 5, "pack_count": 2},
                {"uid": repository.owner.id},
            )
        )
        job_source = getUtility(IGitRefScanJobSource)
        [job] = list(job_source.iterReady())
        self.assertEqual(repository, job.repository)

    def test_notify_missing_repository(self):
        # A notify call on a non-existent repository returns a fault and
        # does not create a job.
        requester_owner = self.factory.makePerson()

        self.assertFault(
            faults.NotFound,
            None,
            "notify",
            "10000",
            {"loose_object_count": 5, "pack_count": 2},
            {"uid": requester_owner.id},
        )
        job_source = getUtility(IGitRefScanJobSource)
        self.assertEqual([], list(job_source.iterReady()))

    def test_notify_private(self):
        # notify works on private repos.
        with admin_logged_in():
            repository = self.factory.makeGitRepository(
                information_type=InformationType.PRIVATESECURITY
            )
            path = repository.getInternalPath()
            self.assertIsNone(
                self.assertDoesNotFault(
                    None,
                    "notify",
                    path,
                    {"loose_object_count": 5, "pack_count": 2},
                    {"uid": repository.owner.id},
                )
            )
        job_source = getUtility(IGitRefScanJobSource)
        [job] = list(job_source.iterReady())
        self.assertEqual(repository, job.repository)

    def assertSetsRepackData(self, repo, auth_params):
        start_time = datetime.now(timezone.utc)
        self.assertIsNone(
            self.assertDoesNotFault(
                None,
                "notify",
                repo.getInternalPath(),
                {"loose_object_count": 5, "pack_count": 2},
                auth_params,
            )
        )
        end_time = datetime.now(timezone.utc)
        naked_repo = removeSecurityProxy(repo)
        self.assertEqual(5, naked_repo.loose_object_count)
        self.assertEqual(2, naked_repo.pack_count)
        self.assertBetween(start_time, naked_repo.date_last_scanned, end_time)

    def test_notify_set_repack_data(self):
        # The notify call sets the repack
        # indicators (loose_object_count, pack_count, date_last_scanned)
        # when received from Turnip for a user
        # that has their ordinary privileges on the corresponding repository
        requester_owner = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester_owner)

        self.assertSetsRepackData(repository, {"uid": requester_owner.id})

    def test_notify_set_repack_data_user_macaroon(self):
        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        with person_logged_in(requester):
            macaroon = removeSecurityProxy(issuer).issueMacaroon(
                repository, user=requester
            )
        auth_params = _make_auth_params(
            requester, macaroon_raw=macaroon.serialize()
        )
        self.assertSetsRepackData(repository, auth_params)

    def test_notify_set_repack_data_user_mismatch(self):
        # notify refuses macaroons in the case where the
        # user doesn't match what the issuer claims was verified.  (We use a
        # fake issuer for this, since this is a stopgap check to defend
        # against issuer bugs)

        issuer = FakeMacaroonIssuer()
        # Claim to be the code-import-job issuer.  This is a bit weird, but
        # it gets us past the difficulty that only certain named issuers are
        # allowed to confer write permissions.
        issuer.identifier = "code-import-job"
        self.useFixture(
            ZopeUtilityFixture(issuer, IMacaroonIssuer, name="code-import-job")
        )
        requesters = [self.factory.makePerson() for _ in range(2)]
        owner = self.factory.makeTeam(members=requesters)
        repository = self.factory.makeGitRepository(owner=owner)
        macaroon = issuer.issueMacaroon(repository)

        for verified_user, authorized, unauthorized in (
            (
                requesters[0],
                [requesters[0]],
                [LAUNCHPAD_SERVICES, requesters[1], None],
            ),
            ([None, NO_USER], [], [LAUNCHPAD_SERVICES] + requesters + [None]),
        ):
            issuer._verified_user = verified_user
            for requester in authorized:
                login(ANONYMOUS)
                auth_params = _make_auth_params(
                    requester, macaroon_raw=macaroon.serialize()
                )
                self.assertSetsRepackData(repository, auth_params)

            for requester in unauthorized:
                login(ANONYMOUS)
                auth_params = _make_auth_params(
                    requester, macaroon_raw=macaroon.serialize()
                )
                self.assertFault(
                    faults.Unauthorized,
                    None,
                    "notify",
                    repository.getInternalPath(),
                    {"loose_object_count": 5, "pack_count": 2},
                    auth_params,
                )

    def test_notify_set_repack_data_user_access_token(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        _, token = self.factory.makeAccessToken(
            owner=requester,
            target=repository,
            scopes=[AccessTokenScope.REPOSITORY_PUSH],
        )
        auth_params = _make_auth_params(
            requester, access_token_id=removeSecurityProxy(token).id
        )
        self.assertSetsRepackData(repository, auth_params)

    def test_notify_set_repack_data_user_access_token_nonexistent(self):
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        auth_params = _make_auth_params(requester, access_token_id=0)
        self.assertFault(
            faults.Unauthorized,
            None,
            "notify",
            repository.getInternalPath(),
            {"loose_object_count": 5, "pack_count": 2},
            auth_params,
        )

    def test_notify_set_repack_data_code_import(self):
        # We set the repack data on a repository from a code import worker
        # with a suitable macaroon.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]

        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroon_raw=macaroons[0].serialize()
        )
        self.assertSetsRepackData(code_imports[0].git_repository, auth_params)

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroon_raw=macaroons[1].serialize()
        )
        self.assertFault(
            faults.Unauthorized,
            None,
            "notify",
            code_imports[0].git_repository.getInternalPath(),
            {"loose_object_count": 5, "pack_count": 2},
            auth_params,
        )

    def test_notify_set_repack_data_private_code_import(self):
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        private_repository = code_imports[0].git_repository
        path = private_repository.getInternalPath()
        removeSecurityProxy(private_repository).transitionToInformationType(
            InformationType.PRIVATESECURITY, private_repository.owner
        )
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]

        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroon_raw=macaroons[0].serialize()
        )
        self.assertSetsRepackData(code_imports[0].git_repository, auth_params)

        auth_params = _make_auth_params(
            LAUNCHPAD_SERVICES, macaroon_raw=macaroons[1].serialize()
        )
        self.assertFault(
            faults.Unauthorized,
            None,
            "notify",
            path,
            {"loose_object_count": 5, "pack_count": 2},
            auth_params,
        )

    def test_authenticateWithPassword(self):
        self.assertFault(
            faults.Unauthorized, None, "authenticateWithPassword", "foo", "bar"
        )

    def test_authenticateWithPassword_code_import(self):
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        code_import = self.factory.makeCodeImport(
            target_rcs_type=TargetRevisionControlSystems.GIT
        )
        with celebrity_logged_in("vcs_imports"):
            job = self.factory.makeCodeImportJob(code_import=code_import)
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroon = removeSecurityProxy(issuer).issueMacaroon(job)
        for username in ("", "+launchpad-services"):
            self.assertEqual(
                {
                    "macaroon": macaroon.serialize(),
                    "user": "+launchpad-services",
                },
                self.assertDoesNotFault(
                    None,
                    "authenticateWithPassword",
                    username,
                    macaroon.serialize(),
                ),
            )
            other_macaroon = Macaroon(
                identifier="another", key="another-secret"
            )
            self.assertFault(
                faults.Unauthorized,
                None,
                "authenticateWithPassword",
                username,
                other_macaroon.serialize(),
            )
            self.assertFault(
                faults.Unauthorized,
                None,
                "authenticateWithPassword",
                username,
                "nonsense",
            )

    def test_authenticateWithPassword_private_snap_build(self):
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        with person_logged_in(self.factory.makePerson()) as owner:
            [ref] = self.factory.makeGitRefs(
                owner=owner, information_type=InformationType.USERDATA
            )
            build = self.factory.makeSnapBuild(
                requester=owner, owner=owner, git_ref=ref, private=True
            )
            issuer = getUtility(IMacaroonIssuer, "snap-build")
            macaroon = removeSecurityProxy(issuer).issueMacaroon(build)
        for username in ("", "+launchpad-services"):
            self.assertEqual(
                {
                    "macaroon": macaroon.serialize(),
                    "user": "+launchpad-services",
                },
                self.assertDoesNotFault(
                    None,
                    "authenticateWithPassword",
                    username,
                    macaroon.serialize(),
                ),
            )
            other_macaroon = Macaroon(
                identifier="another", key="another-secret"
            )
            self.assertFault(
                faults.Unauthorized,
                None,
                "authenticateWithPassword",
                username,
                other_macaroon.serialize(),
            )
            self.assertFault(
                faults.Unauthorized,
                None,
                "authenticateWithPassword",
                username,
                "nonsense",
            )

    def test_authenticateWithPassword_private_ci_build(self):
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        with person_logged_in(self.factory.makePerson()) as owner:
            distro = self.factory.makeDistribution(
                owner=owner, information_type=InformationType.PROPRIETARY
            )
            dsp = self.factory.makeDistributionSourcePackage(
                distribution=distro
            )
            repository = self.factory.makeGitRepository(
                registrant=owner,
                owner=owner,
                information_type=InformationType.PROPRIETARY,
                target=dsp,
            )
            build = self.factory.makeCIBuild(git_repository=repository)
            issuer = getUtility(IMacaroonIssuer, "ci-build")
            macaroon = removeSecurityProxy(issuer).issueMacaroon(build)
        for username in ("", "+launchpad-services"):
            self.assertEqual(
                {
                    "macaroon": macaroon.serialize(),
                    "user": "+launchpad-services",
                },
                self.assertDoesNotFault(
                    None,
                    "authenticateWithPassword",
                    username,
                    macaroon.serialize(),
                ),
            )
            other_macaroon = Macaroon(
                identifier="another", key="another-secret"
            )
            self.assertFault(
                faults.Unauthorized,
                None,
                "authenticateWithPassword",
                username,
                other_macaroon.serialize(),
            )
            self.assertFault(
                faults.Unauthorized,
                None,
                "authenticateWithPassword",
                username,
                "nonsense",
            )

    def test_authenticateWithPassword_user_macaroon(self):
        # A user with a suitable macaroon can authenticate using it, in
        # which case we return both the macaroon and the uid for use by
        # later calls.
        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        macaroon = removeSecurityProxy(issuer).issueMacaroon(
            self.factory.makeGitRepository(owner=requester), user=requester
        )
        self.assertEqual(
            {"macaroon": macaroon.serialize(), "uid": requester.id},
            self.assertDoesNotFault(
                None,
                "authenticateWithPassword",
                requester.name,
                macaroon.serialize(),
            ),
        )
        for username in ("", "+launchpad-services", "nonexistent"):
            self.assertFault(
                faults.Unauthorized,
                None,
                "authenticateWithPassword",
                username,
                macaroon.serialize(),
            )
        other_macaroon = Macaroon(identifier="another", key="another-secret")
        self.assertFault(
            faults.Unauthorized,
            None,
            "authenticateWithPassword",
            requester.name,
            other_macaroon.serialize(),
        )
        self.assertFault(
            faults.Unauthorized,
            None,
            "authenticateWithPassword",
            requester.name,
            "nonsense",
        )

    def test_authenticateWithPassword_user_mismatch(self):
        # authenticateWithPassword refuses macaroons in the case where the
        # user doesn't match what the issuer claims was verified.  (We use a
        # fake issuer for this, since this is a stopgap check to defend
        # against issuer bugs; and we test read permissions since write
        # permissions for internal macaroons are restricted to particular
        # named issuers.)
        issuer = FakeMacaroonIssuer()
        self.useFixture(
            ZopeUtilityFixture(issuer, IMacaroonIssuer, name="test")
        )
        macaroon = issuer.issueMacaroon(self.factory.makeGitRepository())
        requesters = [self.factory.makePerson() for _ in range(2)]
        for verified_user, authorized, unauthorized in (
            (NO_USER, [LAUNCHPAD_SERVICES], requesters),
            (
                requesters[0],
                [requesters[0]],
                [LAUNCHPAD_SERVICES, requesters[1]],
            ),
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
                    self.assertDoesNotFault(
                        None,
                        "authenticateWithPassword",
                        name,
                        macaroon.serialize(),
                    ),
                )
            for requester in unauthorized:
                login(ANONYMOUS)
                name = (
                    requester
                    if requester == LAUNCHPAD_SERVICES
                    else requester.name
                )
                self.assertFault(
                    faults.Unauthorized,
                    None,
                    "authenticateWithPassword",
                    name,
                    macaroon.serialize(),
                )

    def test_authenticateWithPassword_user_access_token(self):
        # A user with a suitable access token can authenticate using it, in
        # which case we return both the access token and the uid for use by
        # later calls.
        requester = self.factory.makePerson()
        secret, token = self.factory.makeAccessToken(owner=requester)
        self.assertIsNone(removeSecurityProxy(token).date_last_used)
        self.assertEqual(
            {
                "access-token": removeSecurityProxy(token).id,
                "uid": requester.id,
            },
            self.assertDoesNotFault(
                None, "authenticateWithPassword", requester.name, secret
            ),
        )
        self.assertIsNotNone(removeSecurityProxy(token).date_last_used)
        for username in ("", "+launchpad-services", "nonexistent"):
            self.assertFault(
                faults.Unauthorized,
                None,
                "authenticateWithPassword",
                username,
                secret,
            )

    def test_authenticateWithPassword_user_access_token_expired(self):
        # An expired access token is rejected.
        requester = self.factory.makePerson()
        secret, _ = self.factory.makeAccessToken(
            owner=requester,
            date_expires=datetime.now(timezone.utc) - timedelta(days=1),
        )
        self.assertFault(
            faults.Unauthorized,
            None,
            "authenticateWithPassword",
            requester.name,
            secret,
        )

    def test_authenticateWithPassword_user_access_token_wrong_user(self):
        # An access token for a different user is rejected.
        requester = self.factory.makePerson()
        secret, _ = self.factory.makeAccessToken()
        self.assertFault(
            faults.Unauthorized,
            None,
            "authenticateWithPassword",
            requester.name,
            secret,
        )

    def test_authenticateWithPassword_user_access_token_inactive_account(self):
        # An access token for an inactive user is rejected.
        requester = self.factory.makePerson(
            account_status=AccountStatus.SUSPENDED
        )
        secret, _ = self.factory.makeAccessToken(owner=requester)
        self.assertFault(
            faults.Unauthorized,
            None,
            "authenticateWithPassword",
            requester.name,
            secret,
        )

    def test_checkRefPermissions_code_import(self):
        # A code import worker with a suitable macaroon has repository owner
        # privileges on a repository associated with a running code import
        # job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]
        repository = code_imports[0].git_repository
        ref_path = b"refs/heads/master"
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw=macaroons[0].serialize(),
        )
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: ["create", "push", "force_push"]},
            macaroon_raw=macaroons[0].serialize(),
        )
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw=macaroons[1].serialize(),
        )
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw="nonsense",
        )
        self.assertHasRefPermissions(
            code_imports[0].registrant,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw=macaroons[0].serialize(),
        )

    def test_checkRefPermissions_private_code_import(self):
        # A code import worker with a suitable macaroon has repository owner
        # privileges on a repository associated with a running private code
        # import job.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        machine = self.factory.makeCodeImportMachine(set_online=True)
        code_imports = [
            self.factory.makeCodeImport(
                target_rcs_type=TargetRevisionControlSystems.GIT
            )
            for _ in range(2)
        ]
        private_repository = code_imports[0].git_repository
        removeSecurityProxy(private_repository).transitionToInformationType(
            InformationType.PRIVATESECURITY, private_repository.owner
        )
        with celebrity_logged_in("vcs_imports"):
            jobs = [
                self.factory.makeCodeImportJob(code_import=code_import)
                for code_import in code_imports
            ]
        issuer = getUtility(IMacaroonIssuer, "code-import-job")
        macaroons = [
            removeSecurityProxy(issuer).issueMacaroon(job) for job in jobs
        ]
        repository = code_imports[0].git_repository
        ref_path = b"refs/heads/master"
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw=macaroons[0].serialize(),
        )
        with celebrity_logged_in("vcs_imports"):
            getUtility(ICodeImportJobWorkflow).startJob(jobs[0], machine)
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: ["create", "push", "force_push"]},
            macaroon_raw=macaroons[0].serialize(),
        )
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw=macaroons[1].serialize(),
        )
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw=Macaroon(
                location=config.vhost.mainsite.hostname,
                identifier="another",
                key="another-secret",
            ).serialize(),
        )
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw="nonsense",
        )
        self.assertHasRefPermissions(
            code_imports[0].registrant,
            repository,
            [ref_path],
            {ref_path: []},
            macaroon_raw=macaroons[0].serialize(),
        )

    def test_checkRefPermissions_private_snap_build(self):
        # A builder with a suitable macaroon cannot write to a repository,
        # even if it is associated with a running private snap build.
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        with person_logged_in(self.factory.makePerson()) as owner:
            [ref] = self.factory.makeGitRefs(
                owner=owner, information_type=InformationType.USERDATA
            )
            build = self.factory.makeSnapBuild(
                requester=owner, owner=owner, git_ref=ref, private=True
            )
            issuer = getUtility(IMacaroonIssuer, "snap-build")
            macaroon = removeSecurityProxy(issuer).issueMacaroon(build)
            build.updateStatus(BuildStatus.BUILDING)
            repository = ref.repository
            path = ref.path.encode("UTF-8")
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [path],
            {path: []},
            macaroon_raw=macaroon.serialize(),
        )

    def test_checkRefPermissions_private_ci_build(self):
        # A builder with a suitable macaroon cannot write to a repository,
        # even if it is associated with a running private CI build.
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        with person_logged_in(self.factory.makePerson()) as owner:
            [ref] = self.factory.makeGitRefs(
                owner=owner, information_type=InformationType.USERDATA
            )
            build = self.factory.makeCIBuild(git_repository=ref.repository)
            issuer = getUtility(IMacaroonIssuer, "ci-build")
            macaroon = removeSecurityProxy(issuer).issueMacaroon(build)
            build.updateStatus(BuildStatus.BUILDING)
            repository = ref.repository
            path = ref.path.encode("UTF-8")
        self.assertHasRefPermissions(
            LAUNCHPAD_SERVICES,
            repository,
            [path],
            {path: []},
            macaroon_raw=macaroon.serialize(),
        )

    def test_checkRefPermissions_user_macaroon(self):
        # A user with a suitable macaroon has their ordinary privileges on
        # the corresponding repository, but not others, even if they own
        # them.
        self.pushConfig("codehosting", git_macaroon_secret_key="some-secret")
        requester = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=requester) for _ in range(2)
        ]
        repositories.append(
            self.factory.makeGitRepository(
                owner=requester,
                information_type=InformationType.PRIVATESECURITY,
            )
        )
        ref_path = b"refs/heads/master"
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        with person_logged_in(requester):
            macaroons = [
                removeSecurityProxy(issuer).issueMacaroon(
                    repository, user=requester
                )
                for repository in repositories
            ]
        for i, repository in enumerate(repositories):
            for j, macaroon in enumerate(macaroons):
                login(ANONYMOUS)
                if i == j:
                    expected_permissions = ["create", "push", "force_push"]
                else:
                    expected_permissions = []
                self.assertHasRefPermissions(
                    requester,
                    repository,
                    [ref_path],
                    {ref_path: expected_permissions},
                    macaroon_raw=macaroon.serialize(),
                )
            login(ANONYMOUS)
            self.assertHasRefPermissions(
                None,
                repository,
                [ref_path],
                {ref_path: []},
                macaroon_raw=macaroon.serialize(),
            )
            login(ANONYMOUS)
            self.assertHasRefPermissions(
                self.factory.makePerson(),
                repository,
                [ref_path],
                {ref_path: []},
                macaroon_raw=macaroon.serialize(),
            )
            login(ANONYMOUS)
            self.assertHasRefPermissions(
                requester,
                repository,
                [ref_path],
                {ref_path: []},
                macaroon_raw=Macaroon(
                    location=config.vhost.mainsite.hostname,
                    identifier="another",
                    key="another-secret",
                ).serialize(),
            )
            login(ANONYMOUS)
            self.assertHasRefPermissions(
                requester,
                repository,
                [ref_path],
                {ref_path: []},
                macaroon_raw="nonsense",
            )

    def test_checkRefPermissions_user_mismatch(self):
        # checkRefPermissions refuses macaroons in the case where the user
        # doesn't match what the issuer claims was verified.  (We use a
        # fake issuer for this, since this is a stopgap check to defend
        # against issuer bugs.)
        issuer = FakeMacaroonIssuer()
        # Claim to be the code-import-job issuer.  This is a bit weird, but
        # it gets us past the difficulty that only certain named issuers are
        # allowed to confer write permissions.
        issuer.identifier = "code-import-job"
        self.useFixture(
            ZopeUtilityFixture(issuer, IMacaroonIssuer, name="code-import-job")
        )
        requesters = [self.factory.makePerson() for _ in range(2)]
        owner = self.factory.makeTeam(members=requesters)
        repository = self.factory.makeGitRepository(owner=owner)
        ref_path = b"refs/heads/master"
        macaroon = issuer.issueMacaroon(repository)
        for verified_user, authorized, unauthorized in (
            (NO_USER, [LAUNCHPAD_SERVICES], requesters + [None]),
            (
                requesters[0],
                [requesters[0]],
                [LAUNCHPAD_SERVICES, requesters[1], None],
            ),
            (None, [], [LAUNCHPAD_SERVICES] + requesters + [None]),
        ):
            issuer._verified_user = verified_user
            for requester in authorized:
                login(ANONYMOUS)
                self.assertHasRefPermissions(
                    requester,
                    repository,
                    [ref_path],
                    {ref_path: ["create", "push", "force_push"]},
                    macaroon_raw=macaroon.serialize(),
                )
            for requester in unauthorized:
                login(ANONYMOUS)
                self.assertHasRefPermissions(
                    requester,
                    repository,
                    [ref_path],
                    {ref_path: []},
                    macaroon_raw=macaroon.serialize(),
                )

    def test_checkRefPermissions_user_access_token(self):
        # A user with a suitable access token has their ordinary privileges
        # on the corresponding repository, but not others, even if they own
        # them.
        requester = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=requester) for _ in range(2)
        ]
        repositories.append(
            self.factory.makeGitRepository(
                owner=requester,
                information_type=InformationType.PRIVATESECURITY,
            )
        )
        ref_path = b"refs/heads/main"
        tokens = []
        with person_logged_in(requester):
            for repository in repositories:
                _, token = self.factory.makeAccessToken(
                    owner=requester,
                    target=repository,
                    scopes=[AccessTokenScope.REPOSITORY_PUSH],
                )
                tokens.append(token)
        for i, repository in enumerate(repositories):
            for j, token in enumerate(tokens):
                login(ANONYMOUS)
                if i == j:
                    expected_permissions = ["create", "push", "force_push"]
                else:
                    expected_permissions = []
                self.assertHasRefPermissions(
                    requester,
                    repository,
                    [ref_path],
                    {ref_path: expected_permissions},
                    access_token_id=removeSecurityProxy(token).id,
                )

    def test_checkRefPermissions_user_access_token_wrong_scope(self):
        # A user with an access token that does not have the repository:push
        # scope cannot push to any branch in the corresponding repository.
        requester = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester)
        _, token = self.factory.makeAccessToken(
            owner=requester,
            target=repository,
            scopes=[AccessTokenScope.REPOSITORY_PULL],
        )
        ref_path = b"refs/heads/main"
        self.assertHasRefPermissions(
            requester,
            repository,
            [ref_path],
            {ref_path: []},
            access_token_id=removeSecurityProxy(token).id,
        )

    def assertUpdatesRepackStats(self, repo):
        start_time = datetime.now(timezone.utc)
        self.assertIsNone(
            self.assertDoesNotFault(
                None,
                "updateRepackStats",
                repo.getInternalPath(),
                {"loose_object_count": 5, "pack_count": 2},
            )
        )
        end_time = datetime.now(timezone.utc)
        naked_repo = removeSecurityProxy(repo)
        self.assertEqual(5, naked_repo.loose_object_count)
        self.assertEqual(2, naked_repo.pack_count)
        self.assertBetween(start_time, naked_repo.date_last_scanned, end_time)

    def test_updateRepackStats(self):
        requester_owner = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=requester_owner)
        self.assertUpdatesRepackStats(repository)

    def test_updateRepackStatsNonExistentRepo(self):
        self.assertFault(
            faults.GitRepositoryNotFound("nonexistent"),
            None,
            "updateRepackStats",
            "nonexistent",
            {"loose_object_count": 5, "pack_count": 2},
        )


class TestGitAPISecurity(TestGitAPIMixin, TestCaseWithFactory):
    """Slow tests for `IGitAPI`.

    These use AppServerLayer to check that `run_with_login` is behaving
    itself properly.
    """

    layer = AppServerLayer
