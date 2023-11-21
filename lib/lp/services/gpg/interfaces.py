# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "get_gpg_home_directory",
    "get_gpg_path",
    "get_gpgme_context",
    "GPG_INJECT",
    "GPGKeyAlgorithm",
    "GPGKeyDoesNotExistOnServer",
    "GPGKeyExpired",
    "GPGKeyNotFoundError",
    "GPGKeyRevoked",
    "GPGKeyMismatchOnServer",
    "GPGKeyTemporarilyNotFoundError",
    "GPGUploadFailure",
    "GPGVerificationError",
    "gpg_algorithm_letter",
    "IGPGHandler",
    "IPymeKey",
    "IPymeSignature",
    "IPymeUserId",
    "MoreThanOneGPGKeyFound",
    "SecretGPGKeyImportDetected",
    "valid_fingerprint",
    "valid_keyid",
]

import atexit
import http.client
import os.path
import re
import shutil
import tempfile

from lazr.enum import DBEnumeratedType, DBItem
from lazr.restful.declarations import error_status
from zope.interface import Attribute, Interface

GPG_INJECT = "gpg.signing_service.injection.enabled"


def valid_fingerprint(fingerprint):
    """Is the fingerprint of valid form."""
    # Fingerprints of v3 keys are md5, fingerprints of v4 keys are sha1;
    # accordingly, fingerprints of v3 keys are 128 bit, those of v4 keys
    # 160. Check therefore for strings of hex characters that are 32
    # (4 * 32 == 128) or 40 characters long (4 * 40 = 160).
    if len(fingerprint) not in (32, 40):
        return False
    if re.match(r"^[\dA-F]+$", fingerprint) is None:
        return False
    return True


def valid_keyid(keyid):
    """Is the key of valid form."""
    if re.match(r"^[\dA-F]{8}$", keyid) is not None:
        return True
    else:
        return False


def get_gpg_path():
    """Return the path to the GPG executable we prefer."""
    return "/usr/bin/gpg2"


_gpg_home = None


def get_gpg_home_directory():
    """Create a new GnuPG home directory for this process.

    This also installs an atexit handler to remove the directory on normal
    process termination.
    """
    global _gpg_home

    if _gpg_home is not None and os.path.exists(_gpg_home):
        return _gpg_home

    _gpg_home = tempfile.mkdtemp(prefix="gpg-")
    confpath = os.path.join(_gpg_home, "gpg.conf")
    with open(confpath, "w") as conf:
        # Avoid wasting time verifying the local keyring's consistency.
        conf.write("no-auto-check-trustdb\n")
        # Use the loopback mode to allow using password callbacks.
        conf.write("pinentry-mode loopback\n")
        # Assume "yes" on most questions; this is needed to allow
        # deletion of secret keys via GPGME.
        conf.write("yes\n")
        # Prefer a SHA-2 hash where possible, otherwise GPG will fall
        # back to a hash it can use.
        conf.write("personal-digest-preferences SHA512 SHA384 SHA256 SHA224\n")
    agentconfpath = os.path.join(_gpg_home, "gpg-agent.conf")
    with open(agentconfpath, "w") as agentconf:
        agentconf.write("allow-loopback-pinentry\n")

    def removeHome(home):
        """Remove GnuPG home directory."""
        if os.path.exists(home):
            shutil.rmtree(home)

    # Remove the configuration directory on normal termination.
    atexit.register(removeHome, _gpg_home)

    return _gpg_home


def get_gpgme_context():
    """Return a new appropriately-configured GPGME context."""
    import gpgme

    context = gpgme.Context()
    context.set_engine_info(
        gpgme.PROTOCOL_OpenPGP, get_gpg_path(), get_gpg_home_directory()
    )
    context.armor = True
    return context


class GPGKeyAlgorithm(DBEnumeratedType):
    """
    GPG Public Key Algorithm

    The numbers must match those in `gpgme_pubkey_algo_t`
    (https://git.gnupg.org/cgi-bin/gitweb.cgi?p=gpgme.git;a=blob;f=src/gpgme.h.in).
    """

    R = DBItem(1, "RSA")
    LITTLE_G = DBItem(16, "ElGamal")
    D = DBItem(17, "DSA")
    G = DBItem(20, "ElGamal, compromised")
    ECDSA = DBItem(301, "ECDSA")
    ECDH = DBItem(302, "ECDH")
    EDDSA = DBItem(303, "EDDSA")


def gpg_algorithm_letter(algorithm):
    """Return a single letter describing a GPG public key algorithm.

    This can be used in display names of keys.

    See `pubkey_letter` in GnuPG
    (https://git.gnupg.org/cgi-bin/gitweb.cgi?p=gnupg.git;a=blob;f=g10/keyid.c)
    for the single-letter codes used here.  Note that they are not
    necessarily unique.
    """
    if algorithm == GPGKeyAlgorithm.R:
        return "R"
    elif algorithm == GPGKeyAlgorithm.LITTLE_G:
        return "g"
    elif algorithm == GPGKeyAlgorithm.D:
        return "D"
    elif algorithm == GPGKeyAlgorithm.G:
        return "G"
    elif algorithm in (GPGKeyAlgorithm.ECDSA, GPGKeyAlgorithm.EDDSA):
        return "E"
    elif algorithm == GPGKeyAlgorithm.ECDH:
        return "e"


class MoreThanOneGPGKeyFound(Exception):
    """More than one GPG key was found.

    And we don't know which one to import.
    """


class GPGKeyNotFoundError(Exception):
    """The GPG key with this fingerprint was not found on the keyserver."""

    def __init__(self, fingerprint, message=None):
        self.fingerprint = fingerprint
        if message is None:
            message = "No GPG key found with the given content: %s" % (
                fingerprint,
            )
        super().__init__(message)


@error_status(http.client.INTERNAL_SERVER_ERROR)
class GPGKeyTemporarilyNotFoundError(GPGKeyNotFoundError):
    """The GPG key with this fingerprint was not found on the keyserver.

    The reason is a timeout while accessing the server, a general
    server error, a network problem or some other temporary issue.
    """

    def __init__(self, fingerprint):
        message = (
            "GPG key %s not found due to a server or network failure."
            % fingerprint
        )
        super().__init__(fingerprint, message)


@error_status(http.client.NOT_FOUND)
class GPGKeyDoesNotExistOnServer(GPGKeyNotFoundError):
    """The GPG key with this fingerprint was not found on the keyserver.

    The server returned an explicit "not found".
    """

    def __init__(self, fingerprint):
        message = "GPG key %s does not exist on the keyserver." % fingerprint
        super().__init__(fingerprint, message)


class GPGKeyRevoked(Exception):
    """The given GPG key was revoked."""

    def __init__(self, key):
        self.key = key
        super().__init__("%s has been publicly revoked" % (key.fingerprint,))


class GPGKeyExpired(Exception):
    """The given GPG key has expired."""

    def __init__(self, key):
        self.key = key
        super().__init__("%s has expired" % (key.fingerprint,))


class GPGKeyMismatchOnServer(Exception):
    """The keyserver returned the wrong key for a given fingerprint.

    This may indicate a keyserver compromise.
    """

    def __init__(self, expected_fingerprint, keyserver_fingerprint):
        self.expected_fingerprint = expected_fingerprint
        self.keyserver_fingerprint = keyserver_fingerprint
        message = (
            "The keyserver returned the wrong key: expected %s, got %s."
            % (expected_fingerprint, keyserver_fingerprint)
        )
        super().__init__(message)


class SecretGPGKeyImportDetected(Exception):
    """An attempt to import a secret GPG key."""


class GPGUploadFailure(Exception):
    """Raised when a key upload failed.

    Typically when a keyserver is not reachable.
    """


class GPGVerificationError(Exception):
    """OpenPGP verification error."""


class IGPGHandler(Interface):
    """Handler to perform OpenPGP operations."""

    def sanitizeFingerprint(fingerprint):
        """Return sanitized fingerprint if well-formed.

        If the fingerprint cannot be sanitized return None.
        """

    def getURLForKeyInServer(fingerprint, action=None, public=False):
        """Return the URL for that fingerprint on the configured keyserver.

        If public is True, return a URL for the public keyserver; otherwise,
        references the default (internal) keyserver.
        If action is provided, will attach that to the URL.
        """

    def getVerifiedSignatureResilient(content, signature=None):
        """Wrapper for getVerifiedSignature.

        This calls the target method up to three times.  Successful results
        are returned immediately, and GPGKeyExpired errors are raised
        immediately.  Otherwise, captures the errors and raises
        GPGVerificationError with the accumulated error information.
        """

    def getVerifiedSignature(content, signature=None):
        """Returns a PymeSignature object if content is correctly signed.

        If signature is None, we assume content is clearsigned. Otherwise
        it stores the detached signature and content should contain the
        plain text in question.

        content and signature must be 8-bit encoded str objects. It's up to
        the caller to encode or decode as appropriate.

        :param content: The content to be verified as string;
        :param signature: The signature as string (or None if content is
            clearsigned)

        :raise GPGVerificationError: if the signature cannot be verified.
        :raise GPGKeyExpired: if the signature was made with an expired key.
        :raise GPGKeyNotFoundError: if the key was not found on the keyserver.
        :return: a `PymeSignature` object.
        """

    def importPublicKey(content):
        """Import the given public key into our local keyring.

        If the secret key's ASCII armored content is given,
        SecretGPGKeyDetected is raised.

        If no key is found, GPGKeyNotFoundError is raised.  On the other
        hand, if more than one key is found, MoreThanOneGPGKeyFound is
        raised.

        :param content: public key ASCII armored content (must be an ASCII
            string (it's up to the caller to encode or decode properly);
        :return: a `PymeKey` object referring to the public key imported.
        """

    def importSecretKey(content):
        """Import the given secret key into our local keyring.

        If no key is found, GPGKeyNotFoundError is raised.  On the other
        hand, if more than one key is found, MoreThanOneGPGKeyFound is
        raised.

        :param content: secret key ASCII armored content (must be an ASCII
            string (it's up to the caller to encode or decode properly);
        :return: a `PymeKey` object referring to the secret key imported.
        """

    def generateKey(name):
        """Generate a new GPG key with the given name.

        Currently only passwordless, signo-only 1024-bit RSA keys are
        generated.

        :param name: unicode to be included in the key parameters, 'comment'
            and 'email' will be empty. Its content will be encoded to
            'utf-8' internally.
        :raise AssertionError: if the key generation is not exactly what
            we expect.

        :return: a `PymeKey` object for the just-generated secret key.
        """

    def encryptContent(content, key):
        """Encrypt the given content for the given key.

        content must be a traditional string. It's up to the caller to
        encode or decode properly.

        :param content: the Unicode content to be encrypted.
        :param key: the `IPymeKey` to encrypt the content for.

        :return: the encrypted content or None if failed.
        """

    def signContent(content, key, password="", mode=None):
        """Signs content with a given GPG key.

        :param content: the content to sign.
        :param key: the `IPymeKey` to use when signing the content.
        :param password: optional password to the key identified by
            key_fingerprint, the default value is '',
        :param mode: optional type of GPG signature to produce, the
            default mode is gpgme.SIG_MODE_CLEAR (clearsigned signatures)

        :return: The ASCII-armored signature for the content.
        """

    def retrieveKey(fingerprint):
        """Retrieve the key information from the local keyring.

        If the key with the given fingerprint is not present in the local
        keyring, first import it from the key server into the local keyring.

        :param fingerprint: The key fingerprint, which must be an hexadecimal
            string.
        :raise GPGKeyNotFoundError: if the key is not found neither in the
            local keyring nor in the key server.
        :return: a `PymeKey`object containing the key information.
        """

    def retrieveActiveKey(fingerprint):
        """Retrieve key information, raise errors if the key is not active.

        Exactly like `retrieveKey` except raises errors if the key is expired
        or has been revoked.

        :param fingerprint: The key fingerprint, which must be an hexadecimal
            string.
        :raise GPGKeyNotFoundError: if the key is not found neither in the
            local keyring nor in the key server.
        :return: a `PymeKey`object containing the key information.
        """

    def submitKey(content):
        """Submit an ASCII-armored public key export to the keyserver.

        It issues a POST at /pks/add on the keyserver specified in the
        configuration.

        :param content: The exported public key, as a byte string.
        :raise GPGUploadFailure: if the keyserver could not be reached.
        :raise AssertionError: if the POST request failed.
        """

    def uploadPublicKey(fingerprint):
        """Upload the specified public key to a keyserver.

        Use `retrieveKey` to get the public key content and upload an
        ASCII-armored export chunk.

        :param fingerprint: The key fingerprint, which must be an hexadecimal
            string.
        :raise GPGUploadFailure: if the keyserver could not be reached.
        :raise AssertionError: if the POST request failed.
        """

    def localKeys(filter=None, secret=False):
        """Return an iterator of all keys locally known about.

        :param filter: optional string used to filter the results. By default
            gpgme tries to match '<name> [comment] [email]', the full
            fingerprint or the key ID (fingerprint last 8 digits);
        :param secret: optional boolean, restrict the domain to secret or
            public keys available in the keyring. Defaults to False.

        :return: a `PymeKey` generator with the matching keys.
        """

    def resetLocalState():
        """Reset the local state.

        Resets OpenPGP keyrings and trust database.
        """
        # FIXME RBC: this should be a zope test cleanup thing per SteveA.


class IPymeSignature(Interface):
    """pyME signature container."""

    fingerprint = Attribute("Signer Fingerprint.")
    plain_data = Attribute("Plain Signed Text.")
    timestamp = Attribute("The time at which the message was signed.")


class IPymeKey(Interface):
    """pyME key model."""

    fingerprint = Attribute("Key Fingerprint")
    key = Attribute("Underlying GpgmeKey object")
    algorithm = Attribute("Key Algorithm")
    revoked = Attribute("Key Revoked")
    expired = Attribute("Key Expired")
    secret = Attribute("Whether the key is secret of not.")
    keysize = Attribute("Key Size")
    keyid = Attribute("Pseudo Key ID, composed by last fingerprint 8 digits ")
    uids = Attribute("List of user IDs associated with this key")
    emails = Attribute(
        "List containing only well formed and non-revoked emails"
    )
    displayname = Attribute("Key displayname: <size><type>/<keyid>")
    owner_trust = Attribute("The owner trust")

    can_encrypt = Attribute("Whether the key can be used for encrypting")
    can_sign = Attribute("Whether the key can be used for signing")
    can_certify = Attribute("Whether the key can be used for certification")
    can_authenticate = Attribute(
        "Whether the key can be used for authentication"
    )

    def export(secret_passphrase=""):
        """Export the context key in ASCII-armored mode.

        Both public and secret keys are supported, although secret keys are
        exported by calling `gpg` process while public ones use the native
        gpgme API.

        :param secret_passphrase: The passphrase, if exporting a secret key.
        :return: a string containing the exported key.
        """

    def matches(fingerprint):
        """Return True if and only if this fingerprint matches this key."""


class IPymeUserId(Interface):
    """pyME user ID"""

    revoked = Attribute("True if the user ID has been revoked")
    invalid = Attribute("True if the user ID is invalid")
    validity = Attribute(
        """A measure of the validity of the user ID,
                         based on owner trust values and signatures."""
    )
    uid = Attribute("A string identifying this user ID")
    name = Attribute("The name portion of this user ID")
    email = Attribute("The email portion of this user ID")
    comment = Attribute("The comment portion of this user ID")
