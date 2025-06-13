#  Copyright 2025 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import yaml

__all__ = [
    "SOSSRecord",
]

# From `soss-cve-tracker/git-hooks/check-cve-syntax`
VALID_CHANNEL_REGEX = re.compile(r"^(focal|jammy|noble):[^/]+/stable$")


@dataclass
class SOSSRecord:

    class PriorityEnum(Enum):
        NEEDS_TRIAGE = "Needs-triage"
        NEGLIGIBLE = "Negligible"
        LOW = "Low"
        MEDIUM = "Medium"
        HIGH = "High"
        CRITICAL = "Critical"

    class PackageStatusEnum(Enum):
        IGNORED = "ignored"
        NEEDS_TRIAGE = "needs-triage"
        RELEASED = "released"
        NOT_AFFECTED = "not-affected"
        DEFERRED = "deferred"
        NEEDED = "needed"

    class PackageTypeEnum(Enum):
        CONDA = "conda"
        PYTHON = "python"
        UNPACKAGED = "unpackaged"
        MAVEN = "maven"
        RUST = "rust"

    @dataclass
    class Channel:
        value: str

        def __post_init__(self):
            if not VALID_CHANNEL_REGEX.match(self.value):
                raise ValueError(f"Invalid channel format: {self.value}")

    @dataclass
    class CVSS:
        source: str
        vector: str
        base_score: float
        base_severity: float

        BASE_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

        def __post_init__(self):
            if not (0.0 <= self.base_score <= 10.0):
                raise ValueError(f"Invalid base score: {self.base_score}")
            if self.base_severity not in self.BASE_SEVERITIES:
                raise ValueError(
                    f"Invalid base severity: {self.base_severity}"
                )

    @dataclass
    class Package:
        name: str
        channel: "SOSSRecord.Channel"
        repositories: List[str]
        status: "SOSSRecord.PackageStatusEnum"
        note: str

    references: List[str]
    notes: List[str]
    priority: PriorityEnum
    priority_reason: str
    assigned_to: str
    packages: Dict[PackageTypeEnum, List[Package]]
    candidate: Optional[str] = None
    description: Optional[str] = None
    cvss: Optional[List[CVSS]] = None
    public_date: Optional[datetime] = None

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "SOSSRecord":
        raw: Dict[str, Any] = yaml.safe_load(yaml_str)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "SOSSRecord":
        # - Candidate, Description, CVSS and PublicDate are not mandatory.
        # - References, Notes can be empty using [], but they are always shown.
        # - Priority-Reason, Assigned-To can be empty using "", but they are
        #   always shown.
        # - Other fields are mandatory.
        packages = {}
        for enum_key, pkgs in raw.get("Packages", {}).items():
            package_type = SOSSRecord.PackageTypeEnum(enum_key.lower())
            package_list = [
                SOSSRecord.Package(
                    name=package["Name"],
                    channel=SOSSRecord.Channel(package["Channel"]),
                    repositories=package["Repositories"],
                    status=SOSSRecord.PackageStatusEnum(
                        package["Status"].lower()
                    ),
                    note=package["Note"],
                )
                for package in pkgs
            ]
            packages[package_type] = package_list

        cvss_list = [
            SOSSRecord.CVSS(
                cvss["source"],
                cvss["vector"],
                cvss["baseScore"],
                cvss["baseSeverity"],
            )
            for cvss in raw.get("CVSS", [])
        ]

        public_date_str = raw.get("PublicDate")
        public_date = (
            datetime.fromisoformat(public_date_str)
            if public_date_str
            else None
        )

        return cls(
            references=raw.get("References", []),
            notes=raw.get("Notes", []),
            priority=SOSSRecord.PriorityEnum(raw["Priority"]),
            priority_reason=raw.get("Priority-Reason", ""),
            assigned_to=raw.get("Assigned-To", ""),
            packages=packages,
            candidate=raw.get("Candidate"),
            description=raw.get("Description"),
            cvss=cvss_list,
            public_date=public_date,
        )
