# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import gzip
import io
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import responses
from testtools.matchers import Contains
from zope.component import getUtility

from lp.bugs.interfaces.cve import CveStatus, ICveSet
from lp.bugs.scripts.cveimport import CVEUpdater
from lp.services.log.logger import DevNullLogger
from lp.services.scripts.base import LaunchpadScriptFailure
from lp.testing import TestCase
from lp.testing.layers import LaunchpadZopelessLayer


class TestCVEUpdater(TestCase):
    @responses.activate
    def test_fetch_uncompressed(self):
        # Fetching a URL returning uncompressed data works.
        url = "http://cve.example.com/allitems.xml"
        body = b'<?xml version="1.0"?>'
        responses.add(
            "GET", url, headers={"Content-Type": "text/xml"}, body=body
        )
        cve_updater = CVEUpdater(
            "cve-updater", test_args=[], logger=DevNullLogger()
        )
        self.assertEqual(body, cve_updater.fetchCVEURL(url))

    @responses.activate
    def test_fetch_content_encoding_gzip(self):
        # Fetching a URL returning Content-Encoding: gzip works.
        url = "http://cve.example.com/allitems.xml.gz"
        body = b'<?xml version="1.0"?>'
        gzipped_body_file = io.BytesIO()
        with gzip.GzipFile(fileobj=gzipped_body_file, mode="wb") as f:
            f.write(body)
        responses.add(
            "GET",
            url,
            headers={
                "Content-Type": "text/xml",
                "Content-Encoding": "gzip",
            },
            body=gzipped_body_file.getvalue(),
        )
        cve_updater = CVEUpdater(
            "cve-updater", test_args=[], logger=DevNullLogger()
        )
        self.assertEqual(body, cve_updater.fetchCVEURL(url))

    @responses.activate
    def test_fetch_gzipped(self):
        # Fetching a URL returning gzipped data without Content-Encoding works.
        url = "http://cve.example.com/allitems.xml.gz"
        body = b'<?xml version="1.0"?>'
        gzipped_body_file = io.BytesIO()
        with gzip.GzipFile(fileobj=gzipped_body_file, mode="wb") as f:
            f.write(body)
        responses.add(
            "GET",
            url,
            headers={"Content-Type": "application/x-gzip"},
            body=gzipped_body_file.getvalue(),
        )
        cve_updater = CVEUpdater(
            "cve-updater", test_args=[], logger=DevNullLogger()
        )
        self.assertEqual(body, cve_updater.fetchCVEURL(url))

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir)

    def create_test_json_cve(
        self, cve_id="2024-0001", description="Test description"
    ):
        """Helper to create a test CVE JSON file"""
        cve_data = {
            "dataType": "CVE_RECORD",
            "cveMetadata": {"cveId": f"CVE-{cve_id}"},
            "containers": {
                "cna": {
                    "descriptions": [{"lang": "en", "value": description}],
                    "references": [
                        {
                            "url": "http://example.com/ref1",
                            "name": "Reference 1",
                        }
                    ],
                }
            },
        }
        return cve_data

    def make_updater(self, test_args=None):
        """Helper to create a properly initialized CVEUpdater."""
        if test_args is None:
            test_args = []
        updater = CVEUpdater(
            "cve-updater", test_args=test_args, logger=DevNullLogger()
        )
        # Initialize just the database connection
        updater._init_db(isolation="read_committed")
        return updater

    def test_process_json_directory(self):
        """Test processing a directory of CVE JSON files."""
        # Create test directory structure
        base_dir = Path(self.temp_dir) / "cves"
        year_dir = base_dir / "2024"
        group_dir = year_dir / "0xxx"
        group_dir.mkdir(parents=True)

        # Create a test CVE file
        cve_file = group_dir / "CVE-2024-0001.json"
        cve_data = self.create_test_json_cve()
        cve_file.write_text(json.dumps(cve_data))

        # Process the directory using the script infrastructure
        updater = self.make_updater([str(base_dir)])
        processed, errors = updater.process_json_directory(str(base_dir))

        # Verify results
        self.assertEqual(1, processed)
        self.assertEqual(0, errors)

        # Verify CVE was created
        cveset = getUtility(ICveSet)
        cve = cveset["2024-0001"]
        self.assertIsNotNone(cve)
        self.assertEqual("Test description", cve.description)

    def test_process_json_directory_with_bigger_group_name(self):
        """Test processing a JSON CVE dir with sequence bigger than 9999.

        This test makes sure the regular expression used allows this group dirs
        and cve files.
        """
        # Create test directory structure
        base_dir = Path(self.temp_dir) / "cves"
        year_dir = base_dir / "2025"

        # CVE sequence number can be > 9999 so we can have groups like 10xxx
        # or 9000xxx. See cvelistV5/2014/1000xxx or 2024/56xxx
        group_dir = year_dir / "9000xxx"
        group_dir.mkdir(parents=True)

        # Create a test CVE file
        cve_file = group_dir / "CVE-2025-9000001.json"
        cve_data = self.create_test_json_cve(cve_id="2025-9000001")
        cve_file.write_text(json.dumps(cve_data))

        # Process the directory using the script infrastructure
        updater = self.make_updater([str(base_dir)])
        processed, errors = updater.process_json_directory(str(base_dir))

        # Verify results
        self.assertEqual(1, processed)
        self.assertEqual(0, errors)

        # Verify CVE was created
        cveset = getUtility(ICveSet)
        cve = cveset["2025-9000001"]
        self.assertIsNotNone(cve)
        self.assertEqual("Test description", cve.description)

    def test_process_delta_directory(self):
        """Test processing a directory of delta CVE files."""
        # Create test delta directory
        delta_dir = Path(self.temp_dir) / "deltaCves"
        delta_dir.mkdir()

        # Create a test delta CVE file
        cve_file = delta_dir / "CVE-2024-0002.json"
        cve_data = self.create_test_json_cve(
            cve_id="2024-0002", description="Delta CVE"
        )
        cve_file.write_text(json.dumps(cve_data))

        # Process the directory using the script infrastructure
        updater = self.make_updater([str(delta_dir)])
        processed, errors = updater.process_delta_directory(str(delta_dir))

        # Verify results
        self.assertEqual(1, processed)
        self.assertEqual(0, errors)

        # Verify CVE was created
        cveset = getUtility(ICveSet)
        cve = cveset["2024-0002"]
        self.assertIsNotNone(cve)
        self.assertEqual("Delta CVE", cve.description)

    def test_construct_github_url(self):
        """Test GitHub URL construction for different scenarios."""
        updater = CVEUpdater(
            "cve-updater", test_args=[], logger=DevNullLogger()
        )

        # Test baseline URL
        url = updater.construct_github_url(delta=False)
        expected = "_all_CVEs_at_midnight.zip"
        self.assertThat(url, Contains(expected))

        # Test delta URL (normal hour)
        url = updater.construct_github_url(delta=True)
        current_hour = datetime.now(timezone.utc).hour
        if current_hour not in (0, 23):
            expected = f"_delta_CVEs_at_{current_hour:02d}00Z.zip"
            self.assertThat(url, Contains(expected))

    def test_invalid_json_cve(self):
        """Test handling of invalid CVE JSON data."""
        updater = CVEUpdater(
            "cve-updater", test_args=[], logger=DevNullLogger()
        )

        # Test invalid dataType
        invalid_data = {
            "dataType": "INVALID",
            "cveMetadata": {"cveId": "CVE-2024-0003"},
        }

        self.assertRaises(
            LaunchpadScriptFailure, updater.processCVEJSON, invalid_data
        )

    def test_update_existing_cve(self):
        """Test updating an existing CVE with new data."""
        # First create a CVE
        original_desc = "Original description"
        cveset = getUtility(ICveSet)

        # Create initial CVE using a properly initialized updater
        updater = self.make_updater()
        cveset.new("2024-0004", original_desc, CveStatus.ENTRY)
        updater.txn.commit()

        # Create updated data
        new_desc = "Updated description"
        cve_data = self.create_test_json_cve(
            cve_id="2024-0004", description=new_desc
        )

        # Process the update with a fresh updater
        updater = self.make_updater()
        updater.processCVEJSON(cve_data)
        updater.txn.commit()

        # Verify the update
        updated_cve = cveset["2024-0004"]
        self.assertEqual(new_desc, updated_cve.description)
