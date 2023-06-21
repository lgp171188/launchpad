# Copyright 2012-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the PersonalArchiveSubscription components and view."""

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.launchpad import ILaunchpadCelebrities, IPrivacy
from lp.services.config import config
from lp.services.signing.enums import SigningKeyType
from lp.soyuz.browser.archivesubscription import PersonalArchiveSubscription
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.gpgkeys import test_pubkey_from_email
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import extract_text, find_tag_by_id
from lp.testing.views import create_initialized_view


class TestPersonArchiveSubscriptionView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_personal_archive_subscription_adapts_to_privacy(self):
        owner = self.factory.makePerson(name="archiveowner")
        subscriber = self.factory.makePerson(name="subscriber")
        pppa = self.factory.makeArchive(owner=owner, private=True, name="pppa")
        with person_logged_in(owner):
            pppa.newSubscription(subscriber, owner)
        pas = PersonalArchiveSubscription(subscriber, pppa)
        privacy = IPrivacy(pas)
        self.assertTrue(privacy.private)

    def test_signed_with_local_key(self):
        owner = self.factory.makePerson(name="archiveowner")
        subscriber = self.factory.makePerson(name="subscriber")
        pppa = self.factory.makeArchive(owner=owner, private=True, name="pppa")
        key = self.factory.makeGPGKey(owner=owner)
        removeSecurityProxy(pppa).signing_key_fingerprint = key.fingerprint
        removeSecurityProxy(pppa).signing_key_owner = getUtility(
            ILaunchpadCelebrities
        ).ppa_key_guard
        with person_logged_in(owner):
            pppa.newSubscription(subscriber, owner)
        with person_logged_in(subscriber):
            pppa.newAuthToken(subscriber)
            pas = PersonalArchiveSubscription(subscriber, pppa)
            view = create_initialized_view(pas, "+index", principal=subscriber)
            signing_key = find_tag_by_id(view(), "signing-key")
            self.assertEqual(
                "This repository is signed with\n%s%s/%s OpenPGP key."
                % (key.keysize, key.algorithm.title, key.fingerprint),
                extract_text(signing_key),
            )
            self.assertEqual(
                "https://%s/pks/lookup?fingerprint=on&op=index&search=0x%s"
                % (config.gpghandler.public_host, key.fingerprint),
                signing_key.a["href"],
            )

    def test_signed_with_signing_service_key(self):
        owner = self.factory.makePerson(name="archiveowner")
        subscriber = self.factory.makePerson(name="subscriber")
        pppa = self.factory.makeArchive(owner=owner, private=True, name="pppa")
        test_key = test_pubkey_from_email("test@canonical.com")
        key = self.factory.makeSigningKey(
            SigningKeyType.OPENPGP,
            fingerprint="A419AE861E88BC9E04B9C26FBA2B9389DFD20543",
            public_key=test_key,
        )
        removeSecurityProxy(pppa).signing_key_fingerprint = key.fingerprint
        removeSecurityProxy(pppa).signing_key_owner = getUtility(
            ILaunchpadCelebrities
        ).ppa_key_guard
        with person_logged_in(owner):
            pppa.newSubscription(subscriber, owner)
        with person_logged_in(subscriber):
            pppa.newAuthToken(subscriber)
            pas = PersonalArchiveSubscription(subscriber, pppa)
            view = create_initialized_view(pas, "+index", principal=subscriber)
            signing_key = find_tag_by_id(view(), "signing-key")
            self.assertEqual(
                "This repository is signed with\n1024D/%s OpenPGP key."
                % key.fingerprint,
                extract_text(signing_key),
            )
            self.assertEqual(
                "https://%s/pks/lookup?fingerprint=on&op=index&search=0x%s"
                % (config.gpghandler.public_host, key.fingerprint),
                signing_key.a["href"],
            )
