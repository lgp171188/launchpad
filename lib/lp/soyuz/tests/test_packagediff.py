# Copyright 2010-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test source package diffs."""

import io
import os.path
from datetime import datetime, timezone
from textwrap import dedent

import transaction
from fixtures import EnvironmentVariableFixture
from storm.expr import And
from zope.security.proxy import removeSecurityProxy
from zope.testbrowser.browser import LinkNotFoundError

from lp.archivepublisher.config import ArchivePurpose
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormexpr import BulkUpdate
from lp.services.job.interfaces.job import JobType
from lp.services.job.model.job import Job
from lp.services.librarian.client import ILibrarianClient
from lp.services.librarian.model import LibraryFileAlias
from lp.soyuz.enums import PackageDiffStatus
from lp.soyuz.model.files import SourcePackageReleaseFile
from lp.testing import (
    BrowserTestCase,
    TestCaseWithFactory,
    getUtility,
    login_person,
)
from lp.testing.dbuser import dbuser
from lp.testing.layers import LaunchpadFunctionalLayer, LaunchpadZopelessLayer
from lp.testing.pages import extract_text


def create_proper_job(factory, sourcepackagename=None):
    archive = factory.makeArchive()
    foo_dash1 = factory.makeSourcePackageRelease(
        archive=archive, sourcepackagename=sourcepackagename
    )
    foo_dash15 = factory.makeSourcePackageRelease(
        archive=archive, sourcepackagename=sourcepackagename
    )
    add_files_to_sources(factory, foo_dash1, foo_dash15)
    return foo_dash1.requestDiffTo(factory.makePerson(), foo_dash15)


def add_files_to_sources(factory, source_1, source_2):
    suite_dir = "lib/lp/archiveuploader/tests/data/suite"
    files = {
        "%s/foo_1.0-1/foo_1.0-1.diff.gz" % suite_dir: None,
        "%s/foo_1.0-1/foo_1.0-1.dsc" % suite_dir: None,
        "%s/foo_1.0-1/foo_1.0.orig.tar.gz" % suite_dir: None,
        "%s/foo_1.0-1.5/foo_1.0-1.5.diff.gz" % suite_dir: None,
        "%s/foo_1.0-1.5/foo_1.0-1.5.dsc" % suite_dir: None,
    }
    for name in files:
        filename = os.path.split(name)[-1]
        with open(name, "rb") as content:
            files[name] = factory.makeLibraryFileAlias(
                filename=filename, content=content.read()
            )
    transaction.commit()
    dash1_files = (
        "%s/foo_1.0-1/foo_1.0-1.diff.gz" % suite_dir,
        "%s/foo_1.0-1/foo_1.0-1.dsc" % suite_dir,
        "%s/foo_1.0-1/foo_1.0.orig.tar.gz" % suite_dir,
    )
    dash15_files = (
        "%s/foo_1.0-1/foo_1.0.orig.tar.gz" % suite_dir,
        "%s/foo_1.0-1.5/foo_1.0-1.5.diff.gz" % suite_dir,
        "%s/foo_1.0-1.5/foo_1.0-1.5.dsc" % suite_dir,
    )
    for name in dash1_files:
        source_1.addFile(files[name])
    for name in dash15_files:
        source_2.addFile(files[name])


class TestPackageDiffs(TestCaseWithFactory):
    """Test package diffs."""

    layer = LaunchpadZopelessLayer
    dbuser = config.uploader.dbuser

    def test_packagediff_working(self):
        # Test the case where none of the files required for the diff are
        # expired in the librarian and where everything works as expected.
        diff = create_proper_job(self.factory)
        self.assertEqual(0, removeSecurityProxy(diff)._countDeletedLFAs())
        diff.performDiff()
        self.assertEqual(PackageDiffStatus.COMPLETED, diff.status)

    def expireLFAsForSource(self, source, expire=True, delete=True):
        """Expire the files associated with the given source package in the
        librarian."""
        assert expire or delete
        update_map = {}
        if expire:
            update_map[LibraryFileAlias.expires] = datetime.now(timezone.utc)
        if delete:
            update_map[LibraryFileAlias.content_id] = None
        with dbuser("launchpad"):
            IStore(LibraryFileAlias).execute(
                BulkUpdate(
                    update_map,
                    table=LibraryFileAlias,
                    values=SourcePackageReleaseFile,
                    where=And(
                        SourcePackageReleaseFile.sourcepackagerelease
                        == source,
                        SourcePackageReleaseFile.libraryfile
                        == LibraryFileAlias.id,
                    ),
                )
            )

    def test_packagediff_with_expired_and_deleted_lfas(self):
        # Test the case where files required for the diff are expired *and*
        # deleted in the librarian causing a package diff failure.
        diff = create_proper_job(self.factory)
        self.expireLFAsForSource(diff.from_source)
        self.assertEqual(4, removeSecurityProxy(diff)._countDeletedLFAs())
        diff.performDiff()
        self.assertEqual(PackageDiffStatus.FAILED, diff.status)

    def test_packagediff_with_expired_but_not_deleted_lfas(self):
        # Test the case where files required for the diff are expired but
        # not deleted in the librarian still allowing the package diff to be
        # performed.
        diff = create_proper_job(self.factory)
        # Expire but don't delete the files associated with the 'from_source'
        # package.
        self.expireLFAsForSource(diff.from_source, expire=True, delete=False)
        self.assertEqual(0, removeSecurityProxy(diff)._countDeletedLFAs())
        diff.performDiff()
        self.assertEqual(PackageDiffStatus.COMPLETED, diff.status)

    def test_packagediff_with_deleted_but_not_expired_lfas(self):
        # Test the case where files required for the diff have been
        # deleted explicitly, not through expiry.
        diff = create_proper_job(self.factory)
        self.expireLFAsForSource(diff.from_source, expire=False, delete=True)
        self.assertEqual(4, removeSecurityProxy(diff)._countDeletedLFAs())
        diff.performDiff()
        self.assertEqual(PackageDiffStatus.FAILED, diff.status)

    def test_packagediff_private_with_copied_spr(self):
        # If an SPR has been copied from a private archive to a public
        # archive, diffs against it are public.
        p3a = self.factory.makeArchive(private=True)
        orig_spr = self.factory.makeSourcePackageRelease(archive=p3a)
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=p3a, sourcepackagerelease=orig_spr
        )
        private_spr = self.factory.makeSourcePackageRelease(archive=p3a)
        private_diff = private_spr.requestDiffTo(p3a.owner, orig_spr)
        self.assertEqual(1, len(orig_spr.published_archives))
        self.assertTrue(private_diff.private)
        ppa = self.factory.makeArchive(owner=p3a.owner)
        spph.copyTo(spph.distroseries, spph.pocket, ppa)
        self.assertEqual(2, len(orig_spr.published_archives))
        public_spr = self.factory.makeSourcePackageRelease(archive=ppa)
        public_diff = public_spr.requestDiffTo(p3a.owner, orig_spr)
        self.assertFalse(public_diff.private)

    def test_packagediff_public_unpublished(self):
        # If an SPR has been uploaded to a public archive but not yet
        # published, diffs to it are public.
        ppa = self.factory.makeArchive()
        from_spr = self.factory.makeSourcePackageRelease(archive=ppa)
        to_spr = self.factory.makeSourcePackageRelease(archive=ppa)
        diff = from_spr.requestDiffTo(ppa.owner, to_spr)
        self.assertFalse(diff.private)

    def test_job_created(self):
        # Requesting a package diff creates a PackageDiffJob.
        ppa = self.factory.makeArchive()
        from_spr = self.factory.makeSourcePackageRelease(archive=ppa)
        to_spr = self.factory.makeSourcePackageRelease(archive=ppa)
        from_spr.requestDiffTo(ppa.owner, to_spr)
        [job] = IStore(Job).find(
            Job, Job.base_job_type == JobType.GENERATE_PACKAGE_DIFF
        )
        self.assertIsNot(None, job)

    def test_packagediff_timeout(self):
        # debdiff is killed after the time limit expires.
        self.pushConfig("packagediff", debdiff_timeout=1)
        temp_dir = self.makeTemporaryDirectory()
        mock_debdiff_path = os.path.join(temp_dir, "debdiff")
        marker_path = os.path.join(temp_dir, "marker")
        with open(mock_debdiff_path, "w") as mock_debdiff:
            print(
                dedent(
                    """\
                #! /bin/sh
                # Make sure we don't rely on the child leaving its SIGALRM
                # disposition undisturbed.
                trap '' ALRM
                (echo "$$"; echo "$TMPDIR") >%s
                sleep 5
                """
                    % marker_path
                ),
                end="",
                file=mock_debdiff,
            )
        os.chmod(mock_debdiff_path, 0o755)
        mock_path = "%s:%s" % (temp_dir, os.environ["PATH"])
        diff = create_proper_job(self.factory)
        with EnvironmentVariableFixture("PATH", mock_path):
            diff.performDiff()
        self.assertEqual(PackageDiffStatus.FAILED, diff.status)
        with open(marker_path) as marker:
            debdiff_pid = int(marker.readline())
            debdiff_tmpdir = marker.readline().rstrip("\n")
            self.assertRaises(ProcessLookupError, os.kill, debdiff_pid, 0)
            self.assertFalse(os.path.exists(debdiff_tmpdir))

    def test_packagediff_max_size(self):
        # debdiff is killed if it generates more than the size limit.
        self.pushConfig("packagediff", debdiff_max_size=1024)
        temp_dir = self.makeTemporaryDirectory()
        mock_debdiff_path = os.path.join(temp_dir, "debdiff")
        marker_path = os.path.join(temp_dir, "marker")
        with open(mock_debdiff_path, "w") as mock_debdiff:
            print(
                dedent(
                    """\
                #! /bin/sh
                (echo "$$"; echo "$TMPDIR") >%s
                yes | head -n2048 || exit 2
                sleep 5
                """
                    % marker_path
                ),
                end="",
                file=mock_debdiff,
            )
        os.chmod(mock_debdiff_path, 0o755)
        mock_path = "%s:%s" % (temp_dir, os.environ["PATH"])
        diff = create_proper_job(self.factory)
        with EnvironmentVariableFixture("PATH", mock_path):
            diff.performDiff()
        self.assertEqual(PackageDiffStatus.FAILED, diff.status)
        with open(marker_path) as marker:
            debdiff_pid = int(marker.readline())
            debdiff_tmpdir = marker.readline().rstrip("\n")
            self.assertRaises(ProcessLookupError, os.kill, debdiff_pid, 0)
            self.assertFalse(os.path.exists(debdiff_tmpdir))

    def test_packagediff_blacklist(self):
        # Package diff jobs for blacklisted package names do nothing.
        self.pushConfig("packagediff", blacklist="udev cordova-cli")
        diff = create_proper_job(self.factory, sourcepackagename="cordova-cli")
        diff.performDiff()
        self.assertEqual(PackageDiffStatus.FAILED, diff.status)


class TestPackageDiffsView(BrowserTestCase):
    """Test package diffs title."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.user = self.factory.makePerson()
        self.distroseries = self.factory.makeDistroSeries()
        self.distribution = self.distroseries.distribution

    def set_up_sources(self, same_archive=True, purpose=None):
        """Create the archives, spph and sources needed for the test cases"""
        # Create archives
        self.from_archive = self.factory.makeArchive(
            distribution=self.distribution,
            purpose=purpose,
            owner=self.user,
        )
        if same_archive:
            self.to_archive = self.from_archive
        else:
            self.to_archive = self.factory.makeArchive()

        # Create sources and spph
        self.from_source = self.factory.makeSourcePackageRelease(
            archive=self.from_archive,
            version="1.0-3",
        )
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=self.to_archive,
            version="1.0-4",
        )
        self.to_source = spph.sourcepackagerelease
        self.spph_id = spph.id
        add_files_to_sources(self.factory, self.from_source, self.to_source)

    def perform_fake_diff(self, diff, filename):
        """Complete a pending diff"""
        naked_diff = removeSecurityProxy(diff)
        naked_diff.date_fulfilled = UTC_NOW
        naked_diff.status = PackageDiffStatus.COMPLETED
        naked_diff.diff_content = getUtility(ILibrarianClient).addFile(
            filename, 3, io.BytesIO(b"Foo"), "application/gzipped-patch"
        )

    def assert_text_in_diffs_view(self, expected_text):
        """Verify that expected text exists in the packages diffs view"""
        login_person(self.user)
        browser = self.getViewBrowser(self.to_archive, "+packages")
        expander_id = f"pub{self.spph_id}-expander"
        browser.getLink(id=expander_id).click()
        self.assertIn(expected_text, extract_text(browser.contents))
        return browser

    def test_package_diffs_view_same_archive(self):
        """Compare different version sources from the same archive"""
        self.set_up_sources(same_archive=True)
        self.from_source.requestDiffTo(self.user, self.to_source)
        expected_text = "Available diffs\ndiff from 1.0-3 to 1.0-4 (pending)"
        self.assert_text_in_diffs_view(expected_text)

    def test_package_diffs_view_different_main_archives(self):
        """Compare sources from distinct archives with a primary purpose"""
        self.set_up_sources(same_archive=False, purpose=ArchivePurpose.PRIMARY)
        self.from_source.requestDiffTo(self.user, self.to_source)
        expected_text = (
            "Available diffs\ndiff from 1.0-3 (in {dis}) to 1.0-4 (pending)"
        ).format(dis=self.distribution.name.capitalize())
        self.assert_text_in_diffs_view(expected_text)

    def test_package_diffs_view_different_ppa_archives(self):
        """Compare sources from distinct archives with a ppa purpose"""
        self.set_up_sources(same_archive=False, purpose=ArchivePurpose.PPA)
        self.from_source.requestDiffTo(self.user, self.to_source)
        expected_text = (
            "Available diffs\ndiff from 1.0-3 (in ~{user}/{distribution}/"
            "{archive}) to 1.0-4 (pending)"
        ).format(
            user=self.user.name,
            distribution=self.distribution.name,
            archive=self.from_archive.name,
        )
        self.assert_text_in_diffs_view(expected_text)

    def test_package_diffs_view_links(self):
        """Diffs between sources from distinct archives with a ppa purpose,"""
        self.set_up_sources(same_archive=False, purpose=ArchivePurpose.PRIMARY)
        diff = self.from_source.requestDiffTo(self.user, self.to_source)
        expected_title = "diff from 1.0-3 (in {dis}) to 1.0-4".format(
            dis=self.distribution.name.capitalize()
        )

        # There is no link while diff is pending
        expected_text = f"Available diffs\n{expected_title} (pending)"
        browser = self.assert_text_in_diffs_view(expected_text)
        self.assertRaises(LinkNotFoundError, browser.getLink, expected_title)

        # There is a link after diff is completed
        login_person(self.user)
        self.perform_fake_diff(diff, "biscuit_1.0-3_1.0-4.diff.gz")
        transaction.commit()
        expected_text = f"Available diffs\n{expected_title} (3 bytes)"
        browser = self.assert_text_in_diffs_view(expected_text)
        url = browser.getLink(expected_title).url
        self.assertIn("/+files/biscuit_1.0-3_1.0-4.diff.gz", url)
