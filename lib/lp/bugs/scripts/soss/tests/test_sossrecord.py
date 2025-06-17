#  Copyright 2025 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).
import os
from datetime import datetime
from pathlib import Path

from lp.bugs.scripts.soss import SOSSRecord
from lp.testing import TestCase


class TestSOSSRecord(TestCase):
    maxDiff = None

    def get_sample_files(self):
        directory = Path(__file__).parent / "sampledata"
        return [directory / f for f in os.listdir(directory)]

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)

        # This is a synthetic SOSSRecord using all the features
        self.soss_record = SOSSRecord(
            references=[
                "https://github.com/ray-project/ray/commit/"
                "64a2e4010522d60b90c389634f24df77b603d85d",
                "https://github.com/ray-project/ray/issues/50266",
                "https://github.com/ray-project/ray/pull/50409",
                "https://security.snyk.io/vuln/SNYK-PYTHON-RAY-8745212",
                "https://ubuntu.com/security/notices/SSN-148-1.json?"
                "show_hidden=true",
            ],
            notes=[
                "This is a sample soss cve with all the fields filled for "
                "testing",
                "sample note 2",
            ],
            priority=SOSSRecord.PriorityEnum.LOW,
            priority_reason=(
                "Unrealistic exploitation scenario. Logs are stored locally "
                "and not transferred between agents, so local log access is "
                "the only conceivable method to view the password for the "
                "redis instance (i.e., no possibility of MitM to access the "
                "logs). Given the requirement for priviledged system access "
                'to access log files the real "danger" posed by the '
                "vulnerability is quite low, and that is reflected in this "
                "priority assignment. "
            ),
            assigned_to="octagalland",
            packages={
                SOSSRecord.PackageTypeEnum.UNPACKAGED: [
                    SOSSRecord.Package(
                        name="vllm",
                        channel=SOSSRecord.Channel("noble:0.7.3/stable"),
                        repositories=["soss-src-stable-local"],
                        status=SOSSRecord.PackageStatusEnum.NEEDED,
                        note="",
                    )
                ],
                SOSSRecord.PackageTypeEnum.PYTHON: [
                    SOSSRecord.Package(
                        name="ray",
                        channel=SOSSRecord.Channel("jammy:2.22.0/stable"),
                        repositories=["nvidia-pb3-python-stable-local"],
                        status=SOSSRecord.PackageStatusEnum.RELEASED,
                        note="2.22.0+soss.1",
                    ),
                    SOSSRecord.Package(
                        name="pyyaml",
                        channel=SOSSRecord.Channel("jammy:2.22.0/stable"),
                        repositories=["nvidia-pb3-python-stable-local"],
                        status=SOSSRecord.PackageStatusEnum.NOT_AFFECTED,
                        note="",
                    ),
                ],
                SOSSRecord.PackageTypeEnum.MAVEN: [
                    SOSSRecord.Package(
                        name="vllm",
                        channel=SOSSRecord.Channel("noble:0.7.3/stable"),
                        repositories=["soss-src-stable-local"],
                        status=SOSSRecord.PackageStatusEnum.NEEDS_TRIAGE,
                        note="",
                    )
                ],
                SOSSRecord.PackageTypeEnum.CONDA: [
                    SOSSRecord.Package(
                        name="ray",
                        channel=SOSSRecord.Channel("jammy:1.17.0/stable"),
                        repositories=["nvidia-pb3-python-stable-local"],
                        status=SOSSRecord.PackageStatusEnum.NOT_AFFECTED,
                        note="2.22.0+soss.1",
                    )
                ],
                SOSSRecord.PackageTypeEnum.RUST: [
                    SOSSRecord.Package(
                        name="ray",
                        channel=SOSSRecord.Channel("focal:0.27.0/stable"),
                        repositories=["nvidia-pb3-python-stable-local"],
                        status=SOSSRecord.PackageStatusEnum.DEFERRED,
                        note="2.22.0+soss.1",
                    )
                ],
            },
            candidate="CVE-2025-1979",
            description=(
                "Versions of the package ray before 2.43.0 are vulnerable to "
                "Insertion of Sensitive Information into Log File where the "
                "redis password is being logged in the standard logging. If "
                "the redis password is passed as an argument, it will be "
                "logged and could potentially leak the password.\r\rThis is "
                "only exploitable if:\r\r1) Logging is enabled;\r\r2) Redis "
                "is using password authentication;\r\r3) Those logs are "
                "accessible to an attacker, who can reach that redis instance."
                "\r\r**Note:**\r\rIt is recommended that anyone who is "
                "running in this configuration should update to the latest "
                "version of Ray, then rotate their redis password."
            ),
            cvss=[
                SOSSRecord.CVSS(
                    source="report@snyk.io",
                    vector=("CVSS:3.1/AV:L/AC:H/PR:L/UI:N/S:C/C:H/I:L/A:N"),
                    base_score=6.4,
                    base_severity="MEDIUM",
                ),
                SOSSRecord.CVSS(
                    source="security-advisories@github.com",
                    vector=("CVSS:3.1/AV:A/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H"),
                    base_score=9.0,
                    base_severity="CRITICAL",
                ),
            ],
            public_date=datetime.fromisoformat("2025-03-06T05:15:16.213"),
        )

        self.soss_record_dict = {
            "References": [
                "https://github.com/ray-project/ray/commit/"
                "64a2e4010522d60b90c389634f24df77b603d85d",
                "https://github.com/ray-project/ray/issues/50266",
                "https://github.com/ray-project/ray/pull/50409",
                "https://security.snyk.io/vuln/SNYK-PYTHON-RAY-8745212",
                "https://ubuntu.com/security/notices/SSN-148-1.json?"
                "show_hidden=true",
            ],
            "Notes": [
                "This is a sample soss cve with all the fields filled for "
                "testing",
                "sample note 2",
            ],
            "Priority": "Low",
            "Priority-Reason": (
                "Unrealistic exploitation scenario. Logs are stored locally "
                "and not transferred between agents, so local log access is "
                "the only conceivable method to view the password for the "
                "redis instance (i.e., no possibility of MitM to access the "
                "logs). Given the requirement for priviledged system access "
                'to access log files the real "danger" posed by the '
                "vulnerability is quite low, and that is reflected in this "
                "priority assignment. "
            ),
            "Assigned-To": "octagalland",
            "Packages": {
                "unpackaged": [
                    {
                        "Name": "vllm",
                        "Channel": "noble:0.7.3/stable",
                        "Repositories": ["soss-src-stable-local"],
                        "Status": "needed",
                        "Note": "",
                    }
                ],
                "python": [
                    {
                        "Name": "ray",
                        "Channel": "jammy:2.22.0/stable",
                        "Repositories": ["nvidia-pb3-python-stable-local"],
                        "Status": "released",
                        "Note": "2.22.0+soss.1",
                    },
                    {
                        "Name": "pyyaml",
                        "Channel": "jammy:2.22.0/stable",
                        "Repositories": ["nvidia-pb3-python-stable-local"],
                        "Status": "not-affected",
                        "Note": "",
                    },
                ],
                "maven": [
                    {
                        "Name": "vllm",
                        "Channel": "noble:0.7.3/stable",
                        "Repositories": ["soss-src-stable-local"],
                        "Status": "needs-triage",
                        "Note": "",
                    }
                ],
                "conda": [
                    {
                        "Name": "ray",
                        "Channel": "jammy:1.17.0/stable",
                        "Repositories": ["nvidia-pb3-python-stable-local"],
                        "Status": "not-affected",
                        "Note": "2.22.0+soss.1",
                    }
                ],
                "rust": [
                    {
                        "Name": "ray",
                        "Channel": "focal:0.27.0/stable",
                        "Repositories": ["nvidia-pb3-python-stable-local"],
                        "Status": "deferred",
                        "Note": "2.22.0+soss.1",
                    }
                ],
            },
            "Candidate": "CVE-2025-1979",
            "Description": (
                "Versions of the package ray before 2.43.0 are vulnerable to "
                "Insertion of Sensitive Information into Log File where the "
                "redis password is being logged in the standard logging. If "
                "the redis password is passed as an argument, it will be "
                "logged and could potentially leak the password.\r\rThis is "
                "only exploitable if:\r\r1) Logging is enabled;\r\r2) Redis "
                "is using password authentication;\r\r3) Those logs are "
                "accessible to an attacker, who can reach that redis instance."
                "\r\r**Note:**\r\rIt is recommended that anyone who is "
                "running in this configuration should update to the latest "
                "version of Ray, then rotate their redis password."
            ),
            "CVSS": [
                {
                    "source": "report@snyk.io",
                    "vector": ("CVSS:3.1/AV:L/AC:H/PR:L/UI:N/S:C/C:H/I:L/A:N"),
                    "baseScore": 6.4,
                    "baseSeverity": "MEDIUM",
                },
                {
                    "source": "security-advisories@github.com",
                    "vector": ("CVSS:3.1/AV:A/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H"),
                    "baseScore": 9.0,
                    "baseSeverity": "CRITICAL",
                },
            ],
            "PublicDate": "2025-03-06T05:15:16.213",
        }

    def test_from_dict(self):
        soss_record = SOSSRecord.from_dict(self.soss_record_dict)
        self.assertEqual(self.soss_record, soss_record)

    def test_from_dict_bad_cvss(self):
        self.soss_record_dict["CVSS"][0]["baseScore"] = -1.5
        self.assertRaises(
            ValueError, SOSSRecord.from_dict, self.soss_record_dict
        )

        self.soss_record_dict["CVSS"][0]["baseScore"] = 10.1
        self.assertRaises(
            ValueError, SOSSRecord.from_dict, self.soss_record_dict
        )

        self.soss_record_dict["CVSS"][0]["baseScore"] = 5
        self.soss_record_dict["CVSS"][0]["baseSeverity"] = "foo"
        self.assertRaises(
            ValueError, SOSSRecord.from_dict, self.soss_record_dict
        )

    def test_from_dict_bad_channel(self):
        self.soss_record_dict["Packages"]["unpackaged"][0]["Channel"] = "bar"
        self.assertRaises(
            ValueError, SOSSRecord.from_dict, self.soss_record_dict
        )

    def test_from_yaml(self):
        load_from = Path(__file__).parent / "sampledata" / "CVE-2025-1979-full"

        soss_record = None
        with open(load_from) as f:
            soss_record = SOSSRecord.from_yaml(f)

        self.assertEqual(self.soss_record, soss_record)

    def test_to_dict(self):
        self.assertDictEqual(
            self.soss_record.to_dict(),
            self.soss_record_dict,
        )

    def test_to_yaml(self):
        load_from = Path(__file__).parent / "sampledata" / "CVE-2025-1979-full"
        with open(load_from) as f:
            sample_data = f.read()

        self.assertEqual(self.soss_record.to_yaml(), sample_data),

    def _verify_import_export_yaml(self, file):
        with open(file) as f:
            soss_record_read = f.read()

        soss_record = SOSSRecord.from_yaml(soss_record_read)
        self.assertEqual(soss_record_read, soss_record.to_yaml())

    def test_verify_import_export_yaml(self):
        files = self.get_sample_files()

        for f in files:
            self._verify_import_export_yaml(f)
