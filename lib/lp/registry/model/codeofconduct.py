# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A module for CodeOfConduct (CoC) related classes.

https://launchpad.canonical.com/CodeOfConduct
"""

__all__ = [
    "CodeOfConduct",
    "CodeOfConductSet",
    "CodeOfConductConf",
    "SignedCodeOfConduct",
    "SignedCodeOfConductSet",
]

import os
from datetime import datetime, timezone

import six
from storm.locals import Bool, DateTime, Int, Not, Reference, Unicode
from zope.component import getUtility
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.registry.interfaces.codeofconduct import (
    ICodeOfConduct,
    ICodeOfConductConf,
    ICodeOfConductSet,
    ISignedCodeOfConduct,
    ISignedCodeOfConductSet,
)
from lp.registry.interfaces.gpg import IGPGKeySet
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import flush_database_updates
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import fti_search
from lp.services.gpg.interfaces import (
    GPGKeyExpired,
    GPGKeyNotFoundError,
    GPGVerificationError,
    IGPGHandler,
)
from lp.services.mail.helpers import get_email_template
from lp.services.mail.sendmail import format_address, simple_sendmail
from lp.services.propertycache import cachedproperty
from lp.services.webapp import canonical_url


@implementer(ICodeOfConductConf)
class CodeOfConductConf:
    """Abstract Component to store the current CoC configuration."""

    # XXX: cprov 2005-02-17
    # Integrate this class with LaunchpadCentral configuration
    # in the future.

    path = "lib/lp/registry/codesofconduct/"
    prefix = "Ubuntu Code of Conduct - "
    currentrelease = "2.0"
    # Set the datereleased to the date that 1.0 CoC was released,
    # preserving everyone's Ubuntu Code of Conduct signatory status.
    # https://launchpad.net/products/launchpad/+bug/48995
    datereleased = datetime(2005, 4, 12, tzinfo=timezone.utc)


@implementer(ICodeOfConduct)
class CodeOfConduct:
    """CoC class model.

    A set of properties allow us to properly handle the CoC stored
    in the filesystem, so it's not a database class.
    """

    def __init__(self, version):
        self.version = version
        # verify if the respective file containing the code of conduct exists
        if not os.path.exists(self._filename):
            # raise something sane
            raise NotFoundError(version)

    @property
    def title(self):
        """Return preformatted title (config_prefix + version)."""

        # XXX: cprov 2005-02-18
        # Missed doctest, problems initing ZopeComponentLookupError.

        # Recover the prefix for CoC from a Component
        prefix = getUtility(ICodeOfConductConf).prefix

        # Build a fancy title
        return "%s" % prefix + self.version

    @property
    def content(self):
        """Return the content of the CoC file."""
        fp = open(self._filename)
        data = fp.read()
        fp.close()

        return data

    @property
    def current(self):
        """Is this the current release of the Code of Conduct?"""
        return getUtility(ICodeOfConductConf).currentrelease == self.version

    @property
    def _filename(self):
        """Rebuild filename according to the local version."""
        # Recover the path for CoC from a Component
        path = getUtility(ICodeOfConductConf).path
        return os.path.join(path, self.version + ".txt")

    @property
    def datereleased(self):
        return getUtility(ICodeOfConductConf).datereleased


@implementer(ICodeOfConductSet)
class CodeOfConductSet:
    """A set of CodeOfConducts."""

    title = "Launchpad Codes of Conduct"

    def __getitem__(self, version):
        """See ICodeOfConductSet."""
        # Create an entry point for the Admin Console
        # Obviously we are excluding a CoC version called 'console'
        if version == "console":
            return SignedCodeOfConductSet()
        # in normal conditions return the CoC Release
        try:
            return CodeOfConduct(version)
        except NotFoundError:
            return None

    def __iter__(self):
        """See ICodeOfConductSet."""
        releases = []

        # Recover the path for CoC from a component
        cocs_path = getUtility(ICodeOfConductConf).path

        # iter through files and store the CoC Object
        for entry in os.scandir(cocs_path):
            # Select the correct filenames
            if entry.name.endswith(".txt"):
                # Extract the version from filename
                version = entry.name.replace(".txt", "")
                releases.append(CodeOfConduct(version))

        # Return the available list of CoCs objects
        return iter(releases)

    @property
    def current_code_of_conduct(self):
        # XXX kiko 2006-08-01:
        # What a hack, but this whole file needs cleaning up.
        currentrelease = getUtility(ICodeOfConductConf).currentrelease
        for code in self:
            if currentrelease == code.version:
                return code
        raise AssertionError("No current code of conduct registered")


@implementer(ISignedCodeOfConduct)
class SignedCodeOfConduct(StormBase):
    """Code of Conduct."""

    __storm_table__ = "SignedCodeOfConduct"

    id = Int(primary=True)

    owner_id = Int(name="owner", allow_none=False)
    owner = Reference(owner_id, "Person.id")

    signedcode = Unicode(name="signedcode", allow_none=True, default=None)

    signing_key_fingerprint = Unicode()

    datecreated = DateTime(
        tzinfo=timezone.utc,
        name="datecreated",
        allow_none=False,
        default=UTC_NOW,
    )

    recipient_id = Int(name="recipient", allow_none=True, default=None)
    recipient = Reference(recipient_id, "Person.id")

    admincomment = Unicode(name="admincomment", allow_none=True, default=None)

    active = Bool(name="active", allow_none=False, default=False)

    affirmed = Bool(
        name="affirmed",
        allow_none=False,
        default=False,
    )

    version = Unicode(name="version", allow_none=True, default=None)

    def __init__(
        self,
        owner,
        signedcode=None,
        signing_key_fingerprint=None,
        recipient=None,
        active=False,
        affirmed=False,
        version=None,
    ):
        super().__init__()
        self.owner = owner
        self.signedcode = signedcode
        self.signing_key_fingerprint = signing_key_fingerprint
        self.recipient = recipient
        self.active = active
        self.affirmed = affirmed
        self.version = version

    @cachedproperty
    def signingkey(self):
        if self.signing_key_fingerprint is not None:
            return getUtility(IGPGKeySet).getByFingerprint(
                self.signing_key_fingerprint
            )

    @property
    def displayname(self):
        """Build a Fancy Title for CoC."""
        displayname = self.datecreated.strftime("%Y-%m-%d")

        if self.signingkey:
            displayname += ": digitally signed by %s (%s)" % (
                self.owner.displayname,
                self.signingkey.displayname,
            )
        elif self.affirmed:
            displayname += ": affirmed by %s" % self.owner.displayname
        else:
            displayname += (
                ": paper submission accepted by %s"
                % self.recipient.displayname
            )

        return displayname

    def sendAdvertisementEmail(self, subject, content):
        """See ISignedCodeOfConduct."""
        assert self.owner.preferredemail
        template = get_email_template(
            "signedcoc-acknowledge.txt", app="registry"
        )
        fromaddress = format_address(
            "Launchpad Code Of Conduct System",
            config.canonical.noreply_from_address,
        )
        replacements = {"user": self.owner.displayname, "content": content}
        message = template % replacements
        simple_sendmail(
            fromaddress, str(self.owner.preferredemail.email), subject, message
        )

    def sendAffirmationEmail(self, subject, content):
        """See ISignedCodeOfConduct."""
        assert self.owner.preferredemail
        template = get_email_template("signedcoc-affirmed.txt", app="registry")
        fromaddress = format_address(
            "Launchpad Code Of Conduct System",
            config.canonical.noreply_from_address,
        )
        replacements = {"user": self.owner.displayname, "content": content}
        message = template % replacements
        simple_sendmail(
            fromaddress, str(self.owner.preferredemail.email), subject, message
        )


@implementer(ISignedCodeOfConductSet)
class SignedCodeOfConductSet:
    """A set of CodeOfConducts"""

    title = "Code of Conduct Administrator Page"

    def __getitem__(self, id):
        """Get a Signed CoC Entry."""
        return IStore(SignedCodeOfConduct).get(SignedCodeOfConduct, int(id))

    def __iter__(self):
        """Iterate through the Signed CoC."""
        return iter(IStore(SignedCodeOfConduct).find(SignedCodeOfConduct))

    def verifyAndStore(self, user, signedcode):
        """See ISignedCodeOfConductSet."""
        # XXX cprov 2005-02-24:
        # Are we missing the version field in SignedCoC table?
        # how to figure out which CoC version is signed?

        # XXX: cprov 2005-02-27:
        # To be implemented:
        # * Valid Person (probably always true via permission lp.AnyPerson),
        # * Valid GPGKey (valid and active),
        # * Person and GPGkey matches (done on DB side too),
        # * CoC is the current version available, or the previous
        #   still-supported version in old.txt,
        # * CoC was signed (correctly) by the GPGkey.

        # use a utility to perform the GPG operations
        gpghandler = getUtility(IGPGHandler)

        try:
            sane_signedcode = signedcode.encode("utf-8")
        except UnicodeEncodeError:
            raise TypeError("Signed Code Could not be encoded as UTF-8")

        try:
            sig = gpghandler.getVerifiedSignature(sane_signedcode)
        except (GPGVerificationError, GPGKeyExpired, GPGKeyNotFoundError) as e:
            return str(e)

        if not sig.fingerprint:
            return (
                "The signature could not be verified. "
                "Check that the OpenPGP key you used to sign with "
                "is published correctly in the global key ring."
            )

        gpgkeyset = getUtility(IGPGKeySet)

        gpg = gpgkeyset.getByFingerprint(sig.fingerprint)

        if not gpg:
            return (
                "The key you used, which has the fingerprint <code>%s"
                "</code>, is not registered in Launchpad. Please "
                '<a href="%s/+editpgpkeys">follow the '
                "instructions</a> and try again."
                % (sig.fingerprint, canonical_url(user))
            )

        if gpg.owner.id != user.id:
            return (
                "You (%s) do not seem to be the owner of this OpenPGP "
                "key (<code>%s</code>)."
                % (user.displayname, gpg.owner.displayname)
            )

        if not gpg.active:
            return (
                "The OpenPGP key used (<code>%s</code>) has been "
                "deactivated. "
                'Please <a href="%s/+editpgpkeys">reactivate</a> it and '
                "try again." % (gpg.displayname, canonical_url(user))
            )

        # recover the current CoC release
        coc = CodeOfConduct(getUtility(ICodeOfConductConf).currentrelease)
        current = coc.content

        # calculate text digest
        if sig.plain_data.split() != current.encode("UTF-8").split():
            return (
                "The signed text does not match the Code of Conduct. "
                "Make sure that you signed the correct text (white "
                "space differences are acceptable)."
            )

        # Store the signature
        signed = SignedCodeOfConduct(
            owner=user,
            signing_key_fingerprint=gpg.fingerprint if gpg else None,
            signedcode=signedcode,
            active=True,
        )

        # Send Advertisement Email
        subject = "Your Code of Conduct signature has been acknowledged"
        content = "Digitally Signed by %s\n" % sig.fingerprint
        signed.sendAdvertisementEmail(subject, content)

    def affirmAndStore(self, user, codetext):
        """See `ISignedCodeOfConductSet`."""
        try:
            encoded_codetext = six.ensure_text(codetext)
        except UnicodeDecodeError:
            raise TypeError("Signed Code Could not be decoded as UTF-8")

        # recover the current CoC release
        coc = CodeOfConduct(getUtility(ICodeOfConductConf).currentrelease)
        current = coc.content

        if encoded_codetext.split() != six.ensure_text(current).split():
            return (
                "The affirmed text does not match the current "
                "Code of Conduct."
            )

        existing = (
            not self.searchByUser(user)
            .find(SignedCodeOfConduct.version == six.ensure_text(coc.version))
            .is_empty()
        )
        if existing:
            return "You have already affirmed the current Code of Conduct."

        affirmed = SignedCodeOfConduct(
            owner=user,
            affirmed=True,
            version=six.ensure_text(coc.version),
            active=True,
        )
        # Send Advertisement Email
        subject = "You have affirmed the Code of Conduct"
        content = "Version affirmed: %s\n\n%s" % (coc.version, coc.content)
        affirmed.sendAffirmationEmail(subject, content)

    def searchByDisplayname(self, displayname, searchfor=None):
        """See ISignedCodeOfConductSet."""
        # Circular import.
        from lp.registry.model.person import Person

        # XXX: cprov 2005-02-27:
        # FTI presents problems when query by incomplete names
        # and I'm not sure if the best solution here is to use
        # trivial ILIKE query. Opinion required on Review.

        clauses = [SignedCodeOfConduct.owner == Person.id]

        # XXX cprov 2005-03-02:
        # I'm not sure if the it is correct way to query ALL
        # entries. If it is it should be part of FTI queries,
        # isn't it ?

        # the name should work like a filter, if you don't enter anything
        # you get everything.
        if displayname:
            clauses.append(fti_search(Person, displayname))

        # Attempt to search for directive
        if searchfor == "activeonly":
            clauses.append(SignedCodeOfConduct.active)
        elif searchfor == "inactiveonly":
            clauses.append(Not(SignedCodeOfConduct.active))

        return (
            IStore(SignedCodeOfConduct)
            .find(SignedCodeOfConduct, *clauses)
            .order_by(SignedCodeOfConduct.active)
        )

    def searchByUser(self, user, active=True):
        """See ISignedCodeOfConductSet."""
        return IStore(SignedCodeOfConduct).find(
            SignedCodeOfConduct, owner=user, active=active
        )

    def modifySignature(self, sign_id, recipient, admincomment, state):
        """See ISignedCodeOfConductSet."""
        sign = IStore(SignedCodeOfConduct).get(SignedCodeOfConduct, sign_id)
        sign.active = state
        sign.admincomment = admincomment
        sign.recipient = recipient.id

        subject = "Launchpad: Code Of Conduct Signature Modified"
        content = (
            "State: %s\n"
            "Comment: %s\n"
            "Modified by %s" % (state, admincomment, recipient.displayname)
        )

        sign.sendAdvertisementEmail(subject, content)

        flush_database_updates()

    def acknowledgeSignature(self, user, recipient):
        """See ISignedCodeOfConductSet."""
        active = True
        sign = SignedCodeOfConduct(
            owner=user, recipient=recipient, active=active
        )

        subject = "Launchpad: Code Of Conduct Signature Acknowledge"
        content = "Paper Submitted acknowledge by %s" % recipient.displayname

        sign.sendAdvertisementEmail(subject, content)

    def getLastAcceptedDate(self):
        """See ISignedCodeOfConductSet."""
        return getUtility(ICodeOfConductConf).datereleased
