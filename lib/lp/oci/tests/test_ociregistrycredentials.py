# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image registry credential storage."""

from __future__ import absolute_import, print_function, unicode_literals

import json

from testtools.matchers import (
    AfterPreprocessing,
    Equals,
    MatchesDict,
    )
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.oci.interfaces.ociregistrycredentials import (
    IOCIRegistryCredentials,
    IOCIRegistryCredentialsSet,
    )
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.services.crypto.interfaces import IEncryptedContainer
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import LaunchpadZopelessLayer


class TestOCIRegistryCredentials(OCIConfigHelperMixin, TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIRegistryCredentials, self).setUp()
        self.setConfig()

    def test_implements_interface(self):
        oci_credentials = getUtility(IOCIRegistryCredentialsSet).new(
            owner=self.factory.makePerson(),
            url='http://example.org',
            credentials={'username': 'foo', 'password': 'bar'})
        self.assertProvides(oci_credentials, IOCIRegistryCredentials)

    def test_retrieve_encrypted_credentials(self):
        owner = self.factory.makePerson()
        oci_credentials = self.factory.makeOCIRegistryCredentials(
            owner=owner,
            url='http://example.org',
            credentials={'username': 'foo', 'password': 'bar'})

        with person_logged_in(owner):
            self.assertThat(oci_credentials.getCredentials(), MatchesDict({
                "username": Equals("foo"),
                "password": Equals("bar")}))

    def test_credentials_are_encrypted(self):
        credentials = {'username': 'foo', 'password': 'bar'}
        oci_credentials = removeSecurityProxy(
            self.factory.makeOCIRegistryCredentials(
                credentials=credentials))
        container = getUtility(IEncryptedContainer, "oci-registry-secrets")
        self.assertThat(oci_credentials._credentials, MatchesDict({
            "credentials_encrypted": AfterPreprocessing(
                lambda value: json.loads(container.decrypt(value)),
                Equals(credentials)),
            }))


class TestOCIRegistryCredentialsSet(OCIConfigHelperMixin, TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIRegistryCredentialsSet, self).setUp()
        self.setConfig()

    def test_implements_interface(self):
        credentials_set = getUtility(IOCIRegistryCredentialsSet)
        self.assertProvides(credentials_set, IOCIRegistryCredentialsSet)

    def test_new(self):
        owner = self.factory.makePerson()
        url = unicode(self.factory.getUniqueURL())
        credentials = {'username': 'foo', 'password': 'bar'}
        oci_credentials = getUtility(IOCIRegistryCredentialsSet).new(
            owner=owner,
            url=url,
            credentials=credentials)
        self.assertEqual(oci_credentials.owner, owner)
        self.assertEqual(oci_credentials.url, url)
        self.assertEqual(oci_credentials.getCredentials(), credentials)

    def test_findByOwner(self):
        owner = self.factory.makePerson()
        for _ in range(3):
            self.factory.makeOCIRegistryCredentials(owner=owner)
        # make some that have a different owner
        for _ in range(5):
            self.factory.makeOCIRegistryCredentials()
        transaction.commit()

        found = getUtility(IOCIRegistryCredentialsSet).findByOwner(owner)
        self.assertEqual(found.count(), 3)
        for oci_credentials in found:
            self.assertEqual(oci_credentials.owner, owner)
