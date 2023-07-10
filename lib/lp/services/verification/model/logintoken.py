# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "LoginToken",
    "LoginTokenSet",
]

import hashlib
from datetime import timezone

import six
from storm.expr import And, Is
from storm.properties import DateTime, Int, Unicode
from storm.references import Reference
from zope.component import getUtility
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.app.validators.email import valid_email
from lp.registry.interfaces.gpg import IGPGKeySet
from lp.registry.interfaces.person import IPersonSet
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.gpg.interfaces import IGPGHandler
from lp.services.mail.helpers import get_email_template
from lp.services.mail.sendmail import format_address, simple_sendmail
from lp.services.tokens import create_token
from lp.services.verification.interfaces.authtoken import LoginTokenType
from lp.services.verification.interfaces.logintoken import (
    ILoginToken,
    ILoginTokenSet,
)
from lp.services.webapp import canonical_url

MAIL_APP = "services/verification"


@implementer(ILoginToken)
class LoginToken(StormBase):
    __storm_table__ = "LoginToken"

    id = Int(primary=True)
    redirection_url = Unicode(default=None)
    requester_id = Int(name="requester")
    requester = Reference(requester_id, "Person.id")
    requesteremail = Unicode(
        name="requesteremail", allow_none=True, default=None
    )
    email = Unicode(name="email", allow_none=False)

    # The hex SHA-256 hash of the token.
    _token = Unicode(name="token")

    tokentype = DBEnum(name="tokentype", allow_none=False, enum=LoginTokenType)
    date_created = DateTime(
        name="created", allow_none=False, tzinfo=timezone.utc
    )
    fingerprint = Unicode(name="fingerprint", allow_none=True, default=None)
    date_consumed = DateTime(default=None, tzinfo=timezone.utc)
    password = ""  # Quick fix for Bug #2481

    title = "Launchpad Email Verification"

    def __init__(
        self,
        email,
        tokentype,
        redirection_url=None,
        requester=None,
        requesteremail=None,
        token=None,
        fingerprint=None,
    ):
        super().__init__()
        self.email = email
        self.tokentype = tokentype
        self.redirection_url = redirection_url
        self.requester = requester
        self.requesteremail = requesteremail
        if token is not None:
            self._plaintext_token = token
            self._token = hashlib.sha256(token.encode("UTF-8")).hexdigest()
        self.fingerprint = fingerprint

    _plaintext_token = None

    @property
    def token(self):
        if self._plaintext_token is None:
            raise AssertionError(
                "Token only available for LoginTokens obtained by token in "
                "the first place. The DB only stores the hashed version."
            )
        return self._plaintext_token

    def consume(self):
        """See ILoginToken."""
        self.date_consumed = UTC_NOW

        # Find all the unconsumed tokens that we need to consume. We
        # don't bother with consumed tokens for performance reasons.
        if self.fingerprint is not None:
            tokens = LoginTokenSet().searchByFingerprintRequesterAndType(
                self.fingerprint,
                self.requester,
                self.tokentype,
                consumed=False,
            )
        else:
            tokens = LoginTokenSet().searchByEmailRequesterAndType(
                self.email, self.requester, self.tokentype, consumed=False
            )

        for token in tokens:
            token.date_consumed = UTC_NOW

    def _send_email(self, from_name, subject, message, headers=None):
        """Send an email to this token's email address."""
        from_address = format_address(
            from_name, config.canonical.noreply_from_address
        )
        to_address = str(self.email)
        simple_sendmail(
            from_address,
            to_address,
            subject,
            message,
            headers=headers,
            bulk=False,
        )

    def sendEmailValidationRequest(self):
        """See ILoginToken."""
        template = get_email_template("validate-email.txt", app=MAIL_APP)
        replacements = {
            "token_url": canonical_url(self),
            "requester": self.requester.displayname,
            "requesteremail": self.requesteremail,
            "toaddress": self.email,
        }
        message = template % replacements
        subject = "Launchpad: Validate your email address"
        self._send_email("Launchpad Email Validator", subject, message)
        self.requester.security_field_changed(
            "A new email address is being added to your Launchpad account.",
            "<%s> will be activated for your account when you follow the "
            "instructions that were sent to <%s>." % (self.email, self.email),
        )

    def sendGPGValidationRequest(self, key):
        """See ILoginToken."""
        separator = "\n    "
        formatted_uids = "    " + separator.join(key.emails)

        assert self.tokentype in (
            LoginTokenType.VALIDATEGPG,
            LoginTokenType.VALIDATESIGNONLYGPG,
        )

        # Craft the confirmation message that will be sent to the user.  There
        # are two chunks of text that will be concatenated together into a
        # single text/plain part.  The first chunk will be the clear text
        # instructions providing some extra help for those people who cannot
        # read the encrypted chunk that follows.  The encrypted chunk will
        # have the actual confirmation token in it, however the ability to
        # read this is highly dependent on the mail reader being used, and how
        # that MUA is configured.

        # Here are the instructions that need to be encrypted.
        template = get_email_template("validate-gpg.txt", app=MAIL_APP)
        key_type = "%s%s" % (key.keysize, key.algorithm.title)
        replacements = {
            "requester": self.requester.displayname,
            "requesteremail": self.requesteremail,
            "key_type": key_type,
            "fingerprint": key.fingerprint,
            "uids": formatted_uids,
            "token_url": canonical_url(self),
        }

        token_text = template % replacements
        salutation = "Hello,\n\n"
        instructions = ""
        closing = "Thanks,\n\nThe Launchpad Team"

        # Encrypt this part's content if requested.
        if key.can_encrypt:
            gpghandler = getUtility(IGPGHandler)
            token_text = six.ensure_text(
                gpghandler.encryptContent(token_text.encode("utf-8"), key)
            )
            # In this case, we need to include some clear text instructions
            # for people who do not have an MUA that can decrypt the ASCII
            # armored text.
            instructions = get_email_template(
                "gpg-cleartext-instructions.txt", app=MAIL_APP
            )

        # Concatenate the message parts and send it.
        text = salutation + instructions + token_text + closing
        from_name = "Launchpad OpenPGP Key Confirmation"
        subject = "Launchpad: Confirm your OpenPGP Key"
        self._send_email(from_name, subject, text)

    def sendMergeRequestEmail(self):
        """See ILoginToken."""
        template = get_email_template("request-merge.txt", app=MAIL_APP)
        from_name = "Launchpad Account Merge"

        dupe = getUtility(IPersonSet).getByEmail(
            self.email, filter_status=False
        )
        replacements = {
            "dupename": "%s (%s)" % (dupe.displayname, dupe.name),
            "requester": self.requester.name,
            "requesteremail": self.requesteremail,
            "toaddress": self.email,
            "token_url": canonical_url(self),
        }
        message = template % replacements

        subject = "Launchpad: Merge of Accounts Requested"
        self._send_email(from_name, subject, message)

    def sendTeamEmailAddressValidationEmail(self, user):
        """See ILoginToken."""
        template = get_email_template("validate-teamemail.txt", app=MAIL_APP)

        from_name = "Launchpad Email Validator"
        subject = "Launchpad: Validate your team's contact email address"
        replacements = {
            "team": self.requester.displayname,
            "requester": "%s (%s)" % (user.displayname, user.name),
            "toaddress": self.email,
            "admin_email": config.canonical.admin_address,
            "token_url": canonical_url(self),
        }
        message = template % replacements
        self._send_email(from_name, subject, message)

    def sendClaimTeamEmail(self):
        """See `ILoginToken`."""
        template = get_email_template("claim-team.txt", app=MAIL_APP)
        from_name = "Launchpad"
        profile = getUtility(IPersonSet).getByEmail(
            self.email, filter_status=False
        )
        replacements = {
            "profile_name": ("%s (%s)" % (profile.displayname, profile.name)),
            "requester_name": (
                "%s (%s)" % (self.requester.displayname, self.requester.name)
            ),
            "email": self.email,
            "token_url": canonical_url(self),
        }
        message = template % replacements
        subject = "Launchpad: Claim existing team"
        self._send_email(from_name, subject, message)

    @property
    def validation_phrase(self):
        """The phrase used to validate sign-only GPG keys"""
        utctime = self.date_created.astimezone(timezone.utc)
        return "Please register %s to the\nLaunchpad user %s.  %s UTC" % (
            self.fingerprint,
            self.requester.name,
            utctime.strftime("%Y-%m-%d %H:%M:%S"),
        )

    def activateGPGKey(self, key, can_encrypt):
        """See `ILoginToken`."""
        lpkey, new = getUtility(IGPGKeySet).activate(
            self.requester, key, can_encrypt
        )
        self.consume()
        return lpkey, new

    def destroySelf(self):
        """See `ILoginToken`."""
        IStore(self).remove(self)


@implementer(ILoginTokenSet)
class LoginTokenSet:
    def __init__(self):
        self.title = "Launchpad email address confirmation"

    def get(self, id, default=None):
        """See ILoginTokenSet."""
        token = IStore(LoginToken).get(LoginToken, id)
        if token is None:
            return default
        return token

    def searchByEmailRequesterAndType(
        self, email, requester, type, consumed=None
    ):
        """See ILoginTokenSet."""
        conditions = And(
            LoginToken.email == email,
            LoginToken.requester == requester,
            LoginToken.tokentype == type,
        )

        if consumed is True:
            conditions = And(conditions, LoginToken.date_consumed != None)
        elif consumed is False:
            conditions = And(conditions, LoginToken.date_consumed == None)
        else:
            assert consumed is None, (
                "consumed should be one of {True, False, None}. Got '%s'."
                % consumed
            )

        # It's important to always use the PRIMARY_FLAVOR store here
        # because we don't want replication lag to cause a 404 error.
        return IPrimaryStore(LoginToken).find(LoginToken, conditions)

    def deleteByEmailRequesterAndType(self, email, requester, type):
        """See ILoginTokenSet."""
        for token in self.searchByEmailRequesterAndType(
            email, requester, type
        ):
            token.destroySelf()

    def searchByFingerprintRequesterAndType(
        self, fingerprint, requester, type, consumed=None
    ):
        """See ILoginTokenSet."""
        conditions = And(
            LoginToken.fingerprint == fingerprint,
            LoginToken.requester == requester,
            LoginToken.tokentype == type,
        )

        if consumed is True:
            conditions = And(conditions, LoginToken.date_consumed != None)
        elif consumed is False:
            conditions = And(conditions, LoginToken.date_consumed == None)
        else:
            assert consumed is None, (
                "consumed should be one of {True, False, None}. Got '%s'."
                % consumed
            )

        # It's important to always use the PRIMARY_FLAVOR store here
        # because we don't want replication lag to cause a 404 error.
        return IPrimaryStore(LoginToken).find(LoginToken, conditions)

    def getPendingGPGKeys(self, requesterid=None):
        """See ILoginTokenSet."""
        clauses = [
            Is(LoginToken.date_consumed, None),
            LoginToken.tokentype.is_in(
                (
                    LoginTokenType.VALIDATEGPG,
                    LoginTokenType.VALIDATESIGNONLYGPG,
                )
            ),
        ]

        if requesterid:
            clauses.append(LoginToken.requester == requesterid)

        return IStore(LoginToken).find(LoginToken, *clauses)

    def deleteByFingerprintRequesterAndType(
        self, fingerprint, requester, type
    ):
        tokens = self.searchByFingerprintRequesterAndType(
            fingerprint, requester, type
        )
        for token in tokens:
            token.destroySelf()

    def new(
        self,
        requester,
        requesteremail,
        email,
        tokentype,
        fingerprint=None,
        redirection_url=None,
    ):
        """See ILoginTokenSet."""
        assert valid_email(email)
        if tokentype not in LoginTokenType.items:
            # XXX: Guilherme Salgado, 2005-12-09:
            # Aha! According to our policy, we shouldn't raise ValueError.
            raise ValueError(
                "tokentype is not an item of LoginTokenType: %s" % tokentype
            )
        token = create_token(20)
        return LoginToken(
            requester=requester,
            requesteremail=requesteremail,
            email=email,
            token=token,
            tokentype=tokentype,
            fingerprint=fingerprint,
            redirection_url=redirection_url,
        )

    def __getitem__(self, tokentext):
        """See ILoginTokenSet."""
        token = (
            IStore(LoginToken)
            .find(
                LoginToken,
                _token=hashlib.sha256(tokentext.encode("UTF-8")).hexdigest(),
            )
            .one()
        )
        if token is None:
            raise NotFoundError(tokentext)
        token._plaintext_token = tokentext
        return token
