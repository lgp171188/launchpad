# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the internal Soyuz archive API."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.services.features.testing import FeatureFixture
from lp.services.macaroons.interfaces import IMacaroonIssuer
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
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret")

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

    def test_checkArchiveAuthToken_buildd_macaroon_wrong_archive(self):
        archive = self.factory.makeArchive(private=True)
        build = self.factory.makeBinaryPackageBuild(archive=archive)
        other_archive = self.factory.makeArchive(
            distribution=archive.distribution, private=True)
        removeSecurityProxy(build).updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(
            getUtility(IMacaroonIssuer, "binary-package-build"))
        macaroon = issuer.issueMacaroon(build)
        self.assertUnauthorized(
            other_archive.reference, "buildd", macaroon.serialize())

    def test_checkArchiveAuthToken_buildd_macaroon_not_building(self):
        archive = self.factory.makeArchive(private=True)
        build = self.factory.makeBinaryPackageBuild(archive=archive)
        issuer = removeSecurityProxy(
            getUtility(IMacaroonIssuer, "binary-package-build"))
        macaroon = issuer.issueMacaroon(build)
        self.assertUnauthorized(
            archive.reference, "buildd", macaroon.serialize())

    def test_checkArchiveAuthToken_buildd_macaroon_wrong_user(self):
        archive = self.factory.makeArchive(private=True)
        build = self.factory.makeBinaryPackageBuild(archive=archive)
        removeSecurityProxy(build).updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(
            getUtility(IMacaroonIssuer, "binary-package-build"))
        macaroon = issuer.issueMacaroon(build)
        self.assertNotFound(
            archive.reference, "another-user", macaroon.serialize(),
            "No valid tokens for 'another-user' in '%s'." % archive.reference)

    def test_checkArchiveAuthToken_buildd_macaroon_correct(self):
        archive = self.factory.makeArchive(private=True)
        build = self.factory.makeBinaryPackageBuild(archive=archive)
        removeSecurityProxy(build).updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(
            getUtility(IMacaroonIssuer, "binary-package-build"))
        macaroon = issuer.issueMacaroon(build)
        self.assertIsNone(self.archive_api.checkArchiveAuthToken(
            archive.reference, "buildd", macaroon.serialize()))

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
