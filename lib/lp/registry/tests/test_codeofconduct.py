# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test codes of conduct."""

from textwrap import dedent

from storm.exceptions import NoneError
from testtools.matchers import ContainsDict, Equals, MatchesRegex
from zope.component import getUtility

from lp.registry.interfaces.codeofconduct import (
    ICodeOfConductSet,
    ISignedCodeOfConductSet,
)
from lp.registry.model.codeofconduct import SignedCodeOfConduct
from lp.services.config import config
from lp.services.gpg.handler import PymeSignature
from lp.services.gpg.interfaces import (
    GPGKeyExpired,
    GPGKeyNotFoundError,
    GPGVerificationError,
    IGPGHandler,
)
from lp.services.mail.sendmail import format_address
from lp.testing import TestCaseWithFactory
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import ZopelessDatabaseLayer


class FakePymeKey:
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint


class FakeGPGHandlerBadSignature:
    def getVerifiedSignature(self, content, signature=None):
        raise GPGVerificationError("Bad signature.")


class FakeGPGHandlerExpired:
    def __init__(self, key):
        self.key = key

    def getVerifiedSignature(self, content, signature=None):
        raise GPGKeyExpired(self.key)


class FakeGPGHandlerNotFound:
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint

    def getVerifiedSignature(self, content, signature=None):
        raise GPGKeyNotFoundError(self.fingerprint)


class FakeGPGHandlerGood:
    def __init__(self, signature):
        self.signature = signature

    def getVerifiedSignature(self, content, signature=None):
        return self.signature


class TestSignedCodeOfConductSet(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def test_verifyAndStore_bad_signature(self):
        self.useFixture(
            ZopeUtilityFixture(FakeGPGHandlerBadSignature(), IGPGHandler)
        )
        user = self.factory.makePerson()
        self.assertEqual(
            "Bad signature.",
            getUtility(ISignedCodeOfConductSet).verifyAndStore(
                user, "signed data"
            ),
        )

    def test_verifyAndStore_expired(self):
        key = FakePymeKey("0" * 40)
        self.useFixture(
            ZopeUtilityFixture(FakeGPGHandlerExpired(key), IGPGHandler)
        )
        user = self.factory.makePerson()
        self.assertEqual(
            "%s has expired" % key.fingerprint,
            getUtility(ISignedCodeOfConductSet).verifyAndStore(
                user, "signed data"
            ),
        )

    def test_verifyAndStore_not_found(self):
        fingerprint = "0" * 40
        self.useFixture(
            ZopeUtilityFixture(
                FakeGPGHandlerNotFound(fingerprint), IGPGHandler
            )
        )
        user = self.factory.makePerson()
        self.assertEqual(
            "No GPG key found with the given content: %s" % fingerprint,
            getUtility(ISignedCodeOfConductSet).verifyAndStore(
                user, "signed data"
            ),
        )

    def test_verifyAndStore_unregistered(self):
        fingerprint = "0" * 40
        signature = PymeSignature(fingerprint, b"plain data")
        self.useFixture(
            ZopeUtilityFixture(FakeGPGHandlerGood(signature), IGPGHandler)
        )
        user = self.factory.makePerson()
        self.assertThat(
            getUtility(ISignedCodeOfConductSet).verifyAndStore(
                user, "signed data"
            ),
            MatchesRegex(r"^The key you used.*is not registered"),
        )

    def test_verifyAndStore_wrong_owner(self):
        other_user = self.factory.makePerson()
        gpgkey = self.factory.makeGPGKey(other_user)
        signature = PymeSignature(gpgkey.fingerprint, b"plain data")
        self.useFixture(
            ZopeUtilityFixture(FakeGPGHandlerGood(signature), IGPGHandler)
        )
        user = self.factory.makePerson()
        self.assertThat(
            getUtility(ISignedCodeOfConductSet).verifyAndStore(
                user, "signed data"
            ),
            MatchesRegex(r"^You.*do not seem to be the owner"),
        )

    def test_verifyAndStore_deactivated(self):
        user = self.factory.makePerson()
        gpgkey = self.factory.makeGPGKey(user)
        gpgkey.active = False
        signature = PymeSignature(gpgkey.fingerprint, b"plain data")
        self.useFixture(
            ZopeUtilityFixture(FakeGPGHandlerGood(signature), IGPGHandler)
        )
        self.assertThat(
            getUtility(ISignedCodeOfConductSet).verifyAndStore(
                user, "signed data"
            ),
            MatchesRegex(r"^The OpenPGP key used.*has been deactivated"),
        )

    def test_verifyAndStore_bad_plain_data(self):
        user = self.factory.makePerson()
        gpgkey = self.factory.makeGPGKey(user)
        signature = PymeSignature(gpgkey.fingerprint, b"plain data")
        self.useFixture(
            ZopeUtilityFixture(FakeGPGHandlerGood(signature), IGPGHandler)
        )
        self.assertThat(
            getUtility(ISignedCodeOfConductSet).verifyAndStore(
                user, "signed data"
            ),
            MatchesRegex(
                r"^The signed text does not match the Code of Conduct"
            ),
        )

    def test_verifyAndStore_good(self):
        user = self.factory.makePerson()
        gpgkey = self.factory.makeGPGKey(user)
        current = getUtility(ICodeOfConductSet).current_code_of_conduct.content
        signature = PymeSignature(gpgkey.fingerprint, current.encode("UTF-8"))
        self.useFixture(
            ZopeUtilityFixture(FakeGPGHandlerGood(signature), IGPGHandler)
        )
        self.assertIsNone(
            getUtility(ISignedCodeOfConductSet).verifyAndStore(
                user, "signed data"
            )
        )
        [notification] = self.assertEmailQueueLength(1)
        self.assertThat(
            dict(notification),
            ContainsDict(
                {
                    "From": Equals(
                        format_address(
                            "Launchpad Code Of Conduct System",
                            config.canonical.noreply_from_address,
                        )
                    ),
                    "To": Equals(user.preferredemail.email),
                    "Subject": Equals(
                        "Your Code of Conduct signature has been acknowledged"
                    ),
                }
            ),
        )
        self.assertEqual(
            dedent(
                """\

                Hello

                Your Code of Conduct Signature was modified.

                User: '%(user)s'
                Digitally Signed by %(fingerprint)s


                Thanks,

                The Launchpad Team
                """
            )
            % {
                "user": user.display_name,
                "fingerprint": gpgkey.fingerprint,
            },
            notification.get_payload(decode=True).decode("UTF-8"),
        )

    def test_affirmAndStore_good(self):
        user = self.factory.makePerson()
        current = getUtility(ICodeOfConductSet).current_code_of_conduct
        self.assertIsNone(
            getUtility(ISignedCodeOfConductSet).affirmAndStore(
                user, current.content
            )
        )
        [notification] = self.assertEmailQueueLength(1)
        self.assertThat(
            dict(notification),
            ContainsDict(
                {
                    "From": Equals(
                        format_address(
                            "Launchpad Code Of Conduct System",
                            config.canonical.noreply_from_address,
                        )
                    ),
                    "To": Equals(user.preferredemail.email),
                    "Subject": Equals("You have affirmed the Code of Conduct"),
                }
            ),
        )
        self.assertEqual(
            dedent(
                """\

                Hello

                You have affirmed the Code of Conduct.

                User: '%(user)s'
                Version affirmed: %(version)s

                %(content)s

                Thanks,

                The Launchpad Team
                """
            )
            % {
                "user": user.display_name,
                "version": current.version,
                "content": current.content,
            },
            notification.get_payload(decode=True).decode("UTF-8"),
        )

    def test_affirmAndStore_incorrect_text(self):
        user = self.factory.makePerson()
        self.assertEqual(
            "The affirmed text does not match the current Code of Conduct.",
            getUtility(ISignedCodeOfConductSet).affirmAndStore(user, "foo"),
        )

    def test_affirmAndStore_existing(self):
        user = self.factory.makePerson()
        current = getUtility(ICodeOfConductSet).current_code_of_conduct
        self.assertIsNone(
            getUtility(ISignedCodeOfConductSet).affirmAndStore(
                user, current.content
            )
        )

        self.assertEqual(
            "You have already affirmed the current Code of Conduct.",
            getUtility(ISignedCodeOfConductSet).affirmAndStore(
                user, current.content
            ),
        )


class TestSignedCodeOfConduct(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def test_affirmed_cant_be_instantiated_with_none(self):
        self.assertRaises(
            NoneError,
            SignedCodeOfConduct,
            owner=self.factory.makePerson(),
            affirmed=None,
        )

    def test_affirmed_cant_be_none(self):
        coc = SignedCodeOfConduct(owner=self.factory.makePerson())
        self.assertRaises(NoneError, setattr, coc, "affirmed", None)
