# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the internal Soyuz archive API."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from zope.security.proxy import removeSecurityProxy

from lp.services.features.testing import FeatureFixture
from lp.soyuz.interfaces.archive import NAMED_AUTH_TOKEN_FEATURE_FLAG
from lp.soyuz.xmlrpc.archive import ArchiveAPI
from lp.testing import TestCaseWithFactory
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.xmlrpc import faults


class TestArchiveAPI(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestArchiveAPI, self).setUp()
        self.useFixture(FeatureFixture({NAMED_AUTH_TOKEN_FEATURE_FLAG: "on"}))
        self.archive_api = ArchiveAPI(None, None)

    def assertNotFound(self, archive_reference, username, password, message):
        """Assert that an archive auth token check returns NotFound."""
        fault = self.archive_api.checkArchiveAuthToken(
            archive_reference, username, password)
        self.assertEqual(faults.NotFound(message), fault)

    def assertUnauthorized(self, archive_reference, username, password):
        """Assert that an archive auth token check returns Unauthorized."""
        fault = self.archive_api.checkArchiveAuthToken(
            archive_reference, username, password)
        self.assertEqual(faults.Unauthorized("Authorisation required."), fault)

    def test_checkArchiveAuthToken_unknown_archive(self):
        self.assertNotFound(
            "~nonexistent/unknown/bad", "user", "",
            "No archive found for '~nonexistent/unknown/bad'.")

    def test_checkArchiveAuthToken_no_tokens(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        self.assertNotFound(
            archive.reference, "nobody", "",
            "No valid tokens for 'nobody' in '%s'." % archive.reference)

    def test_checkArchiveAuthToken_no_named_tokens(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        self.assertNotFound(
            archive.reference, "+missing", "",
            "No valid tokens for '+missing' in '%s'." % archive.reference)

    def test_checkArchiveAuthToken_buildd_wrong_password(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        self.assertUnauthorized(
            archive.reference, "buildd", archive.buildd_secret + "-bad")

    def test_checkArchiveAuthToken_buildd_correct_password(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        self.assertIsNone(self.archive_api.checkArchiveAuthToken(
            archive.reference, "buildd", archive.buildd_secret))

    def test_checkArchiveAuthToken_named_token_wrong_password(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        token = archive.newNamedAuthToken("special")
        removeSecurityProxy(token).deactivate()
        self.assertNotFound(
            archive.reference, "+special", token.token,
            "No valid tokens for '+special' in '%s'." % archive.reference)

    def test_checkArchiveAuthToken_named_token_deactivated(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        token = archive.newNamedAuthToken("special")
        self.assertIsNone(self.archive_api.checkArchiveAuthToken(
            archive.reference, "+special", token.token))

    def test_checkArchiveAuthToken_named_token_correct_password(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        token = archive.newNamedAuthToken("special")
        self.assertIsNone(self.archive_api.checkArchiveAuthToken(
            archive.reference, "+special", token.token))

    def test_checkArchiveAuthToken_personal_token_wrong_password(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        subscriber = self.factory.makePerson()
        archive.newSubscription(subscriber, archive.owner)
        token = archive.newAuthToken(subscriber)
        self.assertUnauthorized(
            archive.reference, subscriber.name, token.token + "-bad")

    def test_checkArchiveAuthToken_personal_token_deactivated(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        subscriber = self.factory.makePerson()
        archive.newSubscription(subscriber, archive.owner)
        token = archive.newAuthToken(subscriber)
        removeSecurityProxy(token).deactivate()
        self.assertNotFound(
            archive.reference, subscriber.name, token.token,
            "No valid tokens for '%s' in '%s'." % (
                subscriber.name, archive.reference))

    def test_checkArchiveAuthToken_personal_token_cancelled(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        subscriber = self.factory.makePerson()
        subscription = archive.newSubscription(subscriber, archive.owner)
        token = archive.newAuthToken(subscriber)
        removeSecurityProxy(subscription).cancel(archive.owner)
        self.assertNotFound(
            archive.reference, subscriber.name, token.token,
            "No valid tokens for '%s' in '%s'." % (
                subscriber.name, archive.reference))

    def test_checkArchiveAuthToken_personal_token_correct_password(self):
        archive = removeSecurityProxy(self.factory.makeArchive(private=True))
        subscriber = self.factory.makePerson()
        archive.newSubscription(subscriber, archive.owner)
        token = archive.newAuthToken(subscriber)
        self.assertIsNone(self.archive_api.checkArchiveAuthToken(
            archive.reference, subscriber.name, token.token))
