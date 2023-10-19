# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import textwrap
from operator import attrgetter

from lazr.uri import URI
from storm.store import Store
from zope.component import getUtility
from zope.security.management import endInteraction
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.person import IPersonSet, TeamMembershipStatus
from lp.registry.interfaces.ssh import ISSHKeySet, SSHKeyType
from lp.registry.interfaces.teammembership import ITeamMembershipSet
from lp.services.identity.interfaces.account import AccountStatus, IAccountSet
from lp.services.openid.model.openididentifier import OpenIdIdentifier
from lp.services.webapp import snapshot
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.webapp.publisher import canonical_url
from lp.testing import (
    TestCaseWithFactory,
    admin_logged_in,
    api_url,
    launchpadlib_for,
    login,
    person_logged_in,
    record_two_runs,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import LaunchpadWebServiceCaller, webservice_for_person


class TestPersonEmailSecurity(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.target = self.factory.makePerson(name="target")
        self.email_one = self.factory.makeEmail(
            "test1@example.com", self.target
        )
        self.email_two = self.factory.makeEmail(
            "test2@example.com", self.target
        )

    def test_logged_in_can_access(self):
        # A logged in launchpadlib connection can see confirmed email
        # addresses.
        accessor = self.factory.makePerson()
        lp = launchpadlib_for("test", accessor.name)
        person = lp.people["target"]
        emails = [entry.email for entry in person.confirmed_email_addresses]
        self.assertContentEqual(
            ["test1@example.com", "test2@example.com"], emails
        )

    def test_anonymous_cannot_access(self):
        # An anonymous launchpadlib connection cannot see email addresses.

        # Need to endInteraction() because launchpadlib_for() will
        # setup a new one.
        endInteraction()
        lp = launchpadlib_for("test", person=None, version="devel")
        person = lp.people["target"]
        emails = list(person.confirmed_email_addresses)
        self.assertEqual([], emails)


class TestPersonAccountStatus(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_account_status_history_restricted(self):
        person = self.factory.makePerson()
        registrar = self.factory.makePerson(
            member_of=[getUtility(IPersonSet).getByName("registry")]
        )
        removeSecurityProxy(person.account).status_history = "Test"
        person_url = api_url(person)

        # A normal user cannot read account_status_history. Not even
        # their own.
        body = (
            webservice_for_person(
                person, permission=OAuthPermission.WRITE_PRIVATE
            )
            .get(person_url, api_version="devel")
            .jsonBody()
        )
        self.assertEqual("Active", body["account_status"])
        self.assertEqual(
            "tag:launchpad.net:2008:redacted", body["account_status_history"]
        )

        # A member of ~registry can see it all.
        body = (
            webservice_for_person(
                registrar, permission=OAuthPermission.WRITE_PRIVATE
            )
            .get(person_url, api_version="devel")
            .jsonBody()
        )
        self.assertEqual("Active", body["account_status"])
        self.assertEqual("Test", body["account_status_history"])

    def test_setAccountStatus(self):
        person = self.factory.makePerson()
        registrar = self.factory.makePerson(
            name="registrar",
            member_of=[getUtility(IPersonSet).getByName("registry")],
        )
        person_url = api_url(person)

        # A normal user cannot set even their own account status.
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.named_post(
            person_url,
            "setAccountStatus",
            status="Suspended",
            comment="Go away",
            api_version="devel",
        )
        self.assertEqual(401, response.status)

        # A member of ~registry can do what they wish.
        webservice = webservice_for_person(
            registrar, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.named_post(
            person_url,
            "setAccountStatus",
            status="Suspended",
            comment="Go away",
            api_version="devel",
        )
        self.assertEqual(200, response.status)
        with admin_logged_in():
            self.assertEqual(AccountStatus.SUSPENDED, person.account_status)
            self.assertEndsWith(
                person.account_status_history,
                "registrar: Active -> Suspended: Go away\n",
            )


class TestPersonExportedID(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_anonymous_user_cannot_see_id(self):
        # An anonymous user cannot read the `id` field.
        person = self.factory.makePerson()
        person_url = api_url(person)

        body = (
            webservice_for_person(
                None, permission=OAuthPermission.WRITE_PRIVATE
            )
            .get(person_url, api_version="devel")
            .jsonBody()
        )
        self.assertEqual("tag:launchpad.net:2008:redacted", body["id"])

    def test_normal_user_cannot_see_id(self):
        # A normal user cannot read the `id` field, not even their own.
        person = self.factory.makePerson()
        person_url = api_url(person)

        body = (
            webservice_for_person(
                person, permission=OAuthPermission.WRITE_PRIVATE
            )
            .get(person_url, api_version="devel")
            .jsonBody()
        )
        self.assertEqual("tag:launchpad.net:2008:redacted", body["id"])

    def test_registry_can_see_id(self):
        # A member of ~registry can read the `id` field.
        person = self.factory.makePerson()
        person_id = person.id
        person_url = api_url(person)

        body = (
            webservice_for_person(
                self.factory.makeRegistryExpert(),
                permission=OAuthPermission.READ_PRIVATE,
            )
            .get(person_url, api_version="devel")
            .jsonBody()
        )
        self.assertEqual(person_id, body["id"])

    def test_commercial_admin_can_see_id(self):
        # A member of ~commercial-admins can read the `id` field.
        person = self.factory.makePerson()
        person_id = person.id
        person_url = api_url(person)

        body = (
            webservice_for_person(
                self.factory.makeCommercialAdmin(),
                permission=OAuthPermission.READ_PRIVATE,
            )
            .get(person_url, api_version="devel")
            .jsonBody()
        )
        self.assertEqual(person_id, body["id"])


class TestPersonRepresentation(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        login("guilherme.salgado@canonical.com ")
        self.person = self.factory.makePerson(
            name="test-person", displayname="Test Person"
        )
        self.webservice = LaunchpadWebServiceCaller(
            "launchpad-library", "salgado-change-anything"
        )

    def test_GET_xhtml_representation(self):
        # Remove the security proxy because IPerson.name is protected.
        person_name = removeSecurityProxy(self.person).name
        response = self.webservice.get(
            "/~%s" % person_name, "application/xhtml+xml"
        )

        self.assertEqual(response.status, 200)

        rendered_comment = response.body
        self.assertEqual(
            rendered_comment,
            b'<a href="/~test-person" class="sprite person">Test Person</a>',
        )


class PersonWebServiceTests(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_deactivated_members_query_count(self):
        with admin_logged_in():
            team = self.factory.makeTeam()
            owner = team.teamowner
            name = team.name
        ws = webservice_for_person(owner)

        def create_member():
            with admin_logged_in():
                person = self.factory.makePerson()
                team.addMember(person, owner)
                getUtility(ITeamMembershipSet).getByPersonAndTeam(
                    person, team
                ).setStatus(
                    TeamMembershipStatus.DEACTIVATED, owner, "Go away."
                )

        def get_members():
            ws.get("/~%s/deactivated_members" % name).jsonBody()

        # Ensure that we're already in a stable cache state.
        get_members()
        recorder1, recorder2 = record_two_runs(get_members, create_member, 2)
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))

    def test_members_ordering(self):
        # Entries in the various members collections are sorted by
        # (Person.display_name, Person.name).
        with admin_logged_in():
            team = self.factory.makeTeam()
            owner = team.teamowner
            name = team.name
        members = [owner]
        with admin_logged_in():
            for member_suffix in (
                "a1",
                "b1",
                "a2",
                "b2",
                "a3",
                "b4",
                "a4",
                "b3",
                "a5",
                "b5",
            ):
                person = self.factory.makePerson(
                    name="member-" + member_suffix
                )
                team.addMember(person, owner)
                members.append(person)
        expected_member_names = [
            member.name
            for member in sorted(
                members, key=attrgetter("display_name", "name")
            )
        ]
        ws = webservice_for_person(owner)
        observed_member_names = []
        batch = ws.get("/~%s/members" % name).jsonBody()
        while True:
            for entry in batch["entries"]:
                observed_member_names.append(entry["name"])
            next_link = batch.get("next_collection_link")
            if next_link is None:
                break
            batch = ws.get(URI(next_link)).jsonBody()
        self.assertEqual(expected_member_names, observed_member_names)

    def test_many_ppas(self):
        # POSTing to a person with many PPAs doesn't OOPS.
        with admin_logged_in():
            team = self.factory.makeTeam()
            owner = team.teamowner
        new_member = self.factory.makePerson()
        ws = webservice_for_person(
            owner, permission=OAuthPermission.WRITE_PUBLIC
        )
        real_hard_limit_for_snapshot = snapshot.HARD_LIMIT_FOR_SNAPSHOT
        snapshot.HARD_LIMIT_FOR_SNAPSHOT = 3
        try:
            with person_logged_in(owner):
                for _ in range(snapshot.HARD_LIMIT_FOR_SNAPSHOT + 1):
                    self.factory.makeArchive(owner=team)
                team_url = api_url(team)
                new_member_url = api_url(new_member)
            response = ws.named_post(
                team_url, "addMember", person=new_member_url, status="Approved"
            )
            self.assertEqual(200, response.status)
            self.assertEqual([True, "Approved"], response.jsonBody())
        finally:
            snapshot.HARD_LIMIT_FOR_SNAPSHOT = real_hard_limit_for_snapshot


class PersonSetWebServiceTests(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.webservice = webservice_for_person(None)

    def assertReturnsPeople(self, expected_names, path):
        self.assertEqual(
            expected_names,
            [
                person["name"]
                for person in self.webservice.get(path).jsonBody()["entries"]
            ],
        )

    def test_default_content(self):
        # /people lists the 50 people with the most karma, excluding
        # those with no karma at all.
        self.assertEqual(
            4, len(self.webservice.get("/people").jsonBody()["entries"])
        )

    def test_find(self):
        # It's possible to find people by name.
        with admin_logged_in():
            person_name = self.factory.makePerson().name
        self.assertReturnsPeople(
            [person_name], "/people?ws.op=find&text=%s" % person_name
        )

    def test_findTeam(self):
        # The search can be restricted to teams.
        with admin_logged_in():
            person_name = self.factory.makePerson().name
            team_name = self.factory.makeTeam(
                name="%s-team" % person_name
            ).name
        self.assertReturnsPeople(
            [team_name], "/people?ws.op=findTeam&text=%s" % person_name
        )

    def test_findTeam_query_count(self):
        with admin_logged_in():
            ws = webservice_for_person(self.factory.makePerson())

        def create_match():
            with admin_logged_in():
                self.factory.makeTeam(displayname="foobar")

        def find_teams():
            ws.named_get("/people", "findTeam", text="foobar").jsonBody()

        # Ensure that we're already in a stable cache state.
        find_teams()
        recorder1, recorder2 = record_two_runs(find_teams, create_match, 2)
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))

    def test_findPerson(self):
        # The search can be restricted to people.
        with admin_logged_in():
            person_name = self.factory.makePerson().name
            self.factory.makeTeam(name="%s-team" % person_name)
        self.assertReturnsPeople(
            [person_name], "/people?ws.op=findPerson&text=%s" % person_name
        )

    def test_find_by_date(self):
        # Creation date filtering is supported.
        self.assertReturnsPeople(
            ["bac"],
            "/people?ws.op=findPerson&text="
            "&created_after=2008-06-27&created_before=2008-07-01",
        )

    def test_getByEmail(self):
        # You can get a person by their email address.
        with admin_logged_in():
            person = self.factory.makePerson()
            person_name = person.name
            person_email = person.preferredemail.email
        self.assertEqual(
            person_name,
            self.webservice.get(
                "/people?ws.op=getByEmail&email=%s" % person_email
            ).jsonBody()["name"],
        )

    def test_getByEmail_checks_format(self):
        # A malformed email address is rejected.
        e = self.assertRaises(
            ValueError,
            self.webservice.get(
                "/people?ws.op=getByEmail&email=foo@"
            ).jsonBody,
        )
        # XXX wgrant bug=1088358: This escaping shouldn't be here; it's
        # not HTML.
        self.assertEqual("email: Invalid email &#x27;foo@&#x27;.", e.args[0])

    def test_getByOpenIDIdentifier(self):
        # You can get a person by their OpenID identifier URL.
        with admin_logged_in():
            person = self.factory.makePerson()
            person_name = person.name
            person_openid = person.account.openid_identifiers.one().identifier
        self.assertEqual(
            person_name,
            self.webservice.get(
                "/people?ws.op=getByOpenIDIdentifier&"
                "identifier=http://login1.test/%%2Bid/%s" % person_openid,
                api_version="devel",
            ).jsonBody()["name"],
        )

    def getOrCreateSoftwareCenterCustomer(self, user):
        webservice = webservice_for_person(
            user, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.named_post(
            "/people",
            "getOrCreateSoftwareCenterCustomer",
            openid_identifier="somebody",
            email_address="somebody@example.com",
            display_name="Somebody",
            api_version="devel",
        )
        return response

    def test_getOrCreateSoftwareCenterCustomer(self):
        # Software Center Agent (SCA) can get or create people by OpenID
        # identifier.
        with admin_logged_in():
            sca = getUtility(IPersonSet).getByName("software-center-agent")
        response = self.getOrCreateSoftwareCenterCustomer(sca)
        self.assertEqual("Somebody", response.jsonBody()["display_name"])
        with admin_logged_in():
            person = getUtility(IPersonSet).getByEmail("somebody@example.com")
            self.assertEqual("Somebody", person.displayname)
            self.assertEqual(
                ["somebody"],
                [oid.identifier for oid in person.account.openid_identifiers],
            )
            self.assertEqual(
                "somebody@example.com", person.preferredemail.email
            )

    def test_getOrCreateSoftwareCenterCustomer_is_restricted(self):
        # The method may only be invoked by the ~software-center-agent
        # celebrity user, as it is security-sensitive.
        with admin_logged_in():
            random = self.factory.makePerson()
        response = self.getOrCreateSoftwareCenterCustomer(random)
        self.assertEqual(401, response.status)

    def test_getOrCreateSoftwareCenterCustomer_rejects_email_conflicts(self):
        # An unknown OpenID identifier with a known email address causes
        # the request to fail with 409 Conflict, as we'd otherwise end
        # up linking the OpenID identifier to an existing account.
        with admin_logged_in():
            self.factory.makePerson(email="somebody@example.com")
            sca = getUtility(IPersonSet).getByName("software-center-agent")
        response = self.getOrCreateSoftwareCenterCustomer(sca)
        self.assertEqual(409, response.status)

    def test_getOrCreateSoftwareCenterCustomer_rejects_suspended(self):
        # Suspended accounts are not returned.
        with admin_logged_in():
            existing = self.factory.makePerson(
                email="somebody@example.com",
                account_status=AccountStatus.SUSPENDED,
            )
            oid = OpenIdIdentifier()
            oid.account = existing.account
            oid.identifier = "somebody"
            Store.of(existing).add(oid)
            sca = getUtility(IPersonSet).getByName("software-center-agent")
        response = self.getOrCreateSoftwareCenterCustomer(sca)
        self.assertEqual(400, response.status)

    def test_getOrCreateSoftwareCenterCustomer_rejects_deceased(self):
        # Deceased accounts are not returned.
        with admin_logged_in():
            existing = self.factory.makePerson(
                email="somebody@example.com",
                account_status=AccountStatus.DECEASED,
            )
            oid = OpenIdIdentifier()
            oid.account = existing.account
            oid.identifier = "somebody"
            Store.of(existing).add(oid)
            sca = getUtility(IPersonSet).getByName("software-center-agent")
        response = self.getOrCreateSoftwareCenterCustomer(sca)
        self.assertEqual(400, response.status)

    def test_getUsernameForSSO(self):
        # canonical-identity-provider (SSO) can get the username for an
        # OpenID identifier suffix.
        with admin_logged_in():
            sso = getUtility(IPersonSet).getByName("ubuntu-sso")
            existing = self.factory.makePerson(name="username")
            taken_openid = existing.account.openid_identifiers.any().identifier
        webservice = webservice_for_person(
            sso, permission=OAuthPermission.READ_PUBLIC
        )
        response = webservice.named_get(
            "/people",
            "getUsernameForSSO",
            openid_identifier=taken_openid,
            api_version="devel",
        )
        self.assertEqual(200, response.status)
        self.assertEqual("username", response.jsonBody())

    def test_getUsernameForSSO_nonexistent(self):
        with admin_logged_in():
            sso = getUtility(IPersonSet).getByName("ubuntu-sso")
        webservice = webservice_for_person(
            sso, permission=OAuthPermission.READ_PUBLIC
        )
        response = webservice.named_get(
            "/people",
            "getUsernameForSSO",
            openid_identifier="doesnotexist",
            api_version="devel",
        )
        self.assertEqual(200, response.status)
        self.assertEqual(None, response.jsonBody())

    def setUsernameFromSSO(self, user, openid_identifier, name, dry_run=False):
        webservice = webservice_for_person(
            user, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.named_post(
            "/people",
            "setUsernameFromSSO",
            openid_identifier=openid_identifier,
            name=name,
            dry_run=dry_run,
            api_version="devel",
        )
        return response

    def test_setUsernameFromSSO(self):
        # canonical-identity-provider (SSO) can create a placeholder
        # Person to give a username to a non-LP user.
        with admin_logged_in():
            sso = getUtility(IPersonSet).getByName("ubuntu-sso")
        response = self.setUsernameFromSSO(sso, "foo", "bar")
        self.assertEqual(200, response.status)
        with admin_logged_in():
            by_name = getUtility(IPersonSet).getByName("bar")
            by_openid = getUtility(IPersonSet).getByOpenIDIdentifier(
                "http://testopenid.test/+id/foo"
            )
            self.assertEqual(by_name, by_openid)
            self.assertEqual(AccountStatus.PLACEHOLDER, by_name.account_status)

    def test_setUsernameFromSSO_dry_run(self):
        # setUsernameFromSSO provides a dry run mode that performs all
        # the checks but doesn't actually make changes. Useful for input
        # validation in SSO.
        with admin_logged_in():
            sso = getUtility(IPersonSet).getByName("ubuntu-sso")
        response = self.setUsernameFromSSO(sso, "foo", "bar", dry_run=True)
        self.assertEqual(200, response.status)
        with admin_logged_in():
            self.assertIs(None, getUtility(IPersonSet).getByName("bar"))
            self.assertRaises(
                LookupError,
                getUtility(IAccountSet).getByOpenIDIdentifier,
                "foo",
            )

    def test_setUsernameFromSSO_is_restricted(self):
        # The method may only be invoked by the ~ubuntu-sso celebrity
        # user, as it is security-sensitive.
        with admin_logged_in():
            random = self.factory.makePerson()
        response = self.setUsernameFromSSO(random, "foo", "bar")
        self.assertEqual(401, response.status)

    def test_setUsernameFromSSO_rejects_bad_input(self, dry_run=False):
        # The method returns meaningful errors on bad input, so SSO can
        # give advice to users.
        # Check canonical-identity-provider before changing these!
        with admin_logged_in():
            sso = getUtility(IPersonSet).getByName("ubuntu-sso")
            self.factory.makePerson(name="taken-name")
            existing = self.factory.makePerson()
            taken_openid = existing.account.openid_identifiers.any().identifier

        response = self.setUsernameFromSSO(
            sso, "foo", "taken-name", dry_run=dry_run
        )
        self.assertEqual(400, response.status)
        self.assertEqual(
            b"name: taken-name is already in use by another person or team.",
            response.body,
        )

        response = self.setUsernameFromSSO(
            sso, "foo", "private-name", dry_run=dry_run
        )
        self.assertEqual(400, response.status)
        self.assertEqual(
            b"name: The name &#x27;private-name&#x27; has been blocked by the "
            b"Launchpad administrators. Contact Launchpad Support if you want "
            b"to use this name.",
            response.body,
        )

        response = self.setUsernameFromSSO(
            sso, taken_openid, "bar", dry_run=dry_run
        )
        self.assertEqual(400, response.status)
        self.assertEqual(
            b"An account for that OpenID identifier already exists.",
            response.body,
        )

    def test_setUsernameFromSSO_rejects_bad_input_in_dry_run(self):
        self.test_setUsernameFromSSO_rejects_bad_input(dry_run=True)

    def test_getSSHKeysForSSO(self):
        with admin_logged_in():
            target = self.factory.makePerson()
            key = self.factory.makeSSHKey(target)
            sso = getUtility(IPersonSet).getByName("ubuntu-sso")
            taken_openid = target.account.openid_identifiers.any().identifier
        webservice = webservice_for_person(
            sso, permission=OAuthPermission.READ_PUBLIC
        )
        response = webservice.named_get(
            "/people",
            "getSSHKeysForSSO",
            openid_identifier=taken_openid,
            api_version="devel",
        )
        expected = "ssh-rsa %s %s" % (key.keytext, key.comment)
        self.assertEqual(200, response.status)
        self.assertEqual([expected], response.jsonBody())

    def test_getSSHKeysForSSO_nonexistent(self):
        with admin_logged_in():
            sso = getUtility(IPersonSet).getByName("ubuntu-sso")
        webservice = webservice_for_person(
            sso, permission=OAuthPermission.READ_PUBLIC
        )
        response = webservice.named_get(
            "/people",
            "getSSHKeysForSSO",
            openid_identifier="doesnotexist",
            api_version="devel",
        )
        self.assertEqual(200, response.status)
        self.assertEqual(None, response.jsonBody())

    def addSSHKeyForPerson(self, openid_identifier, key_text, dry_run=False):
        with admin_logged_in():
            sso = getUtility(IPersonSet).getByName("ubuntu-sso")
        webservice = webservice_for_person(
            sso, permission=OAuthPermission.WRITE_PRIVATE
        )
        return webservice.named_post(
            "/people",
            "addSSHKeyFromSSO",
            openid_identifier=openid_identifier,
            key_text=key_text,
            dry_run=dry_run,
            api_version="devel",
        )

    def test_addSSHKeyFromSSO_nonexistant(self):
        response = self.addSSHKeyForPerson("doesnotexist", "sdf")
        self.assertEqual(400, response.status)
        self.assertEqual(
            b"No account found for openid identifier 'doesnotexist'",
            response.body,
        )

    def test_addSSHKeyFromSSO_rejects_bad_key_data(self):
        with admin_logged_in():
            person = self.factory.makePerson()
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.addSSHKeyForPerson(openid_id, "bad_data")
        self.assertEqual(400, response.status)
        self.assertEqual(b"Invalid SSH key data: 'bad_data'", response.body)

    def test_addSSHKeyFromSSO_rejects_bad_key_type(self):
        with admin_logged_in():
            person = self.factory.makePerson()
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.addSSHKeyForPerson(openid_id, "foo keydata comment")
        self.assertEqual(400, response.status)
        self.assertEqual(b"Invalid SSH key type: 'foo'", response.body)

    def test_addSSHKeyFromSSO_rejects_bad_key_type_dry_run(self):
        with admin_logged_in():
            person = self.factory.makePerson()
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.addSSHKeyForPerson(
            openid_id, "foo keydata comment", True
        )
        self.assertEqual(400, response.status)
        self.assertEqual(b"Invalid SSH key type: 'foo'", response.body)

    def test_addSSHKeyFromSSO_works(self):
        with admin_logged_in():
            person = removeSecurityProxy(self.factory.makePerson())
            openid_id = person.account.openid_identifiers.any().identifier
        full_key = self.factory.makeSSHKeyText()
        _, keytext, comment = full_key.split(" ", 2)
        response = self.addSSHKeyForPerson(openid_id, full_key)

        self.assertEqual(200, response.status)
        [key] = person.sshkeys
        self.assertEqual(SSHKeyType.RSA, key.keytype)
        self.assertEqual(keytext, key.keytext)
        self.assertEqual(comment, key.comment)

    def test_addSSHKeyFromSSO_dry_run(self):
        with admin_logged_in():
            person = removeSecurityProxy(self.factory.makePerson())
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.addSSHKeyForPerson(
            openid_id, self.factory.makeSSHKeyText(), dry_run=True
        )

        self.assertEqual(200, response.status)
        self.assertEqual(0, person.sshkeys.count())

    def test_addSSHKeyFromSSO_is_restricted(self):
        with admin_logged_in():
            target = self.factory.makePerson()
            openid_id = target.account.openid_identifiers.any().identifier
        webservice = webservice_for_person(
            target, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.named_post(
            "/people",
            "addSSHKeyFromSSO",
            openid_identifier=openid_id,
            key_text="ssh-rsa foo bar",
            dry_run=False,
            api_version="devel",
        )
        self.assertEqual(401, response.status)

    def deleteSSHKeyFromSSO(self, openid_identifier, key_text, dry_run=False):
        with admin_logged_in():
            sso = getUtility(IPersonSet).getByName("ubuntu-sso")
        webservice = webservice_for_person(
            sso, permission=OAuthPermission.WRITE_PRIVATE
        )
        return webservice.named_post(
            "/people",
            "deleteSSHKeyFromSSO",
            openid_identifier=openid_identifier,
            key_text=key_text,
            dry_run=dry_run,
            api_version="devel",
        )

    def test_deleteSSHKeyFromSSO_nonexistant(self, dry_run=False):
        response = self.deleteSSHKeyFromSSO("doesnotexist", "sdf", dry_run)
        self.assertEqual(400, response.status)
        self.assertEqual(
            b"No account found for openid identifier 'doesnotexist'",
            response.body,
        )

    def test_deleteSSHKeyFromSSO_nonexistant_dry_run(self):
        self.test_deleteSSHKeyFromSSO_nonexistant(True)

    def test_deleteSSHKeyFromSSO_rejects_bad_key_data(self, dry_run=False):
        with admin_logged_in():
            person = self.factory.makePerson()
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.deleteSSHKeyFromSSO(openid_id, "bad_data", dry_run)
        self.assertEqual(400, response.status)
        self.assertEqual(b"Invalid SSH key data: 'bad_data'", response.body)

    def test_deleteSSHKeyFromSSO_rejects_bad_key_data_dry_run(self):
        self.test_deleteSSHKeyFromSSO_rejects_bad_key_data(True)

    def test_deleteSSHKeyFromSSO_rejects_bad_key_type(self, dry_run=False):
        with admin_logged_in():
            person = self.factory.makePerson()
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.deleteSSHKeyFromSSO(
            openid_id, "foo keydata comment", dry_run
        )
        self.assertEqual(400, response.status)
        self.assertEqual(b"Invalid SSH key type: 'foo'", response.body)

    def test_deleteSSHKeyFromSSO_rejects_bad_key_type_dry_run(self):
        self.test_deleteSSHKeyFromSSO_rejects_bad_key_type(True)

    def test_deleteSSHKeyFromSSO_works(self):
        with admin_logged_in():
            person = removeSecurityProxy(self.factory.makePerson())
            key = self.factory.makeSSHKey(person)
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.deleteSSHKeyFromSSO(openid_id, key.getFullKeyText())

        self.assertEqual(200, response.status)
        self.assertEqual(0, person.sshkeys.count())

    def test_deleteSSHKeyFromSSO_works_dry_run(self):
        with admin_logged_in():
            person = removeSecurityProxy(self.factory.makePerson())
            key = self.factory.makeSSHKey(person)
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.deleteSSHKeyFromSSO(
            openid_id, key.getFullKeyText(), dry_run=True
        )

        self.assertEqual(200, response.status)
        self.assertEqual(1, person.sshkeys.count())

    def test_deleteSSHKeyFromSSO_allows_newlines(self):
        # Adding these should normally be forbidden, but we want users to be
        # able to delete existing rows.
        with admin_logged_in():
            person = removeSecurityProxy(self.factory.makePerson())
            kind, data, comment = self.factory.makeSSHKeyText().split(" ", 2)
            key_text = "%s %s %s\n" % (kind, textwrap.fill(data), comment)
            key = getUtility(ISSHKeySet).new(person, key_text, check_key=False)
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.deleteSSHKeyFromSSO(openid_id, key.getFullKeyText())

        self.assertEqual(200, response.status)
        self.assertEqual(0, person.sshkeys.count())

    def test_deleteSSHKeyFromSSO_allows_newlines_dry_run(self):
        with admin_logged_in():
            person = removeSecurityProxy(self.factory.makePerson())
            kind, data, comment = self.factory.makeSSHKeyText().split(" ", 2)
            key_text = "%s %s %s\n" % (kind, textwrap.fill(data), comment)
            key = getUtility(ISSHKeySet).new(person, key_text, check_key=False)
            openid_id = person.account.openid_identifiers.any().identifier
        response = self.deleteSSHKeyFromSSO(
            openid_id, key.getFullKeyText(), dry_run=True
        )

        self.assertEqual(200, response.status)
        self.assertEqual(1, person.sshkeys.count())

    def test_deleteSSHKeyFromSSO_is_restricted(self, dry_run=False):
        with admin_logged_in():
            target = self.factory.makePerson()
            openid_id = target.account.openid_identifiers.any().identifier
        webservice = webservice_for_person(
            target, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.named_post(
            "/people",
            "deleteSSHKeyFromSSO",
            openid_identifier=openid_id,
            key_text="ssh-rsa foo bar",
            dry_run=dry_run,
            api_version="devel",
        )
        self.assertEqual(401, response.status)

    def test_deleteSSHKeyFromSSO_is_restricted_dry_run(self):
        self.test_deleteSSHKeyFromSSO_is_restricted(True)

    def test_user_data_retrieval(self):
        with admin_logged_in():
            target = self.factory.makePerson(email="test@example.com")
            webservice = webservice_for_person(
                getUtility(ILaunchpadCelebrities).admin.teamowner,
                permission=OAuthPermission.WRITE_PRIVATE,
            )
        response = webservice.named_get(
            "/people",
            "getUserData",
            email="test@example.com",
            api_version="devel",
        ).jsonBody()
        with admin_logged_in():
            self.assertDictEqual(
                {
                    "status": "account only; no other data",
                    "person": canonical_url(target),
                },
                response,
            )

    # See TestGDPRUserRetrieval for more details tests of the
    # various data output options available for this endpoint.
    def test_user_data_retrieval_protected(self):
        with admin_logged_in():
            self.factory.makePerson(email="test@example.com")
            webservice = webservice_for_person(self.factory.makePerson())
        response = webservice.named_get(
            "/people",
            "getUserData",
            email="test@example.com",
            api_version="devel",
        )
        self.assertEqual(401, response.status)
