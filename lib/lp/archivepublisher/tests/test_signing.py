# Copyright 2012-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test UEFI custom uploads."""

import os
import re
import shutil
import stat
import tarfile
from datetime import datetime, timezone
from unittest.mock import call

from fixtures import MockPatch, MonkeyPatch
from testtools.matchers import (
    Contains,
    Equals,
    FileContains,
    Matcher,
    MatchesAll,
    MatchesDict,
    MatchesStructure,
    Mismatch,
    Not,
    StartsWith,
)
from testtools.twistedsupport import AsynchronousDeferredRunTest
from twisted.internet import defer
from zope.component import getUtility

from lp.archivepublisher.config import getPubConfig
from lp.archivepublisher.customupload import (
    CustomUploadAlreadyExists,
    CustomUploadBadUmask,
)
from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    IArchiveGPGSigningKey,
)
from lp.archivepublisher.interfaces.publisherconfig import IPublisherConfigSet
from lp.archivepublisher.signing import (
    PUBLISHER_SIGNING_SERVICE_INJECTS_KEYS,
    PUBLISHER_USES_SIGNING_SERVICE,
    SigningKeyConflict,
    SigningUpload,
    UefiUpload,
)
from lp.archivepublisher.tests.test_run_parts import RunPartsMixin
from lp.services.features.testing import FeatureFixture
from lp.services.log.logger import BufferLogger
from lp.services.osutils import write_file
from lp.services.signing.enums import SigningKeyType, SigningMode
from lp.services.signing.tests.helpers import SigningServiceClientFixture
from lp.services.tarfile_helpers import LaunchpadWriteTarFile
from lp.soyuz.enums import ArchivePurpose
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.fakemethod import FakeMethod
from lp.testing.gpgkeys import gpgkeysdir
from lp.testing.keyserver import InProcessKeyServerFixture
from lp.testing.layers import ZopelessDatabaseLayer


class SignedMatches(Matcher):
    """Matches if a signing result directory is valid."""

    def __init__(self, expected):
        self.expected = expected

    def __str__(self):
        return "SignedMatches({})".format(self.expected)

    def match(self, base):
        content = []
        for root, dirs, files in os.walk(base):
            content.extend(
                [os.path.relpath(os.path.join(root, f), base) for f in files]
            )

        left_over = sorted(set(content) - set(self.expected))
        missing = sorted(set(self.expected) - set(content))
        if left_over != [] or missing != []:
            mismatch = ""
            if left_over:
                mismatch += " unexpected files: " + str(left_over)
            if missing:
                mismatch += " missing files: " + str(missing)
            return Mismatch("SignedMatches:" + mismatch)
        return None


class FakeMethodCallLog(FakeMethod):
    """Fake execution general commands."""

    def __init__(self, upload=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.upload = upload
        self.callers = {
            "UEFI signing": 0,
            "UEFI keygen": 0,
            "FIT signing": 0,
            "FIT keygen": 0,
            "Kmod signing": 0,
            "Kmod keygen key": 0,
            "Kmod keygen cert": 0,
            "Opal signing": 0,
            "Opal keygen key": 0,
            "Opal keygen cert": 0,
            "SIPL signing": 0,
            "SIPL keygen key": 0,
            "SIPL keygen cert": 0,
        }

    def __call__(self, *args, **kwargs):
        super().__call__(*args, **kwargs)

        description = args[0]
        cmdl = args[1]
        self.callers[description] += 1
        if description == "UEFI signing":
            filename = cmdl[-1]
            if filename.endswith(".efi"):
                write_file(filename + ".signed", b"")

        elif description == "UEFI keygen":
            write_file(self.upload.uefi_key, b"")
            write_file(self.upload.uefi_cert, b"")

        elif description == "FIT signing":
            filename = cmdl[-1]
            if filename.endswith(".fit"):
                write_file(filename + ".signed", b"")

        elif description == "FIT keygen":
            write_file(self.upload.fit_key, b"")
            write_file(self.upload.fit_cert, b"")

        elif description == "Kmod signing":
            filename = cmdl[-1]
            if filename.endswith(".ko.sig"):
                write_file(filename, b"")

        elif description == "Kmod keygen cert":
            write_file(self.upload.kmod_x509, b"")

        elif description == "Kmod keygen key":
            write_file(self.upload.kmod_pem, b"")

        elif description == "Opal signing":
            filename = cmdl[-1]
            if filename.endswith(".opal.sig"):
                write_file(filename, b"")

        elif description == "Opal keygen cert":
            write_file(self.upload.opal_x509, b"")

        elif description == "Opal keygen key":
            write_file(self.upload.opal_pem, b"")

        elif description == "SIPL signing":
            filename = cmdl[-1]
            if filename.endswith(".sipl.sig"):
                write_file(filename, b"")

        elif description == "SIPL keygen cert":
            write_file(self.upload.sipl_x509, b"")

        elif description == "SIPL keygen key":
            write_file(self.upload.sipl_pem, b"")

        else:
            raise AssertionError(
                "unknown command executed description=(%s) "
                "cmd=(%s)" % (description, " ".join(cmdl))
            )

        return 0

    def caller_count(self, caller):
        return self.callers.get(caller, 0)

    def caller_list(self):
        return [(caller, n) for (caller, n) in self.callers.items() if n != 0]


class TestSigningHelpers(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=30)

    def setUp(self):
        super().setUp()
        self.temp_dir = self.makeTemporaryDirectory()
        self.distro = self.factory.makeDistribution()
        db_pubconf = getUtility(IPublisherConfigSet).getByDistribution(
            self.distro
        )
        db_pubconf.root_dir = self.temp_dir
        self.archive = self.factory.makeArchive(
            distribution=self.distro, purpose=ArchivePurpose.PRIMARY
        )
        self.signing_dir = os.path.join(
            self.temp_dir, self.distro.name + "-signing"
        )
        self.distroseries = self.factory.makeDistroSeries(
            distribution=self.distro
        )
        self.suite = self.distroseries.name
        pubconf = getPubConfig(self.archive)
        if not os.path.exists(pubconf.temproot):
            os.makedirs(pubconf.temproot)
        # CustomUpload.installFiles requires a umask of 0o022.
        old_umask = os.umask(0o022)
        self.addCleanup(os.umask, old_umask)

    def setUpPPA(self):
        self.pushConfig(
            "personalpackagearchive",
            root=self.temp_dir,
            signing_keys_root=self.temp_dir,
        )
        owner = self.factory.makePerson(name="signing-owner")
        self.archive = self.factory.makeArchive(
            distribution=self.distro,
            owner=owner,
            name="testing",
            purpose=ArchivePurpose.PPA,
        )
        self.signing_dir = os.path.join(
            self.temp_dir, "signing", "signing-owner", "testing"
        )
        self.testcase_cn = "PPA signing-owner testing"
        pubconf = getPubConfig(self.archive)
        if not os.path.exists(pubconf.temproot):
            os.makedirs(pubconf.temproot)

    @defer.inlineCallbacks
    def setUpArchiveKey(self):
        yield self.useFixture(InProcessKeyServerFixture()).start()
        key_path = os.path.join(gpgkeysdir, "ppa-sample@canonical.com.sec")
        yield IArchiveGPGSigningKey(self.archive).setSigningKey(
            key_path, async_keyserver=True
        )

    def setUpUefiKeys(self, create=True, series=None):
        if not series:
            self.key = os.path.join(self.signing_dir, "uefi.key")
            self.cert = os.path.join(self.signing_dir, "uefi.crt")
        else:
            self.key = os.path.join(self.signing_dir, series.name, "uefi.key")
            self.cert = os.path.join(self.signing_dir, series.name, "uefi.crt")
        if create:
            write_file(self.key, b"")
            write_file(self.cert, b"")

    def setUpFitKeys(self, create=True):
        # We expect and need the fit keys to be in their own
        # directory as part of key protection for mkimage.
        self.fit_key = os.path.join(self.signing_dir, "fit", "fit.key")
        self.fit_cert = os.path.join(self.signing_dir, "fit", "fit.crt")
        if create:
            write_file(self.fit_key, b"")
            write_file(self.fit_cert, b"")

    def setUpKmodKeys(self, create=True):
        self.kmod_pem = os.path.join(self.signing_dir, "kmod.pem")
        self.kmod_x509 = os.path.join(self.signing_dir, "kmod.x509")
        if create:
            write_file(self.kmod_pem, b"")
            write_file(self.kmod_x509, b"")

    def setUpOpalKeys(self, create=True):
        self.opal_pem = os.path.join(self.signing_dir, "opal.pem")
        self.opal_x509 = os.path.join(self.signing_dir, "opal.x509")
        if create:
            write_file(self.opal_pem, b"")
            write_file(self.opal_x509, b"")

    def setUpSiplKeys(self, create=True):
        self.sipl_pem = os.path.join(self.signing_dir, "sipl.pem")
        self.sipl_x509 = os.path.join(self.signing_dir, "sipl.x509")
        if create:
            write_file(self.sipl_pem, b"")
            write_file(self.sipl_x509, b"")

    def openArchive(self, loader_type, version, arch):
        self.path = os.path.join(
            self.temp_dir, "%s_%s_%s.tar.gz" % (loader_type, version, arch)
        )
        self.buffer = open(self.path, "wb")
        self.tarfile = LaunchpadWriteTarFile(self.buffer)

    def getDistsPath(self):
        pubconf = getPubConfig(self.archive)
        return os.path.join(pubconf.archiveroot, "dists", self.suite, "main")


class TestLocalSigningUpload(RunPartsMixin, TestSigningHelpers):
    def getSignedPath(self, loader_type, arch):
        return os.path.join(
            self.getDistsPath(), "signed", "%s-%s" % (loader_type, arch)
        )

    def process_emulate(self):
        self.tarfile.close()
        self.buffer.close()
        upload = SigningUpload()
        # Under no circumstances is it safe to execute actual commands.
        self.fake_call = FakeMethod(result=0)
        upload.callLog = FakeMethodCallLog(upload=upload)
        self.useFixture(MonkeyPatch("subprocess.call", self.fake_call))
        upload.process(self.archive, self.path, self.suite)

        return upload

    def process(self):
        self.tarfile.close()
        self.buffer.close()
        upload = SigningUpload()
        upload.signUefi = FakeMethod()
        upload.signKmod = FakeMethod()
        upload.signOpal = FakeMethod()
        upload.signSipl = FakeMethod()
        upload.signFit = FakeMethod()
        # Under no circumstances is it safe to execute actual commands.
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload.process(self.archive, self.path, self.suite)
        self.assertEqual(0, fake_call.call_count)

        return upload

    def test_archive_copy(self):
        # If there is no key/cert configuration, processing succeeds but
        # nothing is signed.
        self.archive = self.factory.makeArchive(
            distribution=self.distro, purpose=ArchivePurpose.COPY
        )
        pubconf = getPubConfig(self.archive)
        if not os.path.exists(pubconf.temproot):
            os.makedirs(pubconf.temproot)
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.tarfile.add_file("1.0/empty.fit", b"")
        upload = self.process_emulate()
        self.assertContentEqual([], upload.callLog.caller_list())

    def test_archive_primary_no_keys(self):
        # If the configured key/cert are missing, processing succeeds but
        # nothing is signed.
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.tarfile.add_file("1.0/empty.fit", b"")
        upload = self.process_emulate()
        self.assertContentEqual([], upload.callLog.caller_list())

    def test_archive_primary_keys(self):
        # If the configured key/cert are missing, processing succeeds but
        # nothing is signed.
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.tarfile.add_file("1.0/empty.fit", b"")
        upload = self.process_emulate()
        expected_callers = [
            ("UEFI signing", 1),
            ("Kmod signing", 1),
        ]
        self.assertContentEqual(expected_callers, upload.callLog.caller_list())

    def test_PPA_creates_keys(self):
        # If the configured key/cert are missing, processing succeeds but
        # nothing is signed.
        self.setUpPPA()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.tarfile.add_file("1.0/empty.fit", b"")
        upload = self.process_emulate()
        expected_callers = [
            ("UEFI keygen", 1),
            ("Kmod keygen key", 1),
            ("Kmod keygen cert", 1),
            ("Opal keygen key", 1),
            ("Opal keygen cert", 1),
            ("SIPL keygen key", 1),
            ("SIPL keygen cert", 1),
            ("FIT keygen", 1),
            ("UEFI signing", 1),
            ("Kmod signing", 1),
            ("Opal signing", 1),
            ("SIPL signing", 1),
            ("FIT signing", 1),
        ]
        self.assertContentEqual(expected_callers, upload.callLog.caller_list())

    def test_common_name_plain(self):
        upload = SigningUpload()
        common_name = upload.generateKeyCommonName("testing-team", "ppa")
        self.assertEqual("PPA testing-team ppa", common_name)

    def test_common_name_suffix(self):
        upload = SigningUpload()
        common_name = upload.generateKeyCommonName(
            "testing-team", "ppa", "kmod"
        )
        self.assertEqual("PPA testing-team ppa kmod", common_name)

    def test_common_name_plain_just_short(self):
        upload = SigningUpload()
        common_name = upload.generateKeyCommonName("t" * 30, "p" * 29)
        expected_name = "PPA " + "t" * 30 + " " + "p" * 29
        self.assertEqual(expected_name, common_name)
        self.assertEqual(64, len(common_name))

    def test_common_name_suffix_just_short(self):
        upload = SigningUpload()
        common_name = upload.generateKeyCommonName("t" * 30, "p" * 24, "kmod")
        expected_name = "PPA " + "t" * 30 + " " + "p" * 24 + " kmod"
        self.assertEqual(expected_name, common_name)
        self.assertEqual(64, len(common_name))

    def test_common_name_plain_long(self):
        upload = SigningUpload()
        common_name = upload.generateKeyCommonName("t" * 40, "p" * 40)
        expected_name = "PPA " + "t" * 40 + " " + "p" * 19
        self.assertEqual(expected_name, common_name)
        self.assertEqual(64, len(common_name))

    def test_common_name_suffix_long(self):
        upload = SigningUpload()
        common_name = upload.generateKeyCommonName(
            "t" * 40, "p" * 40, "kmod-plus"
        )
        expected_name = "PPA " + "t" * 40 + " " + "p" * 9 + " kmod-plus"
        self.assertEqual(expected_name, common_name)
        self.assertEqual(64, len(common_name))

    def test_options_handling_none(self):
        # If the configured key/cert are missing, processing succeeds but
        # nothing is signed.
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"")
        upload = self.process_emulate()
        self.assertContentEqual([], upload.signing_options.keys())

    def test_options_handling_single(self):
        # If the configured key/cert are missing, processing succeeds but
        # nothing is signed.
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"first\n")
        upload = self.process_emulate()
        self.assertContentEqual(["first"], upload.signing_options.keys())

    def test_options_handling_multiple(self):
        # If the configured key/cert are missing, processing succeeds but
        # nothing is signed.
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"first\nsecond\n")
        upload = self.process_emulate()
        self.assertContentEqual(
            ["first", "second"], upload.signing_options.keys()
        )

    def test_options_none(self):
        # Specifying no options should leave us with an open tree.
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.setUpOpalKeys()
        self.setUpSiplKeys()
        self.setUpFitKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.tarfile.add_file("1.0/empty.fit", b"")
        self.process_emulate()
        self.assertThat(
            self.getSignedPath("test", "amd64"),
            SignedMatches(
                [
                    "1.0/SHA256SUMS",
                    "1.0/empty.efi",
                    "1.0/empty.efi.signed",
                    "1.0/control/uefi.crt",
                    "1.0/empty.ko",
                    "1.0/empty.ko.sig",
                    "1.0/control/kmod.x509",
                    "1.0/empty.opal",
                    "1.0/empty.opal.sig",
                    "1.0/control/opal.x509",
                    "1.0/empty.sipl",
                    "1.0/empty.sipl.sig",
                    "1.0/control/sipl.x509",
                    "1.0/empty.fit",
                    "1.0/empty.fit.signed",
                    "1.0/control/fit.crt",
                ]
            ),
        )

    def test_options_tarball(self):
        # Specifying the "tarball" option should create an tarball in
        # the tmpdir.
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.setUpOpalKeys()
        self.setUpSiplKeys()
        self.setUpFitKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"tarball")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.tarfile.add_file("1.0/empty.fit", b"")
        self.process_emulate()
        self.assertThat(
            self.getSignedPath("test", "amd64"),
            SignedMatches(
                [
                    "1.0/SHA256SUMS",
                    "1.0/signed.tar.gz",
                ]
            ),
        )
        tarfilename = os.path.join(
            self.getSignedPath("test", "amd64"), "1.0", "signed.tar.gz"
        )
        with tarfile.open(tarfilename) as tarball:
            self.assertContentEqual(
                [
                    "1.0",
                    "1.0/control",
                    "1.0/control/options",
                    "1.0/empty.efi",
                    "1.0/empty.efi.signed",
                    "1.0/control/uefi.crt",
                    "1.0/empty.ko",
                    "1.0/empty.ko.sig",
                    "1.0/control/kmod.x509",
                    "1.0/empty.opal",
                    "1.0/empty.opal.sig",
                    "1.0/control/opal.x509",
                    "1.0/empty.sipl",
                    "1.0/empty.sipl.sig",
                    "1.0/control/sipl.x509",
                    "1.0/empty.fit",
                    "1.0/empty.fit.signed",
                    "1.0/control/fit.crt",
                ],
                tarball.getnames(),
            )

    def test_options_signed_only(self):
        # Specifying the "signed-only" option should trigger removal of
        # the source files leaving signatures only.
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.setUpOpalKeys()
        self.setUpSiplKeys()
        self.setUpFitKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"signed-only")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.tarfile.add_file("1.0/empty.fit", b"")
        self.process_emulate()
        self.assertThat(
            self.getSignedPath("test", "amd64"),
            SignedMatches(
                [
                    "1.0/SHA256SUMS",
                    "1.0/control/options",
                    "1.0/empty.efi.signed",
                    "1.0/control/uefi.crt",
                    "1.0/empty.ko.sig",
                    "1.0/control/kmod.x509",
                    "1.0/empty.opal.sig",
                    "1.0/control/opal.x509",
                    "1.0/empty.sipl.sig",
                    "1.0/control/sipl.x509",
                    "1.0/empty.fit.signed",
                    "1.0/control/fit.crt",
                ]
            ),
        )

    def test_options_tarball_signed_only(self):
        # Specifying the "tarball" option should create an tarball in
        # the tmpdir.  Adding signed-only should trigger removal of the
        # original files.
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.setUpOpalKeys()
        self.setUpSiplKeys()
        self.setUpFitKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"tarball\nsigned-only")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.tarfile.add_file("1.0/empty.fit", b"")
        self.process_emulate()
        self.assertThat(
            self.getSignedPath("test", "amd64"),
            SignedMatches(
                [
                    "1.0/SHA256SUMS",
                    "1.0/signed.tar.gz",
                ]
            ),
        )
        tarfilename = os.path.join(
            self.getSignedPath("test", "amd64"), "1.0", "signed.tar.gz"
        )
        with tarfile.open(tarfilename) as tarball:
            self.assertContentEqual(
                [
                    "1.0",
                    "1.0/control",
                    "1.0/control/options",
                    "1.0/empty.efi.signed",
                    "1.0/control/uefi.crt",
                    "1.0/empty.ko.sig",
                    "1.0/control/kmod.x509",
                    "1.0/empty.opal.sig",
                    "1.0/control/opal.x509",
                    "1.0/empty.sipl.sig",
                    "1.0/control/sipl.x509",
                    "1.0/empty.fit.signed",
                    "1.0/control/fit.crt",
                ],
                tarball.getnames(),
            )

    def test_no_signed_files(self):
        # Tarballs containing no *.efi files are extracted without complaint.
        # Nothing is signed.
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.setUpOpalKeys()
        self.setUpSiplKeys()
        self.setUpFitKeys()
        self.openArchive("empty", "1.0", "amd64")
        self.tarfile.add_file("1.0/hello", b"world")
        upload = self.process()
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    self.getSignedPath("empty", "amd64"), "1.0", "hello"
                )
            )
        )
        self.assertEqual(0, upload.signUefi.call_count)
        self.assertEqual(0, upload.signKmod.call_count)
        self.assertEqual(0, upload.signOpal.call_count)
        self.assertEqual(0, upload.signSipl.call_count)
        self.assertEqual(0, upload.signFit.call_count)

    def test_already_exists(self):
        # If the target directory already exists, processing fails.
        self.setUpUefiKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        os.makedirs(os.path.join(self.getSignedPath("test", "amd64"), "1.0"))
        self.assertRaises(CustomUploadAlreadyExists, self.process)

    def test_bad_umask(self):
        # The umask must be 0o022 to avoid incorrect permissions.
        self.setUpUefiKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/dir/file.efi", b"foo")
        os.umask(0o002)  # cleanup already handled by setUp
        self.assertRaises(CustomUploadBadUmask, self.process)

    def test_correct_uefi_signing_command_executed(self):
        # Check that calling signUefi() will generate the expected command
        # when appropriate keys are present.
        self.setUpUefiKeys()
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.generateUefiKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signUefi("t.efi")
        self.assertEqual(1, fake_call.call_count)
        # Assert command form.
        args = fake_call.calls[0][0][0]
        expected_cmd = [
            "sbsign",
            "--key",
            self.key,
            "--cert",
            self.cert,
            "t.efi",
        ]
        self.assertEqual(expected_cmd, args)
        self.assertEqual(0, upload.generateUefiKeys.call_count)

    def test_correct_uefi_signing_command_executed_no_keys(self):
        # Check that calling signUefi() will generate no commands when
        # no keys are present.
        self.setUpUefiKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.generateUefiKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signUefi("t.efi")
        self.assertEqual(0, fake_call.call_count)
        self.assertEqual(0, upload.generateUefiKeys.call_count)

    def test_correct_uefi_keygen_command_executed(self):
        # Check that calling generateUefiKeys() will generate the
        # expected command.
        self.setUpPPA()
        self.setUpUefiKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.generateUefiKeys()
        self.assertEqual(1, fake_call.call_count)
        # Assert the actual command matches.
        args = fake_call.calls[0][0][0]
        expected_cmd = [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-subj",
            "/CN=" + self.testcase_cn + " UEFI/",
            "-keyout",
            self.key,
            "-out",
            self.cert,
            "-days",
            "3650",
            "-nodes",
            "-sha256",
        ]
        self.assertEqual(expected_cmd, args)

    def test_correct_fit_signing_command_executed(self):
        # Check that calling signFit() will generate the expected command
        # when appropriate keys are present.
        self.setUpFitKeys()
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        fake_copy = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("shutil.copy", fake_copy))
        upload = SigningUpload()
        upload.generateFitKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signFit("t.fit")
        # Confirm the copy was performed.
        self.assertEqual(1, fake_copy.call_count)
        args = fake_copy.calls[0][0]
        expected_copy = ("t.fit", "t.fit.signed")
        self.assertEqual(expected_copy, args)
        # Assert command form.
        args = fake_call.calls[0][0][0]
        expected_cmd = [
            "mkimage",
            "-F",
            "-k",
            os.path.dirname(self.fit_key),
            "-r",
            "t.fit.signed",
        ]
        self.assertEqual(expected_cmd, args)
        self.assertEqual(0, upload.generateFitKeys.call_count)

    def test_correct_fit_signing_command_executed_no_keys(self):
        # Check that calling signFit() will generate no commands when
        # no keys are present.
        self.setUpFitKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.generateFitKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signUefi("t.fit")
        self.assertEqual(0, fake_call.call_count)
        self.assertEqual(0, upload.generateFitKeys.call_count)

    def test_correct_fit_keygen_command_executed(self):
        # Check that calling generateFitKeys() will generate the
        # expected command.
        self.setUpPPA()
        self.setUpFitKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.generateFitKeys()
        self.assertEqual(1, fake_call.call_count)
        # Assert the actual command matches.
        args = fake_call.calls[0][0][0]
        expected_cmd = [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-subj",
            "/CN=" + self.testcase_cn + " FIT/",
            "-keyout",
            self.fit_key,
            "-out",
            self.fit_cert,
            "-days",
            "3650",
            "-nodes",
            "-sha256",
        ]
        self.assertEqual(expected_cmd, args)

    def test_correct_kmod_openssl_config(self):
        # Check that calling generateOpensslConfig() will return an appropriate
        # openssl configuration.
        self.setUpPPA()
        upload = SigningUpload()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        text = upload.generateOpensslConfig("Kmod", upload.openssl_config_kmod)

        id_re = re.compile(r"^# KMOD OpenSSL config\n")
        cn_re = re.compile(r"\bCN\s*=\s*" + self.testcase_cn + r"\s+Kmod")
        eku_re = re.compile(
            r"\bextendedKeyUsage\s*=\s*"
            r"codeSigning,1.3.6.1.4.1.2312.16.1.2\s*\b"
        )

        self.assertIn("[ req ]", text)
        self.assertIsNotNone(id_re.search(text))
        self.assertIsNotNone(cn_re.search(text))
        self.assertIsNotNone(eku_re.search(text))

    def test_correct_kmod_signing_command_executed(self):
        # Check that calling signKmod() will generate the expected command
        # when appropriate keys are present.
        self.setUpKmodKeys()
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.generateKmodKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signKmod("t.ko")
        self.assertEqual(1, fake_call.call_count)
        # Assert command form.
        args = fake_call.calls[0][0][0]
        expected_cmd = [
            "kmodsign",
            "-D",
            "sha512",
            self.kmod_pem,
            self.kmod_x509,
            "t.ko",
            "t.ko.sig",
        ]
        self.assertEqual(expected_cmd, args)
        self.assertEqual(0, upload.generateKmodKeys.call_count)

    def test_correct_kmod_signing_command_executed_no_keys(self):
        # Check that calling signKmod() will generate no commands when
        # no keys are present.
        self.setUpKmodKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.generateKmodKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signKmod("t.ko")
        self.assertEqual(0, fake_call.call_count)
        self.assertEqual(0, upload.generateKmodKeys.call_count)

    def test_correct_kmod_keygen_command_executed(self):
        # Check that calling generateUefiKeys() will generate the
        # expected command.
        self.setUpPPA()
        self.setUpKmodKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.generateKmodKeys()
        self.assertEqual(2, fake_call.call_count)
        # Assert the actual command matches.
        args = fake_call.calls[0][0][0]
        # Sanitise the keygen tmp file.
        if args[11].endswith(".keygen"):
            args[11] = "XXX.keygen"
        expected_cmd = [
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
            "XXX.keygen",
            "-outform",
            "PEM",
            "-out",
            self.kmod_pem,
            "-keyout",
            self.kmod_pem,
        ]
        self.assertEqual(expected_cmd, args)
        args = fake_call.calls[1][0][0]
        expected_cmd = [
            "openssl",
            "x509",
            "-in",
            self.kmod_pem,
            "-outform",
            "DER",
            "-out",
            self.kmod_x509,
        ]
        self.assertEqual(expected_cmd, args)

    def test_correct_opal_openssl_config(self):
        # Check that calling generateOpensslConfig() will return an appropriate
        # openssl configuration.
        self.setUpPPA()
        upload = SigningUpload()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        text = upload.generateOpensslConfig("Opal", upload.openssl_config_opal)

        id_re = re.compile(r"^# OPAL OpenSSL config\n")
        cn_re = re.compile(r"\bCN\s*=\s*" + self.testcase_cn + r"\s+Opal")

        self.assertIn("[ req ]", text)
        self.assertIsNotNone(id_re.search(text))
        self.assertIsNotNone(cn_re.search(text))
        self.assertNotIn("extendedKeyUsage", text)

    def test_correct_opal_signing_command_executed(self):
        # Check that calling signOpal() will generate the expected command
        # when appropriate keys are present.
        self.setUpOpalKeys()
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.generateOpalKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signOpal("t.opal")
        self.assertEqual(1, fake_call.call_count)
        # Assert command form.
        args = fake_call.calls[0][0][0]
        expected_cmd = [
            "kmodsign",
            "-D",
            "sha512",
            self.opal_pem,
            self.opal_x509,
            "t.opal",
            "t.opal.sig",
        ]
        self.assertEqual(expected_cmd, args)
        self.assertEqual(0, upload.generateOpalKeys.call_count)

    def test_correct_opal_signing_command_executed_no_keys(self):
        # Check that calling signOpal() will generate no commands when
        # no keys are present.
        self.setUpOpalKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.generateOpalKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signOpal("t.opal")
        self.assertEqual(0, fake_call.call_count)
        self.assertEqual(0, upload.generateOpalKeys.call_count)

    def test_correct_opal_keygen_command_executed(self):
        # Check that calling generateOpalKeys() will generate the
        # expected command.
        self.setUpPPA()
        self.setUpOpalKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.generateOpalKeys()
        self.assertEqual(2, fake_call.call_count)
        # Assert the actual command matches.
        args = fake_call.calls[0][0][0]
        # Sanitise the keygen tmp file.
        if args[11].endswith(".keygen"):
            args[11] = "XXX.keygen"
        expected_cmd = [
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
            "XXX.keygen",
            "-outform",
            "PEM",
            "-out",
            self.opal_pem,
            "-keyout",
            self.opal_pem,
        ]
        self.assertEqual(expected_cmd, args)
        args = fake_call.calls[1][0][0]
        expected_cmd = [
            "openssl",
            "x509",
            "-in",
            self.opal_pem,
            "-outform",
            "DER",
            "-out",
            self.opal_x509,
        ]
        self.assertEqual(expected_cmd, args)

    def test_correct_sipl_openssl_config(self):
        # Check that calling generateOpensslConfig() will return an appropriate
        # openssl configuration.
        self.setUpPPA()
        upload = SigningUpload()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        text = upload.generateOpensslConfig("SIPL", upload.openssl_config_sipl)

        id_re = re.compile(r"^# SIPL OpenSSL config\n")
        cn_re = re.compile(r"\bCN\s*=\s*" + self.testcase_cn + r"\s+SIPL")

        self.assertIn("[ req ]", text)
        self.assertIsNotNone(id_re.search(text))
        self.assertIsNotNone(cn_re.search(text))
        self.assertNotIn("extendedKeyUsage", text)

    def test_correct_sipl_signing_command_executed(self):
        # Check that calling signSipl() will generate the expected command
        # when appropriate keys are present.
        self.setUpSiplKeys()
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.generateSiplKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signSipl("t.sipl")
        self.assertEqual(1, fake_call.call_count)
        # Assert command form.
        args = fake_call.calls[0][0][0]
        expected_cmd = [
            "kmodsign",
            "-D",
            "sha512",
            self.sipl_pem,
            self.sipl_x509,
            "t.sipl",
            "t.sipl.sig",
        ]
        self.assertEqual(expected_cmd, args)
        self.assertEqual(0, upload.generateSiplKeys.call_count)

    def test_correct_sipl_signing_command_executed_no_keys(self):
        # Check that calling signSipl() will generate no commands when
        # no keys are present.
        self.setUpSiplKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.generateSiplKeys = FakeMethod()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.signOpal("t.sipl")
        self.assertEqual(0, fake_call.call_count)
        self.assertEqual(0, upload.generateSiplKeys.call_count)

    def test_correct_sipl_keygen_command_executed(self):
        # Check that calling generateSiplKeys() will generate the
        # expected command.
        self.setUpPPA()
        self.setUpSiplKeys(create=False)
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.setTargetDirectory(
            self.archive, "test_1.0_amd64.tar.gz", self.suite
        )
        upload.generateSiplKeys()
        self.assertEqual(2, fake_call.call_count)
        # Assert the actual command matches.
        args = fake_call.calls[0][0][0]
        # Sanitise the keygen tmp file.
        if args[11].endswith(".keygen"):
            args[11] = "XXX.keygen"
        expected_cmd = [
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
            "XXX.keygen",
            "-outform",
            "PEM",
            "-out",
            self.sipl_pem,
            "-keyout",
            self.sipl_pem,
        ]
        self.assertEqual(expected_cmd, args)
        args = fake_call.calls[1][0][0]
        expected_cmd = [
            "openssl",
            "x509",
            "-in",
            self.sipl_pem,
            "-outform",
            "DER",
            "-out",
            self.sipl_x509,
        ]
        self.assertEqual(expected_cmd, args)

    def test_signs_uefi_image(self):
        # Each image in the tarball is signed.
        self.setUpUefiKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        upload = self.process()
        self.assertEqual(1, upload.signUefi.call_count)

    def test_signs_uefi_image_per_series(self):
        """Check that signing can be per series.
        This should fall through to the first series,
        as the second does not have keys.
        """
        first_series = self.factory.makeDistroSeries(
            self.distro, name="existingkeys"
        )
        self.distroseries = self.factory.makeDistroSeries(
            self.distro, name="nokeys"
        )
        self.suite = self.distroseries.name
        # Each image in the tarball is signed.
        self.setUpUefiKeys()
        self.setUpUefiKeys(series=first_series)
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        upload = self.process_emulate()
        expected_callers = [("UEFI signing", 1)]
        self.assertContentEqual(expected_callers, upload.callLog.caller_list())
        # Check the correct series name appears in the call arguments
        self.assertIn("existingkeys", upload.callLog.extract_args()[0][1][2])

    def test_signs_fit_image(self):
        # Each image in the tarball is signed.
        self.setUpFitKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.fit", b"")
        upload = self.process()
        self.assertEqual(1, upload.signFit.call_count)

    def test_signs_kmod_image(self):
        # Each image in the tarball is signed.
        self.setUpKmodKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.ko", b"")
        upload = self.process()
        self.assertEqual(1, upload.signKmod.call_count)

    def test_signs_opal_image(self):
        # Each image in the tarball is signed.
        self.setUpOpalKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.opal", b"")
        upload = self.process()
        self.assertEqual(1, upload.signOpal.call_count)

    def test_signs_sipl_image(self):
        # Each image in the tarball is signed.
        self.setUpSiplKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        upload = self.process()
        self.assertEqual(1, upload.signSipl.call_count)

    def test_signs_combo_image(self):
        # Each image in the tarball is signed.
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty2.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty2.opal", b"")
        self.tarfile.add_file("1.0/empty3.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.tarfile.add_file("1.0/empty2.sipl", b"")
        self.tarfile.add_file("1.0/empty3.sipl", b"")
        self.tarfile.add_file("1.0/empty4.sipl", b"")
        self.tarfile.add_file("1.0/empty.fit", b"")
        self.tarfile.add_file("1.0/empty2.fit", b"")
        self.tarfile.add_file("1.0/empty3.fit", b"")
        self.tarfile.add_file("1.0/empty4.fit", b"")
        self.tarfile.add_file("1.0/empty5.fit", b"")
        upload = self.process()
        self.assertEqual(1, upload.signUefi.call_count)
        self.assertEqual(2, upload.signKmod.call_count)
        self.assertEqual(3, upload.signOpal.call_count)
        self.assertEqual(4, upload.signSipl.call_count)
        self.assertEqual(5, upload.signFit.call_count)

    def test_installed(self):
        # Files in the tarball are installed correctly.
        self.setUpUefiKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.process()
        self.assertTrue(
            os.path.isdir(os.path.join(self.getDistsPath(), "signed"))
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    self.getSignedPath("test", "amd64"), "1.0", "empty.efi"
                )
            )
        )

    def test_installed_existing_uefi(self):
        # Files in the tarball are installed correctly.
        os.makedirs(os.path.join(self.getDistsPath(), "uefi"))
        self.setUpUefiKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.process()
        self.assertTrue(
            os.path.isdir(os.path.join(self.getDistsPath(), "signed"))
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    self.getSignedPath("test", "amd64"), "1.0", "empty.efi"
                )
            )
        )

    def test_installed_existing_signing(self):
        # Files in the tarball are installed correctly.
        os.makedirs(os.path.join(self.getDistsPath(), "signing"))
        self.setUpUefiKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.process()
        self.assertTrue(
            os.path.isdir(os.path.join(self.getDistsPath(), "signed"))
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    self.getSignedPath("test", "amd64"), "1.0", "empty.efi"
                )
            )
        )

    def test_create_uefi_keys_autokey_off(self):
        # Keys are not created.
        self.setUpUefiKeys(create=False)
        self.assertFalse(os.path.exists(self.key))
        self.assertFalse(os.path.exists(self.cert))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signUefi(os.path.join(self.makeTemporaryDirectory(), "t.efi"))
        self.assertEqual(0, upload.callLog.caller_count("UEFI keygen"))
        self.assertFalse(os.path.exists(self.key))
        self.assertFalse(os.path.exists(self.cert))

    def test_create_uefi_keys_autokey_on(self):
        # Keys are created on demand.
        self.setUpPPA()
        self.setUpUefiKeys(create=False)
        self.assertFalse(os.path.exists(self.key))
        self.assertFalse(os.path.exists(self.cert))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signUefi(os.path.join(self.makeTemporaryDirectory(), "t.efi"))
        self.assertEqual(1, upload.callLog.caller_count("UEFI keygen"))
        self.assertTrue(os.path.exists(self.key))
        self.assertTrue(os.path.exists(self.cert))
        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.cert).st_mode), 0o644)

    def test_create_fit_keys_autokey_off(self):
        # Keys are not created.
        self.setUpFitKeys(create=False)
        self.assertFalse(os.path.exists(self.fit_key))
        self.assertFalse(os.path.exists(self.fit_cert))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signFit(os.path.join(self.makeTemporaryDirectory(), "fit"))
        self.assertEqual(0, upload.callLog.caller_count("FIT keygen"))
        self.assertFalse(os.path.exists(self.fit_key))
        self.assertFalse(os.path.exists(self.fit_cert))

    def test_create_fit_keys_autokey_on(self):
        # Keys are created on demand.
        self.setUpPPA()
        self.setUpFitKeys(create=False)
        self.assertFalse(os.path.exists(self.fit_key))
        self.assertFalse(os.path.exists(self.fit_cert))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        fake_copy = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("shutil.copy", fake_copy))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signFit(os.path.join(self.makeTemporaryDirectory(), "t.fit"))
        self.assertEqual(1, upload.callLog.caller_count("FIT keygen"))
        self.assertTrue(os.path.exists(self.fit_key))
        self.assertTrue(os.path.exists(self.fit_cert))
        self.assertEqual(stat.S_IMODE(os.stat(self.fit_key).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.fit_cert).st_mode), 0o644)

    def test_create_kmod_keys_autokey_off(self):
        # Keys are not created.
        self.setUpKmodKeys(create=False)
        self.assertFalse(os.path.exists(self.kmod_pem))
        self.assertFalse(os.path.exists(self.kmod_x509))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signKmod(os.path.join(self.makeTemporaryDirectory(), "t.ko"))
        self.assertEqual(0, upload.callLog.caller_count("Kmod keygen key"))
        self.assertEqual(0, upload.callLog.caller_count("Kmod keygen cert"))
        self.assertFalse(os.path.exists(self.kmod_pem))
        self.assertFalse(os.path.exists(self.kmod_x509))

    def test_create_kmod_keys_autokey_on(self):
        # Keys are created on demand.
        self.setUpPPA()
        self.setUpKmodKeys(create=False)
        self.assertFalse(os.path.exists(self.kmod_pem))
        self.assertFalse(os.path.exists(self.kmod_x509))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signKmod(os.path.join(self.makeTemporaryDirectory(), "t.ko"))
        self.assertEqual(1, upload.callLog.caller_count("Kmod keygen key"))
        self.assertEqual(1, upload.callLog.caller_count("Kmod keygen cert"))
        self.assertTrue(os.path.exists(self.kmod_pem))
        self.assertTrue(os.path.exists(self.kmod_x509))
        self.assertEqual(stat.S_IMODE(os.stat(self.kmod_pem).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.kmod_x509).st_mode), 0o644)

    def test_create_opal_keys_autokey_off(self):
        # Keys are not created.
        self.setUpOpalKeys(create=False)
        self.assertFalse(os.path.exists(self.opal_pem))
        self.assertFalse(os.path.exists(self.opal_x509))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signOpal(os.path.join(self.makeTemporaryDirectory(), "t.opal"))
        self.assertEqual(0, upload.callLog.caller_count("Opal keygen key"))
        self.assertEqual(0, upload.callLog.caller_count("Opal keygen cert"))
        self.assertFalse(os.path.exists(self.opal_pem))
        self.assertFalse(os.path.exists(self.opal_x509))

    def test_create_opal_keys_autokey_on(self):
        # Keys are created on demand.
        self.setUpPPA()
        self.setUpOpalKeys(create=False)
        self.assertFalse(os.path.exists(self.opal_pem))
        self.assertFalse(os.path.exists(self.opal_x509))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signOpal(os.path.join(self.makeTemporaryDirectory(), "t.opal"))
        self.assertEqual(1, upload.callLog.caller_count("Opal keygen key"))
        self.assertEqual(1, upload.callLog.caller_count("Opal keygen cert"))
        self.assertTrue(os.path.exists(self.opal_pem))
        self.assertTrue(os.path.exists(self.opal_x509))
        self.assertEqual(stat.S_IMODE(os.stat(self.opal_pem).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.opal_x509).st_mode), 0o644)

    def test_create_sipl_keys_autokey_off(self):
        # Keys are not created.
        self.setUpSiplKeys(create=False)
        self.assertFalse(os.path.exists(self.sipl_pem))
        self.assertFalse(os.path.exists(self.sipl_x509))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signOpal(os.path.join(self.makeTemporaryDirectory(), "t.sipl"))
        self.assertEqual(0, upload.callLog.caller_count("SIPL keygen key"))
        self.assertEqual(0, upload.callLog.caller_count("SIPL keygen cert"))
        self.assertFalse(os.path.exists(self.sipl_pem))
        self.assertFalse(os.path.exists(self.sipl_x509))

    def test_create_sipl_keys_autokey_on(self):
        # Keys are created on demand.
        self.setUpPPA()
        self.setUpSiplKeys(create=False)
        self.assertFalse(os.path.exists(self.sipl_pem))
        self.assertFalse(os.path.exists(self.sipl_x509))
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload = SigningUpload()
        upload.callLog = FakeMethodCallLog(upload=upload)
        upload.setTargetDirectory(self.archive, "test_1.0_amd64.tar.gz", "")
        upload.signSipl(os.path.join(self.makeTemporaryDirectory(), "t.sipl"))
        self.assertEqual(1, upload.callLog.caller_count("SIPL keygen key"))
        self.assertEqual(1, upload.callLog.caller_count("SIPL keygen cert"))
        self.assertTrue(os.path.exists(self.sipl_pem))
        self.assertTrue(os.path.exists(self.sipl_x509))
        self.assertEqual(stat.S_IMODE(os.stat(self.sipl_pem).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.sipl_x509).st_mode), 0o644)

    def test_checksumming_tree(self):
        # Specifying no options should leave us with an open tree,
        # confirm it is checksummed.
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.setUpOpalKeys()
        self.setUpSiplKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.process_emulate()
        sha256file = os.path.join(
            self.getSignedPath("test", "amd64"), "1.0", "SHA256SUMS"
        )
        self.assertTrue(os.path.exists(sha256file))

    @defer.inlineCallbacks
    def test_checksumming_tree_signed(self):
        # Specifying no options should leave us with an open tree,
        # confirm it is checksummed.  Supply an archive signing key
        # which should trigger signing of the checksum file.
        yield self.setUpArchiveKey()
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.setUpOpalKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.process_emulate()
        sha256file = os.path.join(
            self.getSignedPath("test", "amd64"), "1.0", "SHA256SUMS"
        )
        self.assertTrue(os.path.exists(sha256file))
        self.assertThat(
            sha256file + ".gpg",
            FileContains(
                matcher=StartsWith("-----BEGIN PGP SIGNATURE-----\n")
            ),
        )

    @defer.inlineCallbacks
    def test_checksumming_tree_signed_options_tarball(self):
        # Specifying no options should leave us with an open tree,
        # confirm it is checksummed.  Supply an archive signing key
        # which should trigger signing of the checksum file.
        yield self.setUpArchiveKey()
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.setUpOpalKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"tarball")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.process_emulate()
        sha256file = os.path.join(
            self.getSignedPath("test", "amd64"), "1.0", "SHA256SUMS"
        )
        self.assertTrue(os.path.exists(sha256file))
        self.assertThat(
            sha256file + ".gpg",
            FileContains(
                matcher=StartsWith("-----BEGIN PGP SIGNATURE-----\n")
            ),
        )

        tarfilename = os.path.join(
            self.getSignedPath("test", "amd64"), "1.0", "signed.tar.gz"
        )
        with tarfile.open(tarfilename) as tarball:
            self.assertThat(
                tarball.getnames(),
                MatchesAll(
                    *[
                        Not(Contains(name))
                        for name in [
                            "1.0/SHA256SUMS",
                            "1.0/SHA256SUMS.gpg",
                            "1.0/signed.tar.gz",
                        ]
                    ]
                ),
            )

    def test_checksumming_tree_signed_with_external_run_parts(self):
        # Checksum files can be signed using an external run-parts helper.
        # We disable subprocess.call because there's just too much going on,
        # so we can't test this completely, but we can at least test that
        # run_parts is called.
        self.enableRunParts(distribution_name=self.distro.name)
        run_parts_fixture = self.useFixture(
            MonkeyPatch(
                "lp.archivepublisher.archivegpgsigningkey.run_parts",
                FakeMethod(),
            )
        )
        self.setUpUefiKeys()
        self.setUpKmodKeys()
        self.setUpOpalKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.tarfile.add_file("1.0/empty.ko", b"")
        self.tarfile.add_file("1.0/empty.opal", b"")
        self.tarfile.add_file("1.0/empty.sipl", b"")
        self.process_emulate()
        sha256file = os.path.join(
            self.getSignedPath("test", "amd64"), "1.0", "SHA256SUMS"
        )
        self.assertTrue(os.path.exists(sha256file))
        self.assertEqual(1, run_parts_fixture.new_value.call_count)
        args, kwargs = run_parts_fixture.new_value.calls[-1]
        self.assertEqual((self.distro.name, "sign.d"), args)
        self.assertThat(
            kwargs["env"],
            MatchesDict(
                {
                    "ARCHIVEROOT": Equals(
                        os.path.join(self.temp_dir, self.distro.name)
                    ),
                    "DISTRIBUTION": Equals(self.distro.name),
                    "INPUT_PATH": Equals(sha256file),
                    "MODE": Equals("detached"),
                    "OUTPUT_PATH": Equals("%s.gpg" % sha256file),
                    "SITE_NAME": Equals("launchpad.test"),
                    "SUITE": Equals(self.suite),
                }
            ),
        )

    def test_getSeriesKeyName_no_series(self):
        upload = SigningUpload()
        config = getPubConfig(self.archive)
        result = upload.getSeriesPath(
            config, "key.key", self.archive, "notaseries"
        )
        expected_path = os.path.join(config.signingroot, "key.key")
        self.assertEqual(expected_path, result)

    def test_getSeriesKeyName_autokey(self):
        self.setUpPPA()
        self.factory.makeDistroSeries(self.distro, name="newdistroseries")
        upload = SigningUpload()
        config = getPubConfig(self.archive)
        result = upload.getSeriesPath(
            config, "uefi.key", self.archive, "newdistroseries"
        )
        expected_path = os.path.join(config.signingroot, "uefi.key")
        self.assertEqual(expected_path, result)

    def test_getSeriesKeyName_one_distroseries(self):
        self.setUpUefiKeys(
            series=self.factory.makeDistroSeries(
                self.distro, name="newdistroseries"
            )
        )
        upload = SigningUpload()
        config = getPubConfig(self.archive)
        result = upload.getSeriesPath(
            config, "uefi.key", self.archive, "newdistroseries"
        )
        expected_path = os.path.join(
            config.signingroot,
            "newdistroseries",
            "uefi.key",
        )
        self.assertEqual(expected_path, result)

    def test_getSeriesKeyName_two_distroseries(self):
        self.setUpUefiKeys(
            series=self.factory.makeDistroSeries(
                self.distro, name="newdistroseries"
            )
        )
        self.setUpUefiKeys(
            series=self.factory.makeDistroSeries(
                self.distro, name="seconddistroseries"
            )
        )
        upload = SigningUpload()
        config = getPubConfig(self.archive)
        result = upload.getSeriesPath(
            config, "uefi.key", self.archive, "seconddistroseries"
        )
        expected_path = os.path.join(
            config.signingroot,
            "seconddistroseries",
            "uefi.key",
        )
        self.assertEqual(expected_path, result)

    def test_getSeriesKeyName_two_distroseries_fallthrough(self):
        self.setUpUefiKeys(
            series=self.factory.makeDistroSeries(
                self.distro, name="newdistroseries"
            )
        )
        self.factory.makeDistroSeries(self.distro, name="seconddistroseries")
        upload = SigningUpload()
        config = getPubConfig(self.archive)
        result = upload.getSeriesPath(
            config, "uefi.key", self.archive, "seconddistroseries"
        )
        expected_path = os.path.join(
            config.signingroot,
            "newdistroseries",
            "uefi.key",
        )
        self.assertEqual(expected_path, result)

    def test_getSeriesKeyName_correct_list(self):
        self.setUpUefiKeys(
            series=self.factory.makeDistroSeries(
                self.distro, name="newdistroseries"
            )
        )
        self.setUpUefiKeys(
            series=self.factory.makeDistroSeries(
                self.distro, name="seconddistroseries"
            )
        )
        upload = SigningUpload()
        config = getPubConfig(self.archive)
        result = upload.getSeriesPath(
            config, "uefi.key", self.archive, "newdistroseries"
        )
        expected_path = os.path.join(
            config.signingroot,
            "newdistroseries",
            "uefi.key",
        )
        self.assertEqual(expected_path, result)


class TestUefi(TestSigningHelpers):
    def getSignedPath(self, loader_type, arch):
        return os.path.join(
            self.getDistsPath(), "uefi", "%s-%s" % (loader_type, arch)
        )

    def process(self):
        self.tarfile.close()
        self.buffer.close()
        upload = UefiUpload()
        upload.signUefi = FakeMethod()
        upload.signKmod = FakeMethod()
        # Under no circumstances is it safe to execute actual commands.
        fake_call = FakeMethod(result=0)
        self.useFixture(MonkeyPatch("subprocess.call", fake_call))
        upload.process(self.archive, self.path, self.suite)
        self.assertEqual(0, fake_call.call_count)

        return upload

    def test_installed(self):
        # Files in the tarball are installed correctly.
        self.setUpUefiKeys()
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"")
        self.process()
        self.assertTrue(
            os.path.isdir(os.path.join(self.getDistsPath(), "uefi"))
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    self.getSignedPath("test", "amd64"), "1.0", "empty.efi"
                )
            )
        )


class TestSigningUploadWithSigningService(TestSigningHelpers):
    """Tests for SigningUpload using lp-signing service"""

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({PUBLISHER_USES_SIGNING_SERVICE: True}))

        self.signing_service_client = self.useFixture(
            SigningServiceClientFixture(self.factory)
        )
        self.signing_keys = {
            k: v.signing_key
            for k, v in self.setUpAllKeyTypes(self.archive).items()
        }

    def setUpAllKeyTypes(self, archive):
        """Helper to create

        :return: A dict like {key_type: signing_key} with all keys available.
        """
        keys_per_type = {}
        for key_type in SigningKeyType.items:
            signing_key = self.factory.makeSigningKey(key_type=key_type)
            arch_key = self.factory.makeArchiveSigningKey(
                archive=archive, signing_key=signing_key
            )
            keys_per_type[key_type] = arch_key
        return keys_per_type

    def getArchiveSigningKey(self, key_type):
        signing_key = self.factory.makeSigningKey(key_type=key_type)
        arch_signing_key = self.factory.makeArchiveSigningKey(
            archive=self.archive, signing_key=signing_key
        )
        return arch_signing_key

    @staticmethod
    def getFileListContent(basedir, filenames):
        contents = []
        for filename in filenames:
            with open(os.path.join(basedir, filename), "rb") as fd:
                contents.append(fd.read())
        return contents

    def getSignedPath(self, loader_type, arch):
        return os.path.join(
            self.getDistsPath(), "signed", "%s-%s" % (loader_type, arch)
        )

    def process_emulate(self):
        """Shortcut to close tarfile and run SigningUpload.process."""
        self.tarfile.close()
        self.buffer.close()

        upload = SigningUpload()
        with dbuser("process_accepted"):
            upload.process(self.archive, self.path, self.suite)
        return upload

    def test_set_target_directory_with_distroseries(self):
        archive = self.factory.makeArchive()
        series_name = archive.distribution.series[1].name

        upload = SigningUpload()
        upload.setTargetDirectory(
            archive, "test_1.0_amd64.tar.gz", series_name
        )

        pubconfig = getPubConfig(archive)
        self.assertThat(
            upload,
            MatchesStructure.byEquality(
                distro_series=archive.distribution.series[1],
                archive=archive,
                autokey=pubconfig.signingautokey,
            ),
        )
        self.assertEqual(0, self.signing_service_client.generate.call_count)
        self.assertEqual(0, self.signing_service_client.sign.call_count)

    def test_options_handling_single(self):
        """If the configured key/cert are missing, processing succeeds but
        nothing is signed.
        """
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"first\n")

        upload = self.process_emulate()

        self.assertContentEqual(["first"], upload.signing_options.keys())

        self.assertEqual(0, self.signing_service_client.generate.call_count)
        self.assertEqual(0, self.signing_service_client.sign.call_count)

    def test_options_handling_multiple(self):
        """If the configured key/cert are missing, processing succeeds but
        nothing is signed.
        """
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"first\nsecond\n")

        upload = self.process_emulate()

        self.assertContentEqual(
            ["first", "second"], upload.signing_options.keys()
        )
        self.assertEqual(0, self.signing_service_client.generate.call_count)
        self.assertEqual(0, self.signing_service_client.sign.call_count)

    def test_options_tarball(self):
        """Specifying the "tarball" option should create an tarball in
        tmpdir.
        """
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"tarball")
        self.tarfile.add_file("1.0/empty.efi", b"a")
        self.tarfile.add_file("1.0/empty.ko", b"b")
        self.tarfile.add_file("1.0/empty.opal", b"c")
        self.tarfile.add_file("1.0/empty.sipl", b"d")
        self.tarfile.add_file("1.0/empty.fit", b"e")
        self.tarfile.add_file("1.0/empty.cv2-kernel", b"f")
        self.tarfile.add_file("1.0/empty.android-kernel", b"g")
        self.process_emulate()

        self.assertThat(
            self.getSignedPath("test", "amd64"),
            SignedMatches(
                [
                    "1.0/SHA256SUMS",
                    "1.0/signed.tar.gz",
                ]
            ),
        )
        tarfilename = os.path.join(
            self.getSignedPath("test", "amd64"), "1.0", "signed.tar.gz"
        )
        with tarfile.open(tarfilename) as tarball:
            self.assertContentEqual(
                [
                    "1.0",
                    "1.0/control",
                    "1.0/control/options",
                    "1.0/empty.efi",
                    "1.0/empty.efi.signed",
                    "1.0/control/uefi.crt",
                    "1.0/empty.ko",
                    "1.0/empty.ko.sig",
                    "1.0/control/kmod.x509",
                    "1.0/empty.opal",
                    "1.0/empty.opal.sig",
                    "1.0/control/opal.x509",
                    "1.0/empty.sipl",
                    "1.0/empty.sipl.sig",
                    "1.0/control/sipl.x509",
                    "1.0/empty.fit",
                    "1.0/empty.fit.signed",
                    "1.0/control/fit.crt",
                    "1.0/empty.cv2-kernel",
                    "1.0/empty.cv2-kernel.sig",
                    "1.0/control/cv2-kernel.pub",
                    "1.0/empty.android-kernel",
                    "1.0/empty.android-kernel.sig",
                    "1.0/control/android-kernel.x509",
                ],
                tarball.getnames(),
            )
        self.assertEqual(0, self.signing_service_client.generate.call_count)
        keys = self.signing_keys
        self.assertItemsEqual(
            [
                call(
                    SigningKeyType.UEFI,
                    keys[SigningKeyType.UEFI].fingerprint,
                    "empty.efi",
                    b"a",
                    SigningMode.ATTACHED,
                ),
                call(
                    SigningKeyType.KMOD,
                    keys[SigningKeyType.KMOD].fingerprint,
                    "empty.ko",
                    b"b",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.OPAL,
                    keys[SigningKeyType.OPAL].fingerprint,
                    "empty.opal",
                    b"c",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.SIPL,
                    keys[SigningKeyType.SIPL].fingerprint,
                    "empty.sipl",
                    b"d",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.FIT,
                    keys[SigningKeyType.FIT].fingerprint,
                    "empty.fit",
                    b"e",
                    SigningMode.ATTACHED,
                ),
                call(
                    SigningKeyType.CV2_KERNEL,
                    keys[SigningKeyType.CV2_KERNEL].fingerprint,
                    "empty.cv2-kernel",
                    b"f",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.ANDROID_KERNEL,
                    keys[SigningKeyType.ANDROID_KERNEL].fingerprint,
                    "empty.android-kernel",
                    b"g",
                    SigningMode.DETACHED,
                ),
            ],
            self.signing_service_client.sign.call_args_list,
        )

    def test_options_signed_only(self):
        """Specifying the "signed-only" option should trigger removal of
        the source files leaving signatures only.
        """
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"signed-only")
        self.tarfile.add_file("1.0/empty.efi", b"a")
        self.tarfile.add_file("1.0/empty.ko", b"b")
        self.tarfile.add_file("1.0/empty.opal", b"c")
        self.tarfile.add_file("1.0/empty.sipl", b"d")
        self.tarfile.add_file("1.0/empty.fit", b"e")
        self.tarfile.add_file("1.0/empty.cv2-kernel", b"f")
        self.tarfile.add_file("1.0/empty.android-kernel", b"g")

        self.process_emulate()

        self.assertThat(
            self.getSignedPath("test", "amd64"),
            SignedMatches(
                [
                    "1.0/SHA256SUMS",
                    "1.0/control/options",
                    "1.0/empty.efi.signed",
                    "1.0/control/uefi.crt",
                    "1.0/empty.ko.sig",
                    "1.0/control/kmod.x509",
                    "1.0/empty.opal.sig",
                    "1.0/control/opal.x509",
                    "1.0/empty.sipl.sig",
                    "1.0/control/sipl.x509",
                    "1.0/empty.fit.signed",
                    "1.0/control/fit.crt",
                    "1.0/empty.cv2-kernel.sig",
                    "1.0/control/cv2-kernel.pub",
                    "1.0/empty.android-kernel.sig",
                    "1.0/control/android-kernel.x509",
                ]
            ),
        )
        self.assertEqual(0, self.signing_service_client.generate.call_count)
        keys = self.signing_keys
        self.assertItemsEqual(
            [
                call(
                    SigningKeyType.UEFI,
                    keys[SigningKeyType.UEFI].fingerprint,
                    "empty.efi",
                    b"a",
                    SigningMode.ATTACHED,
                ),
                call(
                    SigningKeyType.KMOD,
                    keys[SigningKeyType.KMOD].fingerprint,
                    "empty.ko",
                    b"b",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.OPAL,
                    keys[SigningKeyType.OPAL].fingerprint,
                    "empty.opal",
                    b"c",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.SIPL,
                    keys[SigningKeyType.SIPL].fingerprint,
                    "empty.sipl",
                    b"d",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.FIT,
                    keys[SigningKeyType.FIT].fingerprint,
                    "empty.fit",
                    b"e",
                    SigningMode.ATTACHED,
                ),
                call(
                    SigningKeyType.CV2_KERNEL,
                    keys[SigningKeyType.CV2_KERNEL].fingerprint,
                    "empty.cv2-kernel",
                    b"f",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.ANDROID_KERNEL,
                    keys[SigningKeyType.ANDROID_KERNEL].fingerprint,
                    "empty.android-kernel",
                    b"g",
                    SigningMode.DETACHED,
                ),
            ],
            self.signing_service_client.sign.call_args_list,
        )

    def test_options_tarball_signed_only(self):
        """Specifying the "tarball" option should create an tarball in
        the tmpdir.  Adding signed-only should trigger removal of the
        original files.
        """
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/control/options", b"tarball\nsigned-only")
        self.tarfile.add_file("1.0/empty.efi", b"a")
        self.tarfile.add_file("1.0/empty.ko", b"b")
        self.tarfile.add_file("1.0/empty.opal", b"c")
        self.tarfile.add_file("1.0/empty.sipl", b"d")
        self.tarfile.add_file("1.0/empty.fit", b"e")
        self.tarfile.add_file("1.0/empty.cv2-kernel", b"f")
        self.tarfile.add_file("1.0/empty.android-kernel", b"g")
        self.process_emulate()
        self.assertThat(
            self.getSignedPath("test", "amd64"),
            SignedMatches(
                [
                    "1.0/SHA256SUMS",
                    "1.0/signed.tar.gz",
                ]
            ),
        )
        tarfilename = os.path.join(
            self.getSignedPath("test", "amd64"), "1.0", "signed.tar.gz"
        )
        with tarfile.open(tarfilename) as tarball:
            self.assertContentEqual(
                [
                    "1.0",
                    "1.0/control",
                    "1.0/control/options",
                    "1.0/empty.efi.signed",
                    "1.0/control/uefi.crt",
                    "1.0/empty.ko.sig",
                    "1.0/control/kmod.x509",
                    "1.0/empty.opal.sig",
                    "1.0/control/opal.x509",
                    "1.0/empty.sipl.sig",
                    "1.0/control/sipl.x509",
                    "1.0/empty.fit.signed",
                    "1.0/control/fit.crt",
                    "1.0/empty.cv2-kernel.sig",
                    "1.0/control/cv2-kernel.pub",
                    "1.0/empty.android-kernel.sig",
                    "1.0/control/android-kernel.x509",
                ],
                tarball.getnames(),
            )
        self.assertEqual(0, self.signing_service_client.generate.call_count)
        keys = self.signing_keys
        self.assertItemsEqual(
            [
                call(
                    SigningKeyType.UEFI,
                    keys[SigningKeyType.UEFI].fingerprint,
                    "empty.efi",
                    b"a",
                    SigningMode.ATTACHED,
                ),
                call(
                    SigningKeyType.KMOD,
                    keys[SigningKeyType.KMOD].fingerprint,
                    "empty.ko",
                    b"b",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.OPAL,
                    keys[SigningKeyType.OPAL].fingerprint,
                    "empty.opal",
                    b"c",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.SIPL,
                    keys[SigningKeyType.SIPL].fingerprint,
                    "empty.sipl",
                    b"d",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.FIT,
                    keys[SigningKeyType.FIT].fingerprint,
                    "empty.fit",
                    b"e",
                    SigningMode.ATTACHED,
                ),
                call(
                    SigningKeyType.CV2_KERNEL,
                    keys[SigningKeyType.CV2_KERNEL].fingerprint,
                    "empty.cv2-kernel",
                    b"f",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.ANDROID_KERNEL,
                    keys[SigningKeyType.ANDROID_KERNEL].fingerprint,
                    "empty.android-kernel",
                    b"g",
                    SigningMode.DETACHED,
                ),
            ],
            self.signing_service_client.sign.call_args_list,
        )

    def test_archive_copy(self):
        """If there is no key/cert configuration, processing succeeds but
        nothing is signed.
        """
        self.archive = self.factory.makeArchive(
            distribution=self.distro, purpose=ArchivePurpose.COPY
        )

        pubconf = getPubConfig(self.archive)
        if not os.path.exists(pubconf.temproot):
            os.makedirs(pubconf.temproot)
        self.openArchive("test", "1.0", "amd64")
        self.tarfile.add_file("1.0/empty.efi", b"a")
        self.tarfile.add_file("1.0/empty.ko", b"b")
        self.tarfile.add_file("1.0/empty.opal", b"c")
        self.tarfile.add_file("1.0/empty.sipl", b"d")
        self.tarfile.add_file("1.0/empty.fit", b"e")
        self.tarfile.add_file("1.0/empty.cv2-kernel", b"f")
        self.tarfile.add_file("1.0/empty.android-kernel", b"g")
        self.tarfile.close()
        self.buffer.close()

        upload = SigningUpload()
        with dbuser("process_accepted"):
            upload.process(self.archive, self.path, self.suite)

        signed_path = self.getSignedPath("test", "amd64")
        self.assertThat(
            signed_path,
            SignedMatches(
                [
                    "1.0/SHA256SUMS",
                    "1.0/empty.efi",
                    "1.0/empty.ko",
                    "1.0/empty.opal",
                    "1.0/empty.sipl",
                    "1.0/empty.fit",
                    "1.0/empty.cv2-kernel",
                    "1.0/empty.android-kernel",
                ]
            ),
        )

        self.assertEqual(0, self.signing_service_client.generate.call_count)
        self.assertEqual(0, self.signing_service_client.sign.call_count)

    def test_sign_without_autokey_and_no_key_pre_set(self):
        """This case should raise exception, since we don't have fallback
        keys on the filesystem to cover for the missing signing service
        keys.
        """
        self.distro = self.factory.makeDistribution()
        self.distroseries = self.factory.makeDistroSeries(
            distribution=self.distro
        )
        self.suite = self.distroseries.name
        self.archive = self.factory.makeArchive(
            distribution=self.distro, purpose=ArchivePurpose.PRIMARY
        )

        filenames = [
            "1.0/empty.efi",
            "1.0/empty.ko",
            "1.0/empty.opal",
            "1.0/empty.sipl",
            "1.0/empty.fit",
            "1.0/empty.cv2-kernel",
            "1.0/empty.android-kernel",
        ]

        # Write data on the archive
        self.openArchive("test", "1.0", "amd64")
        for filename in filenames:
            self.tarfile.add_file(
                filename, ("somedata for %s" % filename).encode("UTF-8")
            )

        self.assertRaises(IOError, self.process_emulate)

    def test_sign_without_autokey_and_some_keys_pre_set(self):
        """For no autokey archives, signing process should sign only for the
        available keys, and skip signing the other files.
        """
        filenames = ["1.0/empty.ko", "1.0/empty.opal"]

        self.openArchive("test", "1.0", "amd64")
        for filename in filenames:
            self.tarfile.add_file(
                filename, ("some data for %s" % filename).encode("UTF-8")
            )

        self.process_emulate()

        signed_path = self.getSignedPath("test", "amd64")
        self.assertThat(
            signed_path,
            SignedMatches(
                filenames
                + [
                    "1.0/SHA256SUMS",
                    "1.0/empty.ko.sig",
                    "1.0/empty.opal.sig",
                    "1.0/control/kmod.x509",
                    "1.0/control/opal.x509",
                ]
            ),
        )

        self.assertEqual(0, self.signing_service_client.generate.call_count)
        keys = self.signing_keys
        self.assertItemsEqual(
            [
                call(
                    SigningKeyType.KMOD,
                    keys[SigningKeyType.KMOD].fingerprint,
                    "empty.ko",
                    b"some data for 1.0/empty.ko",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.OPAL,
                    keys[SigningKeyType.OPAL].fingerprint,
                    "empty.opal",
                    b"some data for 1.0/empty.opal",
                    SigningMode.DETACHED,
                ),
            ],
            self.signing_service_client.sign.call_args_list,
        )

    def test_sign_with_autokey_ppa(self):
        # PPAs should auto-generate keys. Let's use one for this test.
        self.setUpPPA()

        filenames = [
            "1.0/empty.efi",
            "1.0/empty.ko",
            "1.0/empty.opal",
            "1.0/empty.sipl",
            "1.0/empty.fit",
            "1.0/empty.cv2-kernel",
            "1.0/empty.android-kernel",
        ]

        self.openArchive("test", "1.0", "amd64")
        for filename in filenames:
            self.tarfile.add_file(
                filename, ("data - %s" % filename).encode("UTF-8")
            )

        self.tarfile.close()
        self.buffer.close()

        upload = SigningUpload()
        with dbuser("process_accepted"):
            upload.process(self.archive, self.path, self.suite)

        self.assertTrue(upload.autokey)

        expected_signed_filenames = [
            "1.0/empty.efi.signed",
            "1.0/empty.ko.sig",
            "1.0/empty.opal.sig",
            "1.0/empty.sipl.sig",
            "1.0/empty.fit.signed",
            "1.0/empty.cv2-kernel.sig",
            "1.0/empty.android-kernel.sig",
        ]

        expected_public_keys_filenames = [
            "1.0/control/uefi.crt",
            "1.0/control/kmod.x509",
            "1.0/control/opal.x509",
            "1.0/control/sipl.x509",
            "1.0/control/fit.crt",
            "1.0/control/cv2-kernel.pub",
            "1.0/control/android-kernel.x509",
        ]

        signed_path = self.getSignedPath("test", "amd64")
        self.assertThat(
            signed_path,
            SignedMatches(
                ["1.0/SHA256SUMS"]
                + filenames
                + expected_public_keys_filenames
                + expected_signed_filenames
            ),
        )

        self.assertEqual(7, self.signing_service_client.generate.call_count)
        self.assertEqual(7, self.signing_service_client.sign.call_count)

        fingerprints = {
            key_type: data["fingerprint"]
            for key_type, data in self.signing_service_client.generate_returns
        }
        self.assertItemsEqual(
            [
                call(
                    SigningKeyType.UEFI,
                    fingerprints[SigningKeyType.UEFI],
                    "empty.efi",
                    b"data - 1.0/empty.efi",
                    SigningMode.ATTACHED,
                ),
                call(
                    SigningKeyType.KMOD,
                    fingerprints[SigningKeyType.KMOD],
                    "empty.ko",
                    b"data - 1.0/empty.ko",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.OPAL,
                    fingerprints[SigningKeyType.OPAL],
                    "empty.opal",
                    b"data - 1.0/empty.opal",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.SIPL,
                    fingerprints[SigningKeyType.SIPL],
                    "empty.sipl",
                    b"data - 1.0/empty.sipl",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.FIT,
                    fingerprints[SigningKeyType.FIT],
                    "empty.fit",
                    b"data - 1.0/empty.fit",
                    SigningMode.ATTACHED,
                ),
                call(
                    SigningKeyType.CV2_KERNEL,
                    fingerprints[SigningKeyType.CV2_KERNEL],
                    "empty.cv2-kernel",
                    b"data - 1.0/empty.cv2-kernel",
                    SigningMode.DETACHED,
                ),
                call(
                    SigningKeyType.ANDROID_KERNEL,
                    fingerprints[SigningKeyType.ANDROID_KERNEL],
                    "empty.android-kernel",
                    b"data - 1.0/empty.android-kernel",
                    SigningMode.DETACHED,
                ),
            ],
            self.signing_service_client.sign.call_args_list,
        )

        # Checks that all files got signed
        contents = self.getFileListContent(
            signed_path, expected_signed_filenames
        )
        key_types = (
            SigningKeyType.UEFI,
            SigningKeyType.KMOD,
            SigningKeyType.OPAL,
            SigningKeyType.SIPL,
            SigningKeyType.FIT,
            SigningKeyType.CV2_KERNEL,
            SigningKeyType.ANDROID_KERNEL,
        )
        modes = {
            SigningKeyType.UEFI: SigningMode.ATTACHED,
            SigningKeyType.KMOD: SigningMode.DETACHED,
            SigningKeyType.OPAL: SigningMode.DETACHED,
            SigningKeyType.SIPL: SigningMode.DETACHED,
            SigningKeyType.FIT: SigningMode.ATTACHED,
            SigningKeyType.CV2_KERNEL: SigningMode.DETACHED,
            SigningKeyType.ANDROID_KERNEL: SigningMode.DETACHED,
        }
        expected_signed_contents = [
            (
                "signed with key_type=%s mode=%s" % (k.name, modes[k].name)
            ).encode("UTF-8")
            for k in key_types
        ]
        self.assertItemsEqual(expected_signed_contents, contents)

        # Checks that all public keys ended up in the 1.0/control/xxx files
        public_keys = {
            key_type: data["public-key"]
            for key_type, data in self.signing_service_client.generate_returns
        }
        contents = self.getFileListContent(
            signed_path, expected_public_keys_filenames
        )
        expected_public_keys = [public_keys[k] for k in key_types]
        self.assertEqual(expected_public_keys, contents)

    def test_fallback_handler(self):
        upload = SigningUpload()

        # Creating a new archive since our setUp method fills the self.archive
        # with signing keys, and we don't want that here.
        self.distro = self.factory.makeDistribution()
        self.distroseries = self.factory.makeDistroSeries(
            distribution=self.distro
        )
        self.suite = self.distroseries.name
        self.archive = self.factory.makeArchive(
            distribution=self.distro, purpose=ArchivePurpose.PRIMARY
        )
        pubconf = getPubConfig(self.archive)
        if not os.path.exists(pubconf.temproot):
            os.makedirs(pubconf.temproot)
            self.addCleanup(lambda: shutil.rmtree(pubconf.temproot, True))
        old_umask = os.umask(0o022)
        self.addCleanup(os.umask, old_umask)
        self.addCleanup(lambda: shutil.rmtree(pubconf.distroroot, True))

        # Make KMOD signing fail with an exception.
        def mock_sign(key_type, *args, **kwargs):
            if key_type == SigningKeyType.KMOD:
                raise ValueError("!!")
            return self.signing_service_client._sign(key_type, *args, **kwargs)

        self.signing_service_client.sign.side_effect = mock_sign

        # Pre-set KMOD fails on ".sign" method (should fallback to local
        # signing method).
        self.getArchiveSigningKey(SigningKeyType.KMOD)
        upload.signKmod = FakeMethod(result=0)

        # We don't have a signing service key for UEFI. Should fallback too.
        upload.signUefi = FakeMethod(result=0)

        # OPAL key works just fine.
        self.getArchiveSigningKey(SigningKeyType.OPAL)
        upload.signOpal = FakeMethod(result=0)

        filenames = ["1.0/empty.efi", "1.0/empty.ko", "1.0/empty.opal"]

        self.openArchive("test", "1.0", "amd64")
        for filename in filenames:
            self.tarfile.add_file(
                filename, ("data - %s" % filename).encode("UTF-8")
            )

        self.tarfile.close()
        self.buffer.close()

        # Small hack to keep the tmpdir used during upload.process
        # Without this hack, upload.tmpdir is set back to None at the end of
        # process() method execution, during cleanup phase.
        original_cleanup = upload.cleanup

        def intercept_cleanup():
            upload.tmpdir_used = upload.tmpdir
            original_cleanup()

        upload.cleanup = intercept_cleanup

        # Pretend that all key files exists, so the fallback calls are not
        # blocked.
        upload.keyFilesExist = lambda _: True

        with dbuser("process_accepted"):
            upload.process(self.archive, self.path, self.suite)

        # Make sure it only used the existing keys and fallbacks. No new key
        # should be generated.
        self.assertFalse(upload.autokey)

        self.assertEqual(0, self.signing_service_client.generate.call_count)
        self.assertEqual(2, self.signing_service_client.sign.call_count)

        # Check kmod signing
        self.assertEqual(1, upload.signKmod.call_count)
        self.assertEqual(
            [(os.path.join(upload.tmpdir_used, "1.0/empty.ko"),)],
            upload.signKmod.extract_args(),
        )

        # Check OPAL signing
        self.assertEqual(0, upload.signOpal.call_count)

        # Check UEFI signing
        self.assertEqual(1, upload.signUefi.call_count)
        self.assertEqual(
            [(os.path.join(upload.tmpdir_used, "1.0/empty.efi"),)],
            upload.signUefi.extract_args(),
        )

    def test_fallback_injects_key(self):
        self.useFixture(FeatureFixture({PUBLISHER_USES_SIGNING_SERVICE: ""}))
        self.useFixture(
            FeatureFixture(
                {PUBLISHER_SIGNING_SERVICE_INJECTS_KEYS: "SIPL OPAL"}
            )
        )

        now = datetime.now()
        mock_datetime = self.useFixture(
            MockPatch("lp.archivepublisher.signing.datetime")
        ).mock
        mock_datetime.now = lambda: now

        logger = BufferLogger()
        upload = SigningUpload(logger=logger)

        # Setup PPA to ensure it auto-generates keys.
        self.setUpPPA()

        filenames = ["1.0/empty.efi", "1.0/empty.opal"]

        self.openArchive("test", "1.0", "amd64")
        for filename in filenames:
            self.tarfile.add_file(
                filename, ("data - %s" % filename).encode("UTF-8")
            )
        self.tarfile.close()
        self.buffer.close()

        upload.process(self.archive, self.path, self.suite)
        self.assertTrue(upload.autokey)

        # Read the key file content
        with open(upload.opal_pem, "rb") as fd:
            private_key = fd.read()
        with open(upload.opal_x509, "rb") as fd:
            public_key = fd.read()

        # Check if we called lp-signing's /inject endpoint correctly
        self.assertEqual(1, self.signing_service_client.inject.call_count)
        self.assertEqual(
            (
                SigningKeyType.OPAL,
                private_key,
                public_key,
                "OPAL key for %s" % self.archive.reference,
                now.replace(tzinfo=timezone.utc),
            ),
            self.signing_service_client.inject.call_args[0],
        )

        log_content = logger.content.as_text()
        self.assertIn(
            "INFO Injecting key_type OPAL for archive %s into signing "
            "service" % (self.archive.name),
            log_content,
        )

        self.assertIn(
            "INFO Skipping injection for key type UEFI: "
            "not in ['SIPL', 'OPAL']",
            log_content,
        )

    def test_fallback_skips_key_injection_for_existing_keys(self):
        self.useFixture(FeatureFixture({PUBLISHER_USES_SIGNING_SERVICE: ""}))
        self.useFixture(
            FeatureFixture({PUBLISHER_SIGNING_SERVICE_INJECTS_KEYS: "UEFI"})
        )

        now = datetime.now()
        mock_datetime = self.useFixture(
            MockPatch("lp.archivepublisher.signing.datetime")
        ).mock
        mock_datetime.now = lambda: now

        # Setup PPA to ensure it auto-generates keys.
        self.setUpPPA()

        signing_key = self.factory.makeSigningKey(key_type=SigningKeyType.UEFI)
        self.factory.makeArchiveSigningKey(
            archive=self.archive, signing_key=signing_key
        )

        logger = BufferLogger()
        upload = SigningUpload(logger=logger)

        filenames = ["1.0/empty.efi"]

        self.openArchive("test", "1.0", "amd64")
        for filename in filenames:
            self.tarfile.add_file(
                filename, ("data - %s" % filename).encode("UTF-8")
            )
        self.tarfile.close()
        self.buffer.close()

        self.assertRaises(
            SigningKeyConflict,
            upload.process,
            self.archive,
            self.path,
            self.suite,
        )
        self.assertTrue(upload.autokey)

        # Make sure we deleted the locally generated keys.
        self.assertFalse(os.path.exists(upload.uefi_cert))
        self.assertFalse(os.path.exists(upload.uefi_key))

        # Make sure we didn't call lp-signing's /inject endpoint
        self.assertEqual(0, self.signing_service_client.inject.call_count)
        log_content = logger.content.as_text()
        self.assertIn(
            "INFO Skipping injection for key type %s: archive "
            "already has a key on lp-signing." % SigningKeyType.UEFI,
            log_content,
        )
