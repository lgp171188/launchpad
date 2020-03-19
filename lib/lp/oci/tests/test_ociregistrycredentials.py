# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image registry credential storage."""

from __future__ import absolute_import, print_function, unicode_literals

import base64

from nacl.public import PrivateKey
from testtools.matchers import (
    Equals,
    MatchesDict,
    )
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.oci.interfaces.ociregistrycredentials import (
    IOCIRegistryCredentials,
    IOCIRegistryCredentialsSet,
    )
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import LaunchpadZopelessLayer


class TestOCIRegistryCredentials(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIRegistryCredentials, self).setUp()
        self.private_key = PrivateKey.generate()
        self.pushConfig(
            "oci",
            registry_secrets_public_key=base64.b64encode(
                bytes(self.private_key.public_key)).decode("UTF-8"))
        self.pushConfig(
            "oci",
            registry_secrets_private_key=base64.b64encode(
                bytes(self.private_key)))

    def test_implements_interface(self):
        target = getUtility(IOCIRegistryCredentialsSet).new(
            owner=self.factory.makePerson(),
            url='http://example.org',
            credentials={'username': 'foo', 'password': 'bar'})
        self.assertProvides(target, IOCIRegistryCredentials)

    def test_retrieve_encrypted_credentials(self):
        owner = self.factory.makePerson()
        target = self.factory.makeOCIRegistryCredentials(
            owner=owner,
            url='http://example.org',
            credentials={'username': 'foo', 'password': 'bar'})

        with person_logged_in(owner):
            self.assertThat(target.getCredentials(), MatchesDict({
                "username": Equals("foo"),
                "password": Equals("bar")}))

    def test_credentials_are_encrypted(self):
        credentials = {'username': 'foo', 'password': 'bar'}
        target = removeSecurityProxy(
                    self.factory.makeOCIRegistryCredentials(
                        credentials=credentials))
        self.assertIn('credentials_encrypted', target._credentials)
        self.assertIn('public_key', target._credentials)


class TestOCIRegistryCredentialsSet(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIRegistryCredentialsSet, self).setUp()
        self.private_key = PrivateKey.generate()
        self.pushConfig(
            "oci",
            registry_secrets_public_key=base64.b64encode(
                bytes(self.private_key.public_key)).decode("UTF-8"))
        self.pushConfig(
            "oci",
            registry_secrets_private_key=base64.b64encode(
                bytes(self.private_key)))

    def test_implements_interface(self):
        target_set = getUtility(IOCIRegistryCredentialsSet)
        self.assertProvides(target_set, IOCIRegistryCredentialsSet)

    def test_new(self):
        owner = self.factory.makePerson()
        url = unicode(self.factory.getUniqueURL())
        credentials = {'username': 'foo', 'password': 'bar'}
        target = getUtility(IOCIRegistryCredentialsSet).new(
            owner=owner,
            url=url,
            credentials=credentials)
        self.assertEqual(target.owner, owner)
        self.assertEqual(target.url, url)
        self.assertEqual(target.getCredentials(), credentials)

    def test_findByOwner(self):
        owner = self.factory.makePerson()
        for _ in range(3):
            self.factory.makeOCIRegistryCredentials(owner=owner)
        # make some that have a different owner
        for _ in range(5):
            self.factory.makeOCIRegistryCredentials()

        found = getUtility(IOCIRegistryCredentialsSet).findByOwner(owner)
        self.assertEqual(found.count(), 3)
        for target in found:
            self.assertEqual(target.owner, owner)
