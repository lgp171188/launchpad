# Copyright 2004 Canonical Ltd.  All rights reserved.
#

"""Tests for ftparchive.py"""

__metaclass__ = type

import os
import shutil
import difflib
from tempfile import mkdtemp
import unittest

from zope.component import getUtility

from canonical.config import config
from canonical.archivepublisher.config import Config
from canonical.archivepublisher.diskpool import DiskPool
from canonical.archivepublisher.tests.util import (
    FakeSourcePublishing, FakeSourceFilePublishing,
    FakeBinaryPublishing, FakeBinaryFilePublishing, FakeLogger)
from canonical.launchpad.ftests.harness import (
    LaunchpadZopelessTestCase, LaunchpadZopelessTestSetup)
from canonical.launchpad.interfaces import (
    ILibraryFileAliasSet, IDistributionSet, PackagePublishingPriority,
    PackagePublishingPocket)
from canonical.librarian.client import LibrarianClient


def sanitize_feisty_apt_ftparchive_output(text):
    # See XXX barry 2007-05-18 bug=116048:
    #
    # This function filters feisty's apt-ftparchive output to look more like
    # dapper's output.  Specifically, it removes any lines that start with
    # SHA1: or SHA256: since dapper's version doesn't have these lines.  Start
    # by splitting the original text by lines, keeping the original line
    # endings.
    lines = text.splitlines(True)
    return ''.join(line for line in lines
                   if not (line.startswith('SHA256:') or
                           line.startswith('SHA1:')))


class TestFTPArchive(LaunchpadZopelessTestCase):
    dbuser = config.archivepublisher.dbuser

    def setUp(self):
        LaunchpadZopelessTestCase.setUp(self)
        self.library = LibrarianClient()
        self._distribution = getUtility(IDistributionSet)['ubuntutest']
        self._archive = self._distribution.main_archive
        self._config = Config(self._distribution)
        self._config.setupArchiveDirs()

        self._sampledir = os.path.join(config.root, "lib", "canonical",
                                       "archivepublisher", "tests", "apt-data")
        self._distsdir = self._config.distsroot
        self._confdir = self._config.miscroot
        self._pooldir = self._config.poolroot
        self._overdir = self._config.overrideroot
        self._listdir = self._config.overrideroot
        self._tempdir = self._config.temproot
        self._logger = FakeLogger()
        self._dp = DiskPool(self._pooldir, self._tempdir, self._logger)

    def tearDown(self):
        LaunchpadZopelessTestCase.tearDown(self)
        shutil.rmtree(self._config.distroroot)

    def _verifyFile(self, filename, directory, output_filter=None):
        """Compare byte-to-byte the given file and the respective sample.

        It's a poor way of testing files generated by apt-ftparchive.
        """
        result_path = os.path.join(directory, filename)
        result_text = open(result_path).read()
        if output_filter is not None:
            result_text = output_filter(result_text)
        sample_path = os.path.join(self._sampledir, filename)
        sample_text = open(sample_path).read()
        # When the comparison between the sample text and the generated text
        # differ, just printing the strings will be less than optimal.  Use
        # difflib to get a line-by-line comparison that makes it much more
        # immediately obvious what the differences are.
        diff_lines = difflib.ndiff(
            sample_text.splitlines(), result_text.splitlines())
        self.assertEqual(result_text, sample_text, '\n'.join(diff_lines))

    def _addMockFile(self, component, sourcename, leafname):
        """Add a mock file in Librarian.

        Returns a ILibraryFileAlias corresponding to the file uploaded.
        """
        fullpath = self._dp.pathFor(component, sourcename, leafname)
        dirname = os.path.dirname(fullpath)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        leaf = os.path.join(self._sampledir, leafname)
        leafcontent = file(leaf).read()
        file(fullpath, "w").write(leafcontent)

        alias_id = self.library.addFile(
            leafname, len(leafcontent), file(leaf), 'application/text')
        LaunchpadZopelessTestSetup.txn.commit()
        return getUtility(ILibraryFileAliasSet)[alias_id]

    def _getFakePubSource(self, sourcename, component, leafname, section, dr):
        """Return a mock source publishing record."""
        alias = self._addMockFile(component, sourcename, leafname)
        return FakeSourcePublishing(sourcename, component, alias, section, dr)

    def _getFakePubBinary(self, binaryname, sourcename, component, leafname,
                         section, dr, priority, archtag):
        """Return a mock binary publishing record."""
        alias = self._addMockFile(component, sourcename, leafname)
        return FakeBinaryPublishing(binaryname, sourcename, component, alias,
                                    section, dr, priority, archtag)

    def _getFakePubSourceFile(self, sourcename, component, leafname,
                              section, dr):
        """Return a mock source publishing record."""
        alias = self._addMockFile(component, sourcename, leafname)
        return FakeSourceFilePublishing(sourcename, component, leafname,
                                        alias, section, dr)

    def _getFakePubBinaryFile(self, binaryname, sourcename, component,
                              leafname, section, dr, archtag,):
        """Return a mock binary publishing record."""
        alias = self._addMockFile(component, sourcename, leafname)
        # Yes, it's the sourcename. There's nothing much related to
        # binary packages in BinaryPackageFilePublishing apart from the
        # binarypackagepublishing link it has.
        return FakeBinaryFilePublishing(sourcename, component, leafname,
                                        alias, section, dr, archtag)

    def _setUpFTPArchiveHandler(self):
        from canonical.archivepublisher.ftparchive import FTPArchiveHandler
        fa = FTPArchiveHandler(
            self._logger, self._config, self._dp, self._distribution, set())
        return fa

    def testInstantiate(self):
        """canonical.archivepublisher.FTPArchive should be instantiatable"""
        from canonical.archivepublisher.ftparchive import FTPArchiveHandler
        FTPArchiveHandler(self._logger, self._config, self._dp,
                   self._distribution, set())

    def testGetSourcesForOverrides(self):
        """Ensure Publisher.getSourcesForOverrides works.

        FTPArchiveHandler.getSourcesForOverride should be returning
        SourcePackagePublishingHistory rows that match the distroseries,
        its main_archive, the supplied pocket and have a status of PUBLISHED.
        """
        fa = self._setUpFTPArchiveHandler()
        ubuntuwarty = getUtility(IDistributionSet)['ubuntu']['hoary']
        spphs = fa.getSourcesForOverrides(
            ubuntuwarty, PackagePublishingPocket.RELEASE)

        # For the above query, we are depending on the sample data to
        # contain seven rows of SourcePackagePublishghistory data.
        expectedSources = [
            ('evolution', '1.0'),
            ('netapplet', '1.0-1'),
            ('pmount', '0.1-2'),
            ('alsa-utils', '1.0.9a-4ubuntu1'),
            ('cnews', 'cr.g7-37'),
            ('libstdc++', 'b8p'),
            ('linux-source-2.6.15', '2.6.15.3')
            ]
        actualSources = [
            (spph.sourcepackagerelease.name, spph.sourcepackagerelease.version)
            for spph in spphs]

        self.assertEqual(expectedSources, actualSources)

    def testGetBinariesForOverrides(self):
        """Ensure Publisher.getBinariesForOverrides works.

        FTPArchiveHandler.getBinariesForOverride should be returning
        BinaryPackagePublishingHistory rows that match the distroseries,
        its main_archive, the supplied pocket and have a status of PUBLISHED.
        """
        fa = self._setUpFTPArchiveHandler()
        ubuntuwarty = getUtility(IDistributionSet)['ubuntu']['hoary']
        bpphs = fa.getBinariesForOverrides(
            ubuntuwarty, PackagePublishingPocket.RELEASE)

        # The above query depends on the sample data containing two rows
        # of BinaryPackagePublishingHistory with these IDs:
        expectedBinaries = [
            ('pmount', '0.1-1'),
            ('pmount', '2:1.9-1'),
            ]
        actualBinaries = [
            (bpph.binarypackagerelease.name, bpph.binarypackagerelease.version)
            for bpph in bpphs]

        self.assertEqual(expectedBinaries, actualBinaries)

    def testPublishOverrides(self):
        """canonical.archivepublisher.Publisher.publishOverrides should work"""
        fa = self._setUpFTPArchiveHandler()
        src = [self._getFakePubSource(
            "foo", "main", "foo.dsc", "misc", "hoary-test")]
        bin = [self._getFakePubBinary(
            "foo", "foo", "main", "foo.deb", "misc", "hoary-test",
            PackagePublishingPriority.EXTRA, "i386")]
        fa.publishOverrides(src, bin)

        # Check that the overrides lists generated by LP exist and have the
        # expected contents.
        self._verifyFile("override.hoary-test.main", self._overdir)
        self._verifyFile("override.hoary-test.main.src", self._overdir)
        self._verifyFile("override.hoary-test.extra.main", self._overdir)

    def testPublishFileLists(self):
        """canonical.archivepublisher.Publisher.publishFileLists should work"""
        fa = self._setUpFTPArchiveHandler()
        src = [self._getFakePubSourceFile(
            "foo", "main", "foo.dsc", "misc", "hoary-test")]
        bin = [self._getFakePubBinaryFile(
            "foo", "foo", "main", "foo.deb", "misc", "hoary-test", "i386")]

        fa.publishFileLists(src, bin)

        # Check that the file lists generated by LP exist and have the
        # expected contents.
        self._verifyFile("hoary-test_main_source", self._listdir)
        self._verifyFile("hoary-test_main_binary-i386", self._listdir)

    def testGenerateConfig(self):
        """Generate apt-ftparchive config"""
        from canonical.archivepublisher.ftparchive import FTPArchiveHandler
        from canonical.archivepublisher.publishing import Publisher
        publisher = Publisher(
            self._logger, self._config, self._dp, self._archive)
        fa = FTPArchiveHandler(self._logger, self._config, self._dp,
                               self._distribution, publisher)
        src = [self._getFakePubSource(
            "foo", "main", "foo.dsc", "misc", "hoary-test")]
        bin = [self._getFakePubBinary(
            "foo", "foo", "main", "foo.deb", "misc", "hoary-test",
            PackagePublishingPriority.EXTRA, "i386")]
        fa.createEmptyPocketRequests(fullpublish=True)
        fa.publishOverrides(src, bin)
        src = [self._getFakePubSourceFile(
            "foo", "main", "foo.dsc", "misc", "hoary-test")]
        bin = [self._getFakePubBinaryFile(
            "foo", "foo", "main", "foo.deb", "misc", "hoary-test", "i386")]
        fa.publishFileLists(src, bin)

        # XXX cprov 2007-03-21: Relying on byte-to-byte configuration file
        # comparing is weak. We should improve this methodology to avoid
        # wasting time on test failures due to irrelevant format changes.
        apt_conf = fa.generateConfig(fullpublish=True)
        self._verifyFile("apt.conf", self._confdir)

        # XXX cprov 2007-03-21: This is an extra problem. Running a-f on
        # developer machines is wasteful. We need to find a away to split
        # those kind of tests and avoid to run it when performing 'make
        # check'. Although they should remain active in PQM to avoid possible
        # regressions.
        assert fa.runApt(apt_conf) == 0
        # XXX barry 2007-05-18 bug=116048:
        # This is a hack to make this test pass on dapper and feisty.
        # Feisty's apt-ftparchive outputs SHA256 and MD5 hash
        # lines which don't appear in dapper's version.  We can't change the
        # sample data to include these lines because that would break pqm,
        # which runs dapper.  But without those lines, a straight byte
        # comparison will fail on developers' feisty boxes.  The hack then is
        # to filter these lines out of the output from apt-ftparchive.
        # Feisty's apt-ftparchive also includes an extra blank line. :(
        self._verifyFile("Packages",
            os.path.join(self._distsdir, "hoary-test", "main", "binary-i386"),
                         sanitize_feisty_apt_ftparchive_output)
        self._verifyFile("Sources",
            os.path.join(self._distsdir, "hoary-test", "main", "source"))

        # XXX cprov 2007-03-21: see above, byte-to-byte configuration
        # comparing is weak.
        # Test that a publisher run now will generate an empty apt
        # config and nothing else.
        apt_conf = fa.generateConfig()
        assert len(file(apt_conf).readlines()) == 23

        # XXX cprov 2007-03-21: see above, do not run a-f on dev machines.
        assert fa.runApt(apt_conf) == 0

    def testGenerateConfigEmptyCareful(self):
        """Generate apt-ftparchive config for an specific empty suite.

        By passing 'careful_apt' option associated with 'allowed_suite'
        we can publish only a specific group of the suites even if they
        are still empty. It makes APT clients happier during development
        cycle.

        This test should check:

          * if apt.conf was generated correctly.
          * a-f runs based on this config without any errors
          * a-f *only* creates the wanted archive indexes.
        """
        from canonical.archivepublisher.ftparchive import FTPArchiveHandler
        from canonical.archivepublisher.publishing import Publisher

        allowed_suites = set()
        allowed_suites.add(('hoary-test', PackagePublishingPocket.UPDATES))

        publisher = Publisher(
            self._logger, self._config, self._dp,
            allowed_suites=allowed_suites, archive=self._archive)

        fa = FTPArchiveHandler(self._logger, self._config, self._dp,
                               self._distribution, publisher)

        fa.createEmptyPocketRequests(fullpublish=True)

        # XXX cprov 2007-03-21: see above, byte-to-byte configuration
        # comparing is weak.
        apt_conf = fa.generateConfig(fullpublish=True)
        self.assertTrue(os.path.exists(apt_conf))
        apt_conf_content = file(apt_conf).read()
        sample_content = file(
            os.path.join(
            self._sampledir, 'apt_conf_single_empty_suite_test')).read()
        self.assertEqual(apt_conf_content, sample_content)

        # XXX cprov 2007-03-21: see above, do not run a-f on dev machines.
        self.assertEqual(fa.runApt(apt_conf), 0)
        self.assertTrue(os.path.exists(
            os.path.join(self._distsdir, "hoary-test-updates", "main",
                         "binary-i386", "Packages")))
        self.assertTrue(os.path.exists(
            os.path.join(self._distsdir, "hoary-test-updates", "main",
                         "source", "Sources")))

        self.assertFalse(os.path.exists(
            os.path.join(self._distsdir, "hoary-test", "main",
                         "binary-i386", "Packages")))
        self.assertFalse(os.path.exists(
            os.path.join(self._distsdir, "hoary-test", "main",
                         "source", "Sources")))


class TestFTouch(unittest.TestCase):
    """Tests for f_touch function."""

    def setUp(self):
        self.test_folder = mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_folder)

    def testNewFile(self):
        """Test f_touch correctly creates a new file."""
        from canonical.archivepublisher.ftparchive import f_touch

        f_touch(self.test_folder, "file_to_touch")
        self.assertTrue(os.path.exists("%s/file_to_touch" % self.test_folder))

    def testExistingFile(self):
        """Test f_touch truncates existing files."""
        from canonical.archivepublisher.ftparchive import f_touch

        f = open("%s/file_to_truncate" % self.test_folder, "w")
        test_contents = "I'm some test contents"
        f.write(test_contents)
        f.close()

        f_touch(self.test_folder, "file_to_leave_alone")

        f = open("%s/file_to_leave_alone" % self.test_folder, "r")
        contents = f.read()
        f.close()

        self.assertEqual("", contents)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

