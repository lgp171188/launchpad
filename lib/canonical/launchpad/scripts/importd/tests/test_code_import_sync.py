# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Test cases for canonical.launchpad.scripts.importd.code_import_sync."""

__metaclass__ = type
__all__ = ['test_suite']


import datetime
import logging
import pytz
import unittest

from zope.component import getUtility

from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.database import CodeImport, ProductSeries, ProductSet
from canonical.launchpad.ftests.harness import LaunchpadZopelessTestCase
from canonical.launchpad.interfaces import (
    IBranchSet, ICodeImportSet, IProductSet)
from canonical.launchpad.scripts.importd.code_import_sync import CodeImportSync
from canonical.launchpad.utilities import LaunchpadCelebrities
from canonical.lp.dbschema import (
    CodeImportReviewStatus, ImportStatus, RevisionControlSystems)


UTC = pytz.timezone('UTC')


class CodeImportSyncTestCase(LaunchpadZopelessTestCase):

    def setUp(self):
        self.cleanUpSampleData()
        self.firefox = ProductSet().getByName('firefox')
        self.code_import_sync = CodeImportSync(logging, self.layer.txn)

    def cleanUpSampleData(self):
        """Clear out the sample data that would affect tests."""
        all_import_series = ProductSeries.select("importstatus IS NOT NULL")
        for import_series in all_import_series:
            import_series.deleteImport()
        all_code_imports = CodeImport.select()
        for code_import in all_code_imports:
            code_import.destroySelf()

    def createTestingSeries(self, name):
        """Create an import series in with TESTING importstatus."""
        product = self.firefox
        series = product.newSeries(product.owner, name, name)
        series.importstatus = ImportStatus.TESTING
        series.rcstype = RevisionControlSystems.SVN
        series.svnrepository = 'svn://example.com/' + name

        # ProductSeries may have datelastsynced for any importstatus, but it
        # must only be copied to the CodeImport in some cases.
        series.datelastsynced = datetime.datetime(
            2000, 1, 1, 0, 0, 0, tzinfo=UTC)

        return series

    def createImportBranch(self, series):
        """Create an import branch and associate it to an import series."""
        vcs_imports = LaunchpadCelebrities().vcs_imports
        branch = getUtility(IBranchSet).new(
            series.name, vcs_imports, series.product, None)
        series.import_branch = branch
        return branch

    def assertImportMatchesSeries(self, code_import, series):
        """Fail if the CodeImport is not consistent with the ProductSeries."""
        # A CodeImport must have the same database id as its corresponding
        # series.
        self.assertEqual(code_import.id, series.id)

        # Since ProductSeries does not record who requested an import, all
        # CodeImports created by the sync script are recorded as registered by
        # the vcs-imports user.
        self.assertEqual(code_import.registrant.name, u'vcs-imports')

        # The VCS details must be identical.
        self.assertEqual(code_import.rcs_type, series.rcstype)
        self.assertEqual(code_import.svn_branch_url, series.svnrepository)
        self.assertEqual(code_import.cvs_root, series.cvsroot)
        self.assertEqual(code_import.cvs_module, series.cvsmodule)

        # dateLastSuccessfulFromProductSeries is carefully unit-testing in
        # TestDateLastSuccessfulFromProductSeries, so we can rely on it here.
        assert series.datelastsynced is not None # Test suite invariant.
        last_successful = \
            self.code_import_sync.dateLastSuccessfulFromProductSeries(series)
        self.assertEqual(code_import.date_last_successful, last_successful)

        # reviewStatusFromImportStatus is carefully unit-tested in
        # TestReviewStatusFromImportStatus, so we can rely on it here.
        review_status = self.code_import_sync.reviewStatusFromImportStatus(
            series.importstatus)
        self.assertEqual(code_import.review_status, review_status)

        # If series.import_branch is set, it should be the same as
        # code_import.branch.
        if series.import_branch is not None:
            self.assertEqual(code_import.branch, series.import_branch)


class TestGetImportSeries(CodeImportSyncTestCase):
    """Unit tests for CodeImportSync.getImportSeries."""

    def assertListSingleItemEquals(self, the_list, expected_item):
        """Fail if the_list does not have expected_item has its single item."""
        self.assertEqual(len(the_list), 1)
        [the_item] = the_list
        self.assertEqual(the_item, expected_item)

    def testEmpty(self):
        # If there is no series with importstatus set, getImportSeries gives an
        # empty iterable. This would never happen in real life.
        flush_database_updates()
        self.assertEqual(list(self.code_import_sync.getImportSeries()), [])

    def testTesting(self):
        # getImportSeries yields series with TESTING importstatus.
        testing = self.createTestingSeries('testing')
        flush_database_updates()
        import_series_set = list(self.code_import_sync.getImportSeries())
        self.assertListSingleItemEquals(import_series_set, testing)

    # TODO: test correct filtering for all importstatus.

    # TODO: test that non-MAIN cvs branches are ignored, CodeImport does not
    # have a cvs_branch attribute.


class TestReviewStatusFromImportStatus(unittest.TestCase):
    """Unit tests for reviewStatusFromImportStatus."""

    def setUp(self):
        # reviewStatusFromImportStatus does not need database access.
        self.code_import_sync = CodeImportSync(logging, None)

    def assertImportStatusTranslatesTo(self, import_status, expected):
        """Assert that reviewStatusFromImportStatus returns `expected`
        when passed `import_status`.
        """
        review_status = self.code_import_sync.reviewStatusFromImportStatus(
            import_status)
        self.assertEqual(review_status, expected)

    def assertImportStatusDoesNotTranslate(self, import_status):
        """Assert that reviewFromImportStatus raises AssertionError when passed
        `import_status`.
        """
        self.assertRaises(AssertionError,
            self.code_import_sync.reviewStatusFromImportStatus, import_status)

    def testDontsync(self):
        self.assertImportStatusDoesNotTranslate(ImportStatus.DONTSYNC)

    def testTesting(self):
        self.assertImportStatusTranslatesTo(
            ImportStatus.TESTING, CodeImportReviewStatus.NEW)

    def testTestfailed(self):
        self.assertImportStatusDoesNotTranslate(ImportStatus.TESTFAILED)

    def testAutotested(self):
        self.assertImportStatusTranslatesTo(
            ImportStatus.AUTOTESTED, CodeImportReviewStatus.NEW)

    def testProcessing(self):
        self.assertImportStatusTranslatesTo(
            ImportStatus.PROCESSING, CodeImportReviewStatus.REVIEWED)

    def testSyncing(self):
        self.assertImportStatusTranslatesTo(
            ImportStatus.SYNCING, CodeImportReviewStatus.REVIEWED)

    def testStopped(self):
        self.assertImportStatusTranslatesTo(
            ImportStatus.STOPPED, CodeImportReviewStatus.SUSPENDED)


class StubProductSeries:
    """Stub ProductSeries class used in unit tests."""
    pass


class TestDateLastSuccessfulFromProductSeries(unittest.TestCase):

    def setUp(self):
        # dateLastSuccessfulFromProductSeries does not need database access.
        self.code_import_sync = CodeImportSync(logging, None)

    def makeStubSeries(self, import_status):
        """Create a stub ProductSeries with a datelastsynced and the given
        import status.
        """
        series = StubProductSeries()
        series.importstatus = import_status
        series.datelastsynced = datetime.datetime(
            2000, 1, 1, 0, 0, 0, tzinfo=UTC)
        return series

    def assertDateLastSuccessfulIsReturned(self, import_status):
        """Assert that dateLastSuccessfulFromProductSeries returns
        datelastsynced for a ProductSeries with the given `import_status`.
        """
        series = self.makeStubSeries(import_status)
        date_last_successful = \
            self.code_import_sync.dateLastSuccessfulFromProductSeries(series)
        self.assertEqual(date_last_successful, series.datelastsynced)

    def assertNoneIsReturned(self, import_status):
        """Assert that dateLastSuccesfulFromProductSeries return None for a
        ProductSeries with the given `import_status`.
        """
        series = self.makeStubSeries(import_status)
        date_last_successful = \
            self.code_import_sync.dateLastSuccessfulFromProductSeries(series)
        self.assertEqual(date_last_successful, None)

    def assertAssertionErrorRaised(self, import_status):
        """Assort that dateLastSuccessfulFromProductSeries raises an
        AssertionError for a ProductSeries with the given `import_status`.
        """
        series = self.makeStubSeries(import_status)
        self.assertRaises(AssertionError,
            self.code_import_sync.dateLastSuccessfulFromProductSeries, series)

    def testDontsync(self):
        self.assertAssertionErrorRaised(ImportStatus.DONTSYNC)

    def testTesting(self):
        self.assertNoneIsReturned(ImportStatus.TESTING)

    def testFailed(self):
        self.assertAssertionErrorRaised(ImportStatus.TESTFAILED)

    def testAutotested(self):
        self.assertNoneIsReturned(ImportStatus.AUTOTESTED)

    def testProcessing(self):
        self.assertNoneIsReturned(ImportStatus.PROCESSING)

    def testSyncing(self):
        self.assertDateLastSuccessfulIsReturned(ImportStatus.SYNCING)

    def testStopped(self):
        self.assertDateLastSuccessfulIsReturned(ImportStatus.STOPPED)



class TestCreateCodeImport(CodeImportSyncTestCase):
    """Unit tests for CodeImportSync.createCodeImport."""

    def testTesting(self):
        testing = self.createTestingSeries('testing')
        code_import = self.code_import_sync.createCodeImport(testing)
        self.assertImportMatchesSeries(code_import, testing)


class TestCodeImportSync(CodeImportSyncTestCase):
    """Feature tests for CodeImportSync."""

    def run_code_import_sync(self):
        """Run the code-import-sync, and flush database updates as needed."""
        flush_database_updates()
        self.code_import_sync.run()
        flush_database_updates()

    def assertSingleCodeImportMatchesSeries(self, series):
        """Fail unless there is a single CodeImport object and it matches
        series.
        """
        all_imports = list(getUtility(ICodeImportSet).getAll())
        self.assertEqual(len(all_imports), 1)
        [code_import] = all_imports
        self.assertImportMatchesSeries(code_import, series)

    def testNewTesting(self):
        # A new TESTING series causes the creation of a new code import with
        # NEW review status.
        testing = self.createTestingSeries('testing')
        self.run_code_import_sync()
        self.assertSingleCodeImportMatchesSeries(testing)

    def testNewProcessing(self):
        # A new PROCESSING series causes the creation of a new code import with
        # REVIEWED review status.
        processing = self.createTestingSeries('processing')
        processing.certifyForSync()
        self.assertEqual(processing.importstatus, ImportStatus.PROCESSING)
        self.run_code_import_sync()
        self.assertSingleCodeImportMatchesSeries(processing)

    def testNewSyncing(self):
        # A new SYNCING series causes the creation of a new code import with
        # REVIEWED review status and a non-NULL date_last_succesful.
        syncing = self.createTestingSeries('syncing')
        syncing.certifyForSync()
        syncing.enableAutoSync()
        self.assertEqual(syncing.importstatus, ImportStatus.SYNCING)
        self.createImportBranch(syncing)
        self.run_code_import_sync()
        self.assertSingleCodeImportMatchesSeries(syncing)

    def testUpdateProcessingToSyncing(self):
        # When a code import is created for a PROCESSING series, and the series
        # is ugraded to SYNCING, the code import can be correctly updated.
        series = self.createTestingSeries('processing-syncing')
        series.certifyForSync()
        self.assertEqual(series.importstatus, ImportStatus.PROCESSING)
        self.run_code_import_sync()
        series.enableAutoSync()
        self.assertEqual(series.importstatus, ImportStatus.SYNCING)

        # When code-import-sync runs in production, importd will need to use
        # the CodeImport's branch to publish the import.
        code_import = CodeImport.get(series.id) # Error if object not found.
        series.import_branch = code_import.branch

        self.run_code_import_sync()
        self.assertSingleCodeImportMatchesSeries(series)


    # TODO: test that CVS imports are correctly created and updated. All the
    # basic tests are done on SVN imports.

    # TODO: test updates to VCS details, CVS->SVN and SVN->CVS

    # TODO: test deletion of code-import


    def testGetImportSeries(self):
        # getImportSeries should select all ProductSeries whose importstatus is
        # TESTING, AUTOTESTED, PROCESSING, SYNCING or STOPPED. ProductSeries
        # whose status is DONTSYNC or TESTFAILED are ignored.

        # Create a series with importstatus = TESTFAILED
        testfailed = self.createTestingSeries('testfailed')
        testfailed.markTestFailed()

        # Create a series with importstatus = AUTOTESTED
        autotested = self.createTestingSeries('autotested')
        autotested.importstatus = ImportStatus.AUTOTESTED

        # Create a series with importstatus = DONTSYNC
        dontsync = self.createTestingSeries('dontsync')
        dontsync.markDontSync()

        # Create a series with importstatus = STOPPED
        stopped = self.createTestingSeries('stopped')
        stopped.certifyForSync()
        stopped.enableAutoSync()
        stopped_branch = self.createImportBranch(stopped)
        stopped.importstatus = ImportStatus.STOPPED


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
