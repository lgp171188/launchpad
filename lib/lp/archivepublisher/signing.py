# Copyright 2012-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The processing of Signing tarballs.

UEFI Secure Boot requires boot loader images to be signed, and we want to
have signed images in the archive so that they can be used for upgrades.
This cannot be done on the build daemons because they are insufficiently
secure to hold signing keys, so we sign them as a custom upload instead.
"""

__all__ = [
    "SigningUpload",
    "UefiUpload",
]

import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import textwrap
from datetime import datetime, timezone
from functools import partial

from zope.component import getUtility

from lp.archivepublisher.config import getPubConfig
from lp.archivepublisher.customupload import CustomUpload
from lp.registry.interfaces.distroseries import IDistroSeriesSet
from lp.services.features import getFeatureFlag
from lp.services.osutils import remove_if_exists
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import IArchiveSigningKeySet
from lp.soyuz.interfaces.queue import CustomUploadError

PUBLISHER_USES_SIGNING_SERVICE = "archivepublisher.signing_service.enabled"
PUBLISHER_SIGNING_SERVICE_INJECTS_KEYS = (
    "archivepublisher.signing_service.injection.enabled"
)


class SigningUploadPackError(CustomUploadError):
    def __init__(self, tarfile_path, exc):
        message = "Problem building tarball '%s': %s" % (tarfile_path, exc)
        CustomUploadError.__init__(self, message)


class NoSigningKeyError(Exception):
    pass


class SigningServiceError(Exception):
    pass


class SigningKeyConflict(Exception):
    pass


class SigningUpload(CustomUpload):
    """Signing custom upload.

    The filename must be of the form:

        <PACKAGE>_<VERSION>_<ARCH>.tar.gz

    where:

      * PACKAGE: source package of the contents;
      * VERSION: encoded version;
      * ARCH: targeted architecture tag (e.g. 'amd64').

    The contents are extracted in the archive in the following path:

        <ARCHIVE>/dists/<SUITE>/main/signed/<PACKAGE>-<ARCH>/<VERSION>

    A 'current' symbolic link points to the most recent version.  The
    tarfile must contain at least one file matching the wildcard *.efi, and
    any such files are signed using the archive's UEFI signing key.

    Signing keys may be installed in the "signingroot" directory specified in
    publisher configuration.  In this directory, the private key is
    "uefi.key" and the certificate is "uefi.crt".

    This class is already prepared to use signing service. There are
    basically two places interacting with it:
        - findSigningHandlers(), that provides a handler to call signing
        service to sign each file (together with a fallback handler,
        that signs the file locally).

        - copyPublishedPublicKeys(), that accepts both ways of saving public
        keys: by copying from local file system (old way) or saving the
        public key stored at signing service (new way).
    """

    custom_type = "signing"

    dists_directory = "signed"

    @staticmethod
    def parsePath(tarfile_path):
        tarfile_base = os.path.basename(tarfile_path)
        bits = tarfile_base.split("_")
        if len(bits) != 3:
            raise ValueError("%s is not TYPE_VERSION_ARCH" % tarfile_base)
        return bits[0], bits[1], bits[2].split(".")[0]

    def setComponents(self, tarfile_path):
        self.package, self.version, self.arch = self.parsePath(tarfile_path)

    def getSeriesPath(self, pubconf, key_name, archive, signing_for):
        """Find the key path for a given series.

        Will iterate the series list backwards until either one exists,
        or we reach the key at the filesystem root.
        """
        found = False
        for series in archive.distribution.series:
            if series.name == signing_for:
                found = True
            if found:
                path = os.path.join(pubconf.signingroot, series.name, key_name)
                if os.path.exists(path):
                    return path
        # If we have exhausted all available series, return the root
        return os.path.join(pubconf.signingroot, key_name)

    def setTargetDirectory(self, archive, tarfile_path, suite):
        self.archive = archive

        if suite:
            self.distro_series, _ = getUtility(IDistroSeriesSet).fromSuite(
                self.archive.distribution, suite
            )
        else:
            self.distro_series = None

        pubconf = getPubConfig(archive)
        if pubconf.signingroot is None:
            if self.logger is not None:
                self.logger.warning(
                    "No signing root configured for this archive"
                )
            self.uefi_key = None
            self.uefi_cert = None
            self.kmod_pem = None
            self.kmod_x509 = None
            self.opal_pem = None
            self.opal_x509 = None
            self.sipl_pem = None
            self.sipl_x509 = None
            self.fit_key = None
            self.fit_cert = None
            self.autokey = False
        else:
            signing_for = self.distro_series.name if self.distro_series else ""
            self.uefi_key = self.getSeriesPath(
                pubconf, "uefi.key", archive, signing_for
            )
            self.uefi_cert = self.getSeriesPath(
                pubconf, "uefi.crt", archive, signing_for
            )
            self.kmod_pem = self.getSeriesPath(
                pubconf, "kmod.pem", archive, signing_for
            )
            self.kmod_x509 = self.getSeriesPath(
                pubconf, "kmod.x509", archive, signing_for
            )
            self.opal_pem = self.getSeriesPath(
                pubconf, "opal.pem", archive, signing_for
            )
            self.opal_x509 = self.getSeriesPath(
                pubconf, "opal.x509", archive, signing_for
            )
            self.sipl_pem = self.getSeriesPath(
                pubconf, "sipl.pem", archive, signing_for
            )
            self.sipl_x509 = self.getSeriesPath(
                pubconf, "sipl.x509", archive, signing_for
            )
            # Note: the signature tool allows a collection of keys and takes
            #       a directory name with all valid keys.  Avoid mixing the
            #       other signing types' keys with the fit keys.
            self.fit_key = self.getSeriesPath(
                pubconf, os.path.join("fit", "fit.key"), archive, signing_for
            )
            self.fit_cert = self.getSeriesPath(
                pubconf, os.path.join("fit", "fit.crt"), archive, signing_for
            )
            self.autokey = pubconf.signingautokey

        self.setComponents(tarfile_path)

        dists_signed = os.path.join(
            pubconf.archiveroot, "dists", suite, "main", self.dists_directory
        )
        self.targetdir = os.path.join(
            dists_signed, "%s-%s" % (self.package, self.arch)
        )
        self.archiveroot = pubconf.archiveroot
        self.temproot = pubconf.temproot

        self.public_keys = {}

    def publishPublicKey(self, key, content=None):
        """Record this key as having been used in this upload.

        :param key: Key file name
        :param content: Key file content (if None, try to read it from local
            filesystem)
        """
        if content is not None:
            self.public_keys[key] = content
        elif key not in self.public_keys:
            # Ensure we only emit files which are world-readable.
            if stat.S_IMODE(os.stat(key).st_mode) & stat.S_IROTH:
                with open(key, "rb") as f:
                    self.public_keys[key] = f.read()
            else:
                if self.logger is not None:
                    self.logger.warning(
                        "%s: public key not world readable" % key
                    )

    def copyPublishedPublicKeys(self):
        """Copy out published keys into the custom upload."""
        keydir = os.path.join(self.tmpdir, self.version, "control")
        if not os.path.exists(keydir):
            os.makedirs(keydir)
        for filename, content in self.public_keys.items():
            file_path = os.path.join(keydir, os.path.basename(filename))
            with open(file_path, "wb") as fd:
                fd.write(content)

    def setSigningOptions(self):
        """Find and extract raw-signing options from the tarball."""
        self.signing_options = {}

        # Look for an options file in the top level control directory.
        options_file = os.path.join(
            self.tmpdir, self.version, "control", "options"
        )
        if not os.path.exists(options_file):
            return

        with open(options_file) as options_fd:
            for option in options_fd:
                self.signing_options[option.strip()] = True

    @classmethod
    def getSeriesKey(cls, tarfile_path):
        try:
            package, _, arch = cls.parsePath(tarfile_path)
            return package, arch
        except ValueError:
            return None

    def callLog(self, description, cmdl):
        status = subprocess.call(cmdl)
        if status != 0:
            # Just log this rather than failing, since custom upload errors
            # tend to make the publisher rather upset.
            if self.logger is not None:
                self.logger.warning(
                    "%s Failed (cmd='%s')" % (description, " ".join(cmdl))
                )
        return status

    def findSigningHandlers(self):
        """Find all the signable files in an extracted tarball."""
        use_signing_service = bool(
            getFeatureFlag(PUBLISHER_USES_SIGNING_SERVICE)
        )

        fallback_handlers = {
            SigningKeyType.UEFI: self.signUefi,
            SigningKeyType.KMOD: self.signKmod,
            SigningKeyType.OPAL: self.signOpal,
            SigningKeyType.SIPL: self.signSipl,
            SigningKeyType.FIT: self.signFit,
        }

        for dirpath, _, filenames in os.walk(self.tmpdir):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                if filename.endswith(".efi"):
                    key_type = SigningKeyType.UEFI
                elif filename.endswith(".ko"):
                    key_type = SigningKeyType.KMOD
                elif filename.endswith(".opal"):
                    key_type = SigningKeyType.OPAL
                elif filename.endswith(".sipl"):
                    key_type = SigningKeyType.SIPL
                elif filename.endswith(".fit"):
                    key_type = SigningKeyType.FIT
                elif filename.endswith(".cv2-kernel"):
                    key_type = SigningKeyType.CV2_KERNEL
                elif filename.endswith(".android-kernel"):
                    key_type = SigningKeyType.ANDROID_KERNEL
                else:
                    continue

                if use_signing_service:
                    key = getUtility(IArchiveSigningKeySet).getSigningKey(
                        key_type, self.archive, self.distro_series
                    )
                    handler = partial(
                        self.signUsingSigningService, key_type, key
                    )
                    if key_type in fallback_handlers:
                        fallback_handler = partial(
                            self.signUsingLocalKey,
                            key_type,
                            fallback_handlers.get(key_type),
                        )
                    else:
                        fallback_handler = None
                    yield file_path, handler, fallback_handler
                else:
                    yield file_path, fallback_handlers.get(key_type), None

    def signUsingLocalKey(self, key_type, handler, filename):
        """Sign the given filename using using handler if the local
        key files exists. If the local key files does not exist, raises
        IOError.

        Note that this method should only be used as a fallback to signing
        service, since it will not try to generate local keys.

        :param key_type: One of the SigningKeyType items.
        :param handler: One of the local signing handlers (self.signUefi,
                        self.signKmod, etc).
        :param filename: The filename to be signed.
        """

        if not self.keyFilesExist(key_type):
            raise OSError(
                "Could not fallback to local signing keys: the key files "
                "were not found."
            )
        return handler(filename)

    def keyFilesExist(self, key_type):
        """Checks if all needed key files exists in the local filesystem
        for the given key type.
        """
        fallback_keys = {
            SigningKeyType.UEFI: [self.uefi_cert, self.uefi_key],
            SigningKeyType.KMOD: [self.kmod_pem, self.kmod_x509],
            SigningKeyType.OPAL: [self.opal_pem, self.opal_x509],
            SigningKeyType.SIPL: [self.sipl_pem, self.sipl_x509],
            SigningKeyType.FIT: [self.fit_cert, self.fit_key],
        }
        # If we are missing local key files, do not proceed.
        key_files = [i for i in fallback_keys.get(key_type, []) if i]
        return all(os.path.exists(key_file) for key_file in key_files)

    def signUsingSigningService(self, key_type, signing_key, filename):
        """Sign the given filename using a certain key hosted on signing
        service, writes the signed content back to the filesystem and
        publishes the public key to self.public_keys.

        If the given key is None and self.autokey is set to True, this method
        generates a key on signing service and associates it with the current
        archive.

        :param key_type: One of the SigningKeyType enum items
        :param signing_key: The SigningKey to be used (or None,
                            to autogenerate a key if possible).
        :param filename: The filename to be signed.
        :return: Boolean. True if signed, or raises SigningServiceError
                 on failure.
        """
        if signing_key is None:
            if not self.autokey:
                raise NoSigningKeyError("No signing key for %s" % filename)
            description = "%s key for %s" % (
                key_type.name,
                self.archive.reference,
            )
            try:
                signing_key = (
                    getUtility(IArchiveSigningKeySet)
                    .generate(key_type, description, self.archive)
                    .signing_key
                )
            except Exception as e:
                if self.logger:
                    self.logger.exception(
                        "Error generating signing key for %s: %s %s"
                        % (self.archive.reference, e.__class__.__name__, e)
                    )
                raise SigningServiceError(
                    "Could not generate key %s: %s" % (key_type, e)
                )

        with open(filename, "rb") as fd:
            content = fd.read()

        try:
            signed_content = signing_key.sign(
                content, message_name=os.path.basename(filename)
            )
        except Exception as e:
            if self.logger:
                self.logger.exception(
                    "Error signing %s on signing service: %s %s"
                    % (filename, e.__class__.__name__, e)
                )
            raise SigningServiceError(
                "Could not sign message with key %s: %s" % (signing_key, e)
            )

        if key_type in (SigningKeyType.UEFI, SigningKeyType.FIT):
            file_suffix = ".signed"
            public_key_suffix = ".crt"
        else:
            file_suffix = ".sig"
            if key_type == SigningKeyType.CV2_KERNEL:
                public_key_suffix = ".pub"
            else:
                public_key_suffix = ".x509"

        signed_filename = filename + file_suffix
        public_key_filename = (
            key_type.name.lower().replace("_", "-") + public_key_suffix
        )

        with open(signed_filename, "wb") as fd:
            fd.write(signed_content)

        self.publishPublicKey(public_key_filename, signing_key.public_key)
        return True

    def getKeys(self, which, generate, *keynames):
        """Validate and return the uefi key and cert for encryption."""
        if self.autokey:
            for keyfile in keynames:
                if keyfile and not os.path.exists(keyfile):
                    generate()
                    break

        valid = True
        for keyfile in keynames:
            if keyfile and not os.access(keyfile, os.R_OK):
                if self.logger is not None:
                    self.logger.warning(
                        "%s key %s not readable" % (which, keyfile)
                    )
                valid = False

        if not valid:
            return [None for k in keynames]
        return keynames

    def injectIntoSigningService(
        self, key_type, private_key_file, public_key_file
    ):
        """Injects the given key pair into signing service for current
        archive.

        Note that this injection should only be used for freshly
        autogenerated keys, always injecting the key for the archive in
        general (not setting earliest_distro_series).
        """
        if key_type not in SigningKeyType:
            raise ValueError("%s is not a valid key type to inject" % key_type)

        feature_flag = (
            getFeatureFlag(PUBLISHER_SIGNING_SERVICE_INJECTS_KEYS) or ""
        )
        key_types_to_inject = [i.strip() for i in feature_flag.split()]

        if key_type.name not in key_types_to_inject:
            if self.logger:
                self.logger.info(
                    "Skipping injection for key type %s: not in %s",
                    key_type,
                    key_types_to_inject,
                )
            return

        key_set = getUtility(IArchiveSigningKeySet)
        current_key = key_set.get(
            key_type, self.archive, None, exact_match=True
        )
        if current_key is not None:
            self.logger.info(
                "Skipping injection for key type %s: archive "
                "already has a key on lp-signing.",
                key_type,
            )
            raise SigningKeyConflict(
                "Archive %s already has a signing key type %s on lp-signing."
                % (self.archive.reference, key_type)
            )

        if self.logger:
            self.logger.info(
                "Injecting key_type %s for archive %s into signing service",
                key_type,
                self.archive.name,
            )

        with open(private_key_file, "rb") as fd:
            private_key = fd.read()
        with open(public_key_file, "rb") as fd:
            public_key = fd.read()

        now = datetime.now().replace(tzinfo=timezone.utc)
        description = "%s key for %s" % (key_type.name, self.archive.reference)
        key_set.inject(
            key_type,
            private_key,
            public_key,
            description,
            now,
            self.archive,
            earliest_distro_series=None,
        )

    def generateKeyCommonName(self, owner, archive, suffix=""):
        # PPA <owner> <archive> <suffix>
        # truncate <owner> <archive> to ensure the overall form is shorter
        # than 64 characters but the suffix is maintained
        if suffix:
            suffix = " " + suffix
        common_name = "PPA %s %s" % (owner, archive)
        return common_name[0 : 64 - len(suffix)] + suffix

    def generateKeyCrtPair(self, key_type, key_filename, cert_filename):
        """Generate new Key/Crt key pairs."""
        directory = os.path.dirname(key_filename)
        if not os.path.exists(directory):
            os.makedirs(directory)

        common_name = self.generateKeyCommonName(
            self.archive.owner.name, self.archive.name, key_type
        )
        subject = "/CN=" + common_name + "/"

        old_mask = os.umask(0o077)
        try:
            new_key_cmd = [
                "openssl",
                "req",
                "-new",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-subj",
                subject,
                "-keyout",
                key_filename,
                "-out",
                cert_filename,
                "-days",
                "3650",
                "-nodes",
                "-sha256",
            ]
            self.callLog(key_type + " keygen", new_key_cmd)
        finally:
            os.umask(old_mask)

        if os.path.exists(cert_filename):
            os.chmod(cert_filename, 0o644)

            signing_key_type = getattr(SigningKeyType, key_type.upper())
            try:
                self.injectIntoSigningService(
                    signing_key_type, key_filename, cert_filename
                )
            except SigningKeyConflict:
                os.unlink(key_filename)
                os.unlink(cert_filename)
                raise

    def generateUefiKeys(self):
        """Generate new UEFI Keys for this archive."""
        self.generateKeyCrtPair("UEFI", self.uefi_key, self.uefi_cert)

    def signUefi(self, image):
        """Attempt to sign an image."""
        remove_if_exists("%s.signed" % image)
        (key, cert) = self.getKeys(
            "UEFI", self.generateUefiKeys, self.uefi_key, self.uefi_cert
        )
        if not key or not cert:
            return
        self.publishPublicKey(cert)
        cmdl = ["sbsign", "--key", key, "--cert", cert, image]
        return self.callLog("UEFI signing", cmdl) == 0

    openssl_config_base = textwrap.dedent(
        """\
        [ req ]
        default_bits = 4096
        distinguished_name = req_distinguished_name
        prompt = no
        string_mask = utf8only
        x509_extensions = myexts

        [ req_distinguished_name ]
        CN = {common_name}

        [ myexts ]
        basicConstraints=critical,CA:FALSE
        keyUsage=digitalSignature
        subjectKeyIdentifier=hash
        authorityKeyIdentifier=keyid
        """
    )

    openssl_config_opal = "# OPAL OpenSSL config\n" + openssl_config_base

    openssl_config_kmod = (
        "# KMOD OpenSSL config\n"
        + openssl_config_base
        + textwrap.dedent(
            """
        # codeSigning:  specifies that this key is used to sign code.
        # 1.3.6.1.4.1.2312.16.1.2:  defines this key as used for
        #   module signing only. See https://lkml.org/lkml/2015/8/26/741.
        extendedKeyUsage        = codeSigning,1.3.6.1.4.1.2312.16.1.2
        """
        )
    )

    openssl_config_sipl = "# SIPL OpenSSL config\n" + openssl_config_base

    def generateOpensslConfig(self, key_type, genkey_tmpl):
        # Truncate name to 64 character maximum.
        common_name = self.generateKeyCommonName(
            self.archive.owner.name, self.archive.name, key_type
        )

        return genkey_tmpl.format(common_name=common_name)

    def generatePemX509Pair(
        self, key_type, genkey_text, pem_filename, x509_filename
    ):
        """Generate new pem/x509 key pairs."""
        directory = os.path.dirname(pem_filename)
        if not os.path.exists(directory):
            os.makedirs(directory)

        old_mask = os.umask(0o077)
        try:
            with tempfile.NamedTemporaryFile(suffix=".keygen") as tf:
                tf.write(genkey_text.encode("UTF-8"))

                # Close out the underlying file so we know it is complete.
                tf.file.close()

                new_key_cmd = [
                    "openssl",
                    "req",
                    "-new",
                    "-nodes",
                    "-utf8",
                    "-sha512",
                    "-days",
                    "3650",
                    "-batch",
                    "-x509",
                    "-config",
                    tf.name,
                    "-outform",
                    "PEM",
                    "-out",
                    pem_filename,
                    "-keyout",
                    pem_filename,
                ]
                if self.callLog(key_type + " keygen key", new_key_cmd) == 0:
                    new_x509_cmd = [
                        "openssl",
                        "x509",
                        "-in",
                        pem_filename,
                        "-outform",
                        "DER",
                        "-out",
                        x509_filename,
                    ]
                    if (
                        self.callLog(key_type + " keygen cert", new_x509_cmd)
                        != 0
                    ):
                        os.unlink(pem_filename)
        finally:
            os.umask(old_mask)

        if os.path.exists(x509_filename):
            os.chmod(x509_filename, 0o644)

            signing_key_type = getattr(SigningKeyType, key_type.upper())
            try:
                self.injectIntoSigningService(
                    signing_key_type, pem_filename, x509_filename
                )
            except SigningKeyConflict:
                os.unlink(pem_filename)
                os.unlink(x509_filename)
                raise

    def generateKmodKeys(self):
        """Generate new Kernel Signing Keys for this archive."""
        config = self.generateOpensslConfig("Kmod", self.openssl_config_kmod)
        self.generatePemX509Pair("Kmod", config, self.kmod_pem, self.kmod_x509)

    def signKmod(self, image):
        """Attempt to sign a kernel module."""
        remove_if_exists("%s.sig" % image)
        (pem, cert) = self.getKeys(
            "Kernel Module",
            self.generateKmodKeys,
            self.kmod_pem,
            self.kmod_x509,
        )
        if not pem or not cert:
            return
        self.publishPublicKey(cert)
        cmdl = ["kmodsign", "-D", "sha512", pem, cert, image, image + ".sig"]
        return self.callLog("Kmod signing", cmdl) == 0

    def generateOpalKeys(self):
        """Generate new Opal Signing Keys for this archive."""
        config = self.generateOpensslConfig("Opal", self.openssl_config_opal)
        self.generatePemX509Pair("Opal", config, self.opal_pem, self.opal_x509)

    def signOpal(self, image):
        """Attempt to sign a kernel image for Opal."""
        remove_if_exists("%s.sig" % image)
        (pem, cert) = self.getKeys(
            "Opal Kernel", self.generateOpalKeys, self.opal_pem, self.opal_x509
        )
        if not pem or not cert:
            return
        self.publishPublicKey(cert)
        cmdl = ["kmodsign", "-D", "sha512", pem, cert, image, image + ".sig"]
        return self.callLog("Opal signing", cmdl) == 0

    def generateSiplKeys(self):
        """Generate new Sipl Signing Keys for this archive."""
        config = self.generateOpensslConfig("SIPL", self.openssl_config_sipl)
        self.generatePemX509Pair("SIPL", config, self.sipl_pem, self.sipl_x509)

    def signSipl(self, image):
        """Attempt to sign a kernel image for Sipl."""
        remove_if_exists("%s.sig" % image)
        (pem, cert) = self.getKeys(
            "SIPL Kernel", self.generateSiplKeys, self.sipl_pem, self.sipl_x509
        )
        if not pem or not cert:
            return
        self.publishPublicKey(cert)
        cmdl = ["kmodsign", "-D", "sha512", pem, cert, image, image + ".sig"]
        return self.callLog("SIPL signing", cmdl) == 0

    def generateFitKeys(self):
        """Generate new FIT Keys for this archive."""
        self.generateKeyCrtPair("FIT", self.fit_key, self.fit_cert)

    def signFit(self, image):
        """Attempt to sign an image."""
        image_signed = "%s.signed" % image
        remove_if_exists(image_signed)
        (key, cert) = self.getKeys(
            "FIT", self.generateFitKeys, self.fit_key, self.fit_cert
        )
        if not key or not cert:
            return
        self.publishPublicKey(cert)
        # Make a copy of the image as mkimage signs in place and in
        # signed-only mode we will remove the original file.
        shutil.copy(image, image_signed)
        cmdl = [
            "mkimage",
            "-F",
            "-k",
            os.path.dirname(key),
            "-r",
            image_signed,
        ]
        return self.callLog("FIT signing", cmdl) == 0

    def convertToTarball(self):
        """Convert unpacked output to signing tarball."""
        tarfilename = os.path.join(self.tmpdir, "signed.tar.gz")
        versiondir = os.path.join(self.tmpdir, self.version)

        try:
            with tarfile.open(tarfilename, "w:gz") as tarball:
                tarball.add(versiondir, arcname=self.version)
        except tarfile.TarError as exc:
            raise SigningUploadPackError(tarfilename, exc)

        # Clean out the original tree and move the signing tarball in.
        try:
            shutil.rmtree(versiondir)
            os.mkdir(versiondir)
            os.rename(tarfilename, os.path.join(versiondir, "signed.tar.gz"))
        except OSError as exc:
            raise SigningUploadPackError(tarfilename, exc)

    def extract(self):
        """Copy the custom upload to a temporary directory, and sign it.

        No actual extraction is required.
        """
        super().extract()
        self.setSigningOptions()
        for filename, handler, fallback_handler in self.findSigningHandlers():
            try:
                was_signed = handler(filename)
            except (NoSigningKeyError, SigningServiceError) as e:
                if fallback_handler is not None and self.logger:
                    self.logger.warning(
                        "Signing service will try to fallback to local key. "
                        "Reason: %s (%s)" % (e.__class__.__name__, e)
                    )
                was_signed = False
            if not was_signed and fallback_handler is not None:
                was_signed = fallback_handler(filename)
            if was_signed and "signed-only" in self.signing_options:
                os.unlink(filename)

        # Copy out the public keys where they were used.
        self.copyPublishedPublicKeys()

        # If tarball output is requested, tar up the results.
        if "tarball" in self.signing_options:
            self.convertToTarball()

    def installFiles(self, archive, suite):
        """After installation hash and sign the installed result."""
        # Avoid circular import.
        from lp.archivepublisher.publishing import DirectoryHash

        super().installFiles(archive, suite)

        versiondir = os.path.join(self.targetdir, self.version)
        with DirectoryHash(versiondir, self.temproot) as hasher:
            hasher.add_dir(versiondir)
        for checksum_path in hasher.checksum_paths:
            if self.shouldSign(checksum_path):
                self.sign(archive, suite, checksum_path)

    def shouldInstall(self, filename):
        return filename.startswith("%s/" % self.version)

    def shouldSign(self, filename):
        return filename.endswith("SUMS")


class UefiUpload(SigningUpload):
    """Legacy UEFI Signing custom upload.

    Provides backwards compatibility UEFI signing uploads. Existing
    packages use the raw-uefi custom upload and expect the results
    to be published to dists/*/uefi.  These are a functional subset of
    raw-signing custom uploads differing only in where they are published
    in the archive.

    We expect to be able to remove this upload type once all existing
    packages are converted to the new form and location.
    """

    custom_type = "uefi"
    dists_directory = "uefi"
