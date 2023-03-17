# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Functional tests for process-death-row.py script.

See lib/lp/archivepublisher/tests/deathrow.rst for more detailed tests
of the module functionality; here we just aim to test that the script
processes its arguments and handles dry-run correctly.
"""

import os
import shutil
import subprocess
from datetime import datetime, timezone
from tempfile import mkdtemp

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.archivepublisher.scripts.processdeathrow import DeathRowProcessor
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.person import IPersonSet
from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.soyuz.enums import PackagePublishingStatus
from lp.soyuz.model.publishing import SourcePackagePublishingHistory
from lp.testing import TestCaseWithFactory
from lp.testing.layers import LaunchpadZopelessLayer


class TestProcessDeathRow(TestCaseWithFactory):
    """Test the process-death-row.py script works properly."""

    layer = LaunchpadZopelessLayer

    def runDeathRow(self, extra_args, distribution="ubuntutest"):
        """Run process-death-row.py, returning the result and output."""
        script = os.path.join(config.root, "scripts", "process-death-row.py")
        args = [script, "-v", "-p", self.primary_test_folder]
        args.extend(extra_args)
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()
        err_msg = "process-deathrow returned %s:\n%s" % (
            process.returncode,
            stderr,
        )
        self.assertEqual(process.returncode, 0, err_msg)

        return (process.returncode, stdout, stderr)

    def setUp(self):
        """Set up for a test death row run."""
        super().setUp()
        self.setupPrimaryArchive()
        self.setupPPA()

        # Commit so script can see our publishing record changes.
        self.layer.txn.commit()

    def tearDown(self):
        """Clean up after ourselves."""
        self.tearDownPrimaryArchive()
        self.tearDownPPA()
        super().tearDown()

    def setupPrimaryArchive(self):
        """Create pending removal publications in ubuntutest PRIMARY archive.

        Also places the respective content in disk, so it can be removed
        and verified.
        """
        ubuntutest = getUtility(IDistributionSet)["ubuntutest"]
        self.factory.makeDistroSeriesParent(
            derived_series=ubuntutest.currentseries
        )
        ut_alsautils = ubuntutest.getSourcePackage("alsa-utils")
        ut_alsautils_109a4 = ut_alsautils.getVersion("1.0.9a-4")
        primary_pubrecs = ut_alsautils_109a4.publishing_history
        self.primary_pubrec_ids = self.markPublishingForRemoval(
            primary_pubrecs
        )

        self.primary_test_folder = mkdtemp()
        package_folder = os.path.join(
            self.primary_test_folder, "main", "a", "alsa-utils"
        )
        os.makedirs(package_folder)

        self.primary_package_path = os.path.join(
            package_folder, "alsa-utils_1.0.9a-4.dsc"
        )

        self.writeContent(self.primary_package_path)

    def tearDownPrimaryArchive(self):
        shutil.rmtree(self.primary_test_folder)

    def setupPPA(self):
        """Create pending removal publications in cprov PPA.

        Firstly, transform the cprov & mark PPAs in a ubuntutest PPA,
        since ubuntu publish configuration is broken in the sampledata.

        Also create one respective file in disk, so it can be removed and
        verified.
        """
        ubuntutest = getUtility(IDistributionSet)["ubuntutest"]

        cprov = getUtility(IPersonSet).getByName("cprov")
        removeSecurityProxy(cprov.archive).distribution = ubuntutest
        ppa_pubrecs = cprov.archive.getPublishedSources("iceweasel")
        self.ppa_pubrec_ids = self.markPublishingForRemoval(ppa_pubrecs)

        mark = getUtility(IPersonSet).getByName("mark")
        removeSecurityProxy(mark.archive).distribution = ubuntutest
        ppa_pubrecs = mark.archive.getPublishedSources("iceweasel")
        self.ppa_pubrec_ids.extend(self.markPublishingForRemoval(ppa_pubrecs))

        # Fill one of the files in cprov PPA just to ensure that deathrow
        # will be able to remove it. The other files can remain missing
        # in order to test if deathrow can cope with not-found files.
        self.ppa_test_folder = os.path.join(
            config.personalpackagearchive.root, "cprov", cprov.archive.name
        )
        package_folder = os.path.join(
            self.ppa_test_folder, "ubuntutest/pool/main/i/iceweasel"
        )
        os.makedirs(package_folder)
        self.ppa_package_path = os.path.join(
            package_folder, "iceweasel-1.0.dsc"
        )
        self.writeContent(self.ppa_package_path)

    def tearDownPPA(self):
        shutil.rmtree(self.ppa_test_folder)

    def writeContent(self, path, content="whatever"):
        f = open(path, "w")
        f.write("This is some test file contents")
        f.close()

    def markPublishingForRemoval(self, pubrecs):
        """Mark the given publishing record for removal."""
        pubrec_ids = []
        for pubrec in pubrecs:
            pubrec.status = PackagePublishingStatus.SUPERSEDED
            pubrec.dateremoved = None
            pubrec.scheduleddeletiondate = datetime(
                1999, 1, 1, tzinfo=timezone.utc
            )
            pubrec_ids.append(pubrec.id)
        return pubrec_ids

    def probePublishingStatus(self, pubrec_ids, status):
        """Check if all source publishing records match the given status."""
        store = IStore(SourcePackagePublishingHistory)
        for pubrec_id in pubrec_ids:
            spph = store.get(SourcePackagePublishingHistory, pubrec_id)
            self.assertEqual(
                spph.status,
                status,
                "ID %s -> %s (expected %s)"
                % (spph.id, spph.status.title, status.title),
            )

    def probeRemoved(self, pubrec_ids):
        """Check if all source publishing records were removed."""
        store = IStore(SourcePackagePublishingHistory)
        right_now = datetime.now(timezone.utc)
        for pubrec_id in pubrec_ids:
            spph = store.get(SourcePackagePublishingHistory, pubrec_id)
            self.assertTrue(
                spph.dateremoved < right_now,
                "ID %s -> not removed" % (spph.id),
            )

    def probeNotRemoved(self, pubrec_ids):
        """Check if all source publishing records were not removed."""
        store = IStore(SourcePackagePublishingHistory)
        for pubrec_id in pubrec_ids:
            spph = store.get(SourcePackagePublishingHistory, pubrec_id)
            self.assertTrue(
                spph.dateremoved is None, "ID %s -> removed" % (spph.id)
            )

    def test_getTargetArchives_ppa(self):
        """With --ppa, getTargetArchives returns all non-empty PPAs."""
        ubuntutest = getUtility(IDistributionSet)["ubuntutest"]
        cprov_archive = getUtility(IPersonSet).getByName("cprov").archive
        mark_archive = getUtility(IPersonSet).getByName("mark").archive
        # Private PPAs are included too.
        private_archive = self.factory.makeArchive(
            distribution=ubuntutest, private=True
        )
        self.factory.makeSourcePackagePublishingHistory(
            archive=private_archive
        )
        # Empty PPAs are skipped.
        self.factory.makeArchive(distribution=ubuntutest)
        script = DeathRowProcessor(test_args=["-d", "ubuntutest", "--ppa"])
        self.assertContentEqual(
            [cprov_archive, mark_archive, private_archive],
            script.getTargetArchives(ubuntutest),
        )

    def test_getTargetArchives_main(self):
        """Without --ppa, getTargetArchives returns main archives."""
        ubuntutest = getUtility(IDistributionSet)["ubuntutest"]
        script = DeathRowProcessor(test_args=["-d", "ubuntutest"])
        self.assertContentEqual(
            ubuntutest.all_distro_archives,
            script.getTargetArchives(ubuntutest),
        )

    def testDryRun(self):
        """Test we don't delete the file or change the db in dry run mode."""
        self.runDeathRow(["-d", "ubuntutest", "-n"])
        self.assertTrue(os.path.exists(self.primary_package_path))
        self.assertTrue(os.path.exists(self.ppa_package_path))

        self.probePublishingStatus(
            self.primary_pubrec_ids, PackagePublishingStatus.SUPERSEDED
        )
        self.probeNotRemoved(self.primary_pubrec_ids)
        self.probePublishingStatus(
            self.ppa_pubrec_ids, PackagePublishingStatus.SUPERSEDED
        )
        self.probeNotRemoved(self.ppa_pubrec_ids)

    def testWetRun(self):
        """Test we do delete the file and change the db in wet run mode."""
        self.runDeathRow(["-d", "ubuntutest"])
        self.assertFalse(os.path.exists(self.primary_package_path))
        self.assertTrue(os.path.exists(self.ppa_package_path))

        self.probePublishingStatus(
            self.primary_pubrec_ids, PackagePublishingStatus.SUPERSEDED
        )
        self.probeRemoved(self.primary_pubrec_ids)
        self.probePublishingStatus(
            self.ppa_pubrec_ids, PackagePublishingStatus.SUPERSEDED
        )
        self.probeNotRemoved(self.ppa_pubrec_ids)

    def testPPARun(self):
        """Test we only work upon PPA."""
        self.runDeathRow(["-d", "ubuntutest", "--ppa"])

        self.assertTrue(os.path.exists(self.primary_package_path))
        self.assertFalse(os.path.exists(self.ppa_package_path))

        self.probePublishingStatus(
            self.primary_pubrec_ids, PackagePublishingStatus.SUPERSEDED
        )
        self.probeNotRemoved(self.primary_pubrec_ids)
        self.probePublishingStatus(
            self.ppa_pubrec_ids, PackagePublishingStatus.SUPERSEDED
        )
        self.probeRemoved(self.ppa_pubrec_ids)

    def testDerivedRun(self):
        self.runDeathRow([])
        self.assertTrue(os.path.exists(self.primary_package_path))
        self.assertTrue(os.path.exists(self.ppa_package_path))
        self.runDeathRow(["--all-derived"])
        self.assertFalse(os.path.exists(self.primary_package_path))
        self.assertTrue(os.path.exists(self.ppa_package_path))
        self.runDeathRow(["--all-derived", "--ppa"])
        self.assertFalse(os.path.exists(self.primary_package_path))
        self.assertFalse(os.path.exists(self.ppa_package_path))
