# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image registry credential storage."""

import json

import transaction
from testtools import ExpectedException
from testtools.matchers import AfterPreprocessing, Equals, MatchesDict
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.oci.interfaces.ociregistrycredentials import (
    IOCIRegistryCredentials,
    IOCIRegistryCredentialsSet,
    OCIRegistryCredentialsAlreadyExist,
    OCIRegistryCredentialsNotOwner,
)
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.services.crypto.interfaces import IEncryptedContainer
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.layers import LaunchpadZopelessLayer


class TestOCIRegistryCredentials(OCIConfigHelperMixin, TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.setConfig()

    def test_implements_interface(self):
        owner = self.factory.makePerson()
        oci_credentials = getUtility(IOCIRegistryCredentialsSet).new(
            registrant=owner,
            owner=owner,
            url="http://example.org",
            credentials={"username": "foo", "password": "bar"},
        )
        self.assertProvides(oci_credentials, IOCIRegistryCredentials)

    def test_credentials_are_encrypted(self):
        credentials = {
            "username": "foo",
            "password": "bar",
            "region": "br-101",
        }
        oci_credentials = removeSecurityProxy(
            self.factory.makeOCIRegistryCredentials(credentials=credentials)
        )
        container = getUtility(IEncryptedContainer, "oci-registry-secrets")
        self.assertThat(
            oci_credentials._credentials,
            MatchesDict(
                {
                    "username": Equals("foo"),
                    "region": Equals("br-101"),
                    "credentials_encrypted": AfterPreprocessing(
                        lambda value: json.loads(
                            container.decrypt(value).decode("UTF-8")
                        ),
                        Equals({"password": "bar"}),
                    ),
                }
            ),
        )

    def test_credentials_set(self):
        owner = self.factory.makePerson()
        oci_credentials = self.factory.makeOCIRegistryCredentials(
            registrant=owner,
            owner=owner,
            url="http://example.org",
            credentials={
                "username": "foo",
                "password": "bar",
                "region": "br-101",
            },
        )

        with person_logged_in(owner):
            self.assertThat(
                oci_credentials.getCredentials(),
                MatchesDict(
                    {
                        "username": Equals("foo"),
                        "password": Equals("bar"),
                        "region": Equals("br-101"),
                    }
                ),
            )

    def test_credentials_set_empty(self):
        owner = self.factory.makePerson()
        oci_credentials = self.factory.makeOCIRegistryCredentials(
            registrant=owner,
            owner=owner,
            url="http://example.org",
            credentials={},
        )
        with person_logged_in(owner):
            self.assertThat(oci_credentials.getCredentials(), MatchesDict({}))

    def test_credentials_set_no_password(self):
        owner = self.factory.makePerson()
        oci_credentials = removeSecurityProxy(
            self.factory.makeOCIRegistryCredentials(
                registrant=owner,
                owner=owner,
                url="http://example.org",
                credentials={"username": "test"},
            )
        )
        container = getUtility(IEncryptedContainer, "oci-registry-secrets")
        with person_logged_in(owner):
            self.assertThat(
                oci_credentials._credentials,
                MatchesDict(
                    {
                        "username": Equals("test"),
                        "credentials_encrypted": AfterPreprocessing(
                            lambda value: json.loads(
                                container.decrypt(value).decode("UTF-8")
                            ),
                            Equals({}),
                        ),
                    }
                ),
            )

    def test_credentials_set_no_username(self):
        owner = self.factory.makePerson()
        oci_credentials = removeSecurityProxy(
            self.factory.makeOCIRegistryCredentials(
                registrant=owner,
                owner=owner,
                url="http://example.org",
                credentials={"password": "bar"},
            )
        )
        container = getUtility(IEncryptedContainer, "oci-registry-secrets")
        with person_logged_in(owner):
            self.assertThat(
                oci_credentials._credentials,
                MatchesDict(
                    {
                        "credentials_encrypted": AfterPreprocessing(
                            lambda value: json.loads(
                                container.decrypt(value).decode("UTF-8")
                            ),
                            Equals({"password": "bar"}),
                        )
                    }
                ),
            )

    def test_credentials_set_encrypts_other_data(self):
        owner = self.factory.makePerson()
        oci_credentials = removeSecurityProxy(
            self.factory.makeOCIRegistryCredentials(
                registrant=owner,
                owner=owner,
                url="http://example.org",
                credentials={
                    "username": "foo",
                    "password": "bar",
                    "other": "baz",
                },
            )
        )
        container = getUtility(IEncryptedContainer, "oci-registry-secrets")
        with person_logged_in(owner):
            self.assertThat(
                oci_credentials._credentials,
                MatchesDict(
                    {
                        "username": Equals("foo"),
                        "credentials_encrypted": AfterPreprocessing(
                            lambda value: json.loads(
                                container.decrypt(value).decode("UTF-8")
                            ),
                            Equals({"password": "bar", "other": "baz"}),
                        ),
                    }
                ),
            )


class TestOCIRegistryCredentialsSet(OCIConfigHelperMixin, TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.setConfig()

    def test_implements_interface(self):
        credentials_set = getUtility(IOCIRegistryCredentialsSet)
        self.assertProvides(credentials_set, IOCIRegistryCredentialsSet)

    def test_new(self):
        owner = self.factory.makePerson()
        url = self.factory.getUniqueURL()
        credentials = {"username": "foo", "password": "bar"}
        oci_credentials = getUtility(IOCIRegistryCredentialsSet).new(
            registrant=owner, owner=owner, url=url, credentials=credentials
        )
        self.assertEqual(oci_credentials.owner, owner)
        self.assertEqual(oci_credentials.url, url)
        self.assertEqual(oci_credentials.getCredentials(), credentials)

    def test_new_with_existing(self):
        owner = self.factory.makePerson()
        url = self.factory.getUniqueURL()
        credentials = {"username": "foo", "password": "bar"}
        getUtility(IOCIRegistryCredentialsSet).new(
            registrant=owner, owner=owner, url=url, credentials=credentials
        )
        self.assertRaises(
            OCIRegistryCredentialsAlreadyExist,
            getUtility(IOCIRegistryCredentialsSet).new,
            registrant=owner,
            owner=owner,
            url=url,
            credentials=credentials,
        )

    def test_new_not_owner(self):
        registrant = self.factory.makePerson()
        other_person = self.factory.makePerson()
        other_team = self.factory.makeTeam(owner=other_person)
        url = self.factory.getUniqueURL()
        credentials = {"username": "foo", "password": "bar"}
        expected_message = "%s cannot create credentials owned by %s." % (
            registrant.display_name,
            other_person.display_name,
        )
        with ExpectedException(
            OCIRegistryCredentialsNotOwner, expected_message
        ):
            getUtility(IOCIRegistryCredentialsSet).new(
                registrant=registrant,
                owner=other_person,
                url=url,
                credentials=credentials,
            )
        expected_message = "%s is not a member of %s." % (
            registrant.display_name,
            other_team.display_name,
        )
        with ExpectedException(
            OCIRegistryCredentialsNotOwner, expected_message
        ):
            getUtility(IOCIRegistryCredentialsSet).new(
                registrant=registrant,
                owner=other_team,
                url=url,
                credentials=credentials,
            )

    def test_new_owner_override(self):
        # In certain situations, we might want to be able to create
        # credentials for other people
        registrant = self.factory.makePerson()
        other_person = self.factory.makePerson()
        url = self.factory.getUniqueURL()
        credentials = {"username": "foo", "password": "bar"}
        oci_credentials = getUtility(IOCIRegistryCredentialsSet).new(
            registrant=registrant,
            owner=other_person,
            url=url,
            credentials=credentials,
            override_owner=True,
        )
        self.assertEqual(oci_credentials.owner, other_person)
        self.assertEqual(oci_credentials.url, url)
        self.assertEqual(oci_credentials.getCredentials(), credentials)

    def test_getOrCreate_existing(self):
        owner = self.factory.makePerson()
        url = self.factory.getUniqueURL()
        credentials = {"username": "foo", "password": "bar"}
        new = getUtility(IOCIRegistryCredentialsSet).new(
            registrant=owner, owner=owner, url=url, credentials=credentials
        )

        existing = getUtility(IOCIRegistryCredentialsSet).getOrCreate(
            registrant=owner, owner=owner, url=url, credentials=credentials
        )

        self.assertEqual(new.id, existing.id)

    def test_getOrCreate_existing_by_region(self):
        owner = self.factory.makePerson()
        url = self.factory.getUniqueURL()
        west_credentials = {
            "username": "foo",
            "password": "bar",
            "region": "west",
        }
        west = getUtility(IOCIRegistryCredentialsSet).new(
            registrant=owner,
            owner=owner,
            url=url,
            credentials=west_credentials,
        )
        east_credentials = {
            "username": "foo",
            "password": "bar",
            "region": "east",
        }
        east = getUtility(IOCIRegistryCredentialsSet).new(
            registrant=owner,
            owner=owner,
            url=url,
            credentials=east_credentials,
        )
        self.assertNotEqual(west.id, east.id)

        existing_west = getUtility(IOCIRegistryCredentialsSet).getOrCreate(
            registrant=owner,
            owner=owner,
            url=url,
            credentials=west_credentials,
        )

        self.assertEqual(west.id, existing_west.id)

    def test_getOrCreate_new(self):
        owner = self.factory.makePerson()
        url = self.factory.getUniqueURL()
        credentials = {"username": "foo", "password": "bar"}
        new = getUtility(IOCIRegistryCredentialsSet).getOrCreate(
            registrant=owner, owner=owner, url=url, credentials=credentials
        )

        self.assertEqual(new.owner, owner)
        self.assertEqual(new.url, url)
        self.assertEqual(new.getCredentials(), credentials)

    def test_getOrCreate_not_owner(self):
        registrant = self.factory.makePerson()
        other_person = self.factory.makePerson()
        other_team = self.factory.makeTeam(owner=other_person)
        url = self.factory.getUniqueURL()
        credentials = {"username": "foo", "password": "bar"}
        expected_message = "%s cannot create credentials owned by %s." % (
            registrant.display_name,
            other_person.display_name,
        )
        with ExpectedException(
            OCIRegistryCredentialsNotOwner, expected_message
        ):
            getUtility(IOCIRegistryCredentialsSet).getOrCreate(
                registrant=registrant,
                owner=other_person,
                url=url,
                credentials=credentials,
            )
        expected_message = "%s is not a member of %s." % (
            registrant.display_name,
            other_team.display_name,
        )
        with ExpectedException(
            OCIRegistryCredentialsNotOwner, expected_message
        ):
            getUtility(IOCIRegistryCredentialsSet).getOrCreate(
                registrant=registrant,
                owner=other_team,
                url=url,
                credentials=credentials,
            )

    def test_findByOwner(self):
        owner = self.factory.makePerson()
        for _ in range(3):
            self.factory.makeOCIRegistryCredentials(
                registrant=owner, owner=owner
            )
        # make some that have a different owner
        for _ in range(5):
            self.factory.makeOCIRegistryCredentials()
        transaction.commit()

        found = getUtility(IOCIRegistryCredentialsSet).findByOwner(owner)
        self.assertEqual(found.count(), 3)
        for oci_credentials in found:
            self.assertEqual(oci_credentials.owner, owner)
