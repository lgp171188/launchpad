# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A UCT (Ubuntu CVE Tracker) bug importer

This code can import CVE summaries stored in UCT repository to bugs in
Launchpad.

For each entry in UCT we:

1. Create a Bug instance
2. Create a Vulnerability instance and link it to the bug (multiple
    Vulnerabilities may be created if the CVE entry covers multiple
    distributions)
3. Create a Bug Task for each package/distro-series in the CVE entry
4. Update the statuses of Bug Tasks based on the information in the CVE entry
"""
import logging
from datetime import datetime, timezone
from enum import Enum
from itertools import chain
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple, Union
from typing.io import TextIO

import dateutil.parser
import transaction
from contrib.cve_lib import load_cve
from zope.component import getUtility

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.bugs.enums import VulnerabilityStatus
from lp.bugs.interfaces.bug import CreateBugParams, IBugSet
from lp.bugs.interfaces.bugactivity import IBugActivitySet
from lp.bugs.interfaces.bugtask import (
    BugTaskImportance,
    BugTaskStatus,
    IBugTaskSet,
)
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.bugs.interfaces.cve import ICveSet
from lp.bugs.interfaces.vulnerability import IVulnerabilitySet
from lp.bugs.model.bug import Bug as BugModel
from lp.bugs.model.bugtask import BugTask
from lp.bugs.model.cve import Cve as CveModel
from lp.bugs.model.vulnerability import Vulnerability
from lp.registry.interfaces.distroseries import IDistroSeriesSet
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.sourcepackagename import ISourcePackageNameSet
from lp.registry.model.distribution import Distribution
from lp.registry.model.distributionsourcepackage import (
    DistributionSourcePackage,
)
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.person import Person
from lp.registry.model.sourcepackage import SourcePackage
from lp.services.database.constants import UTC_NOW

__all__ = [
    "CVE",
    "CVSS",
    "UCTImporter",
    "UCTRecord",
    "UCTImportError",
]

from lp.services.propertycache import cachedproperty

logger = logging.getLogger("lp.bugs.scripts.import")


CVSS = NamedTuple(
    "CVSS",
    (
        ("authority", str),
        ("vector_string", str),
    ),
)


class UCTRecord:
    """
    UCTRecord represents a single CVE record in the ubuntu-cve-tracker.
    """

    class Priority(Enum):
        CRITICAL = "critical"
        HIGH = "high"
        MEDIUM = "medium"
        LOW = "low"
        UNTRIAGED = "untriaged"
        NEGLIGIBLE = "negligible"

    class PackageStatus(Enum):
        IGNORED = "ignored"
        NEEDS_TRIAGE = "needs-triage"
        DOES_NOT_EXIST = "DNE"
        RELEASED = "released"
        NOT_AFFECTED = "not-affected"
        DEFERRED = "deferred"
        NEEDED = "needed"
        PENDING = "pending"

    DistroSeriesPackageStatus = NamedTuple(
        "DistroSeriesPackageStatus",
        (
            ("distroseries", str),
            ("status", PackageStatus),
            ("reason", str),
            ("priority", Optional[Priority]),
        ),
    )

    Patch = NamedTuple(
        "Patch",
        (
            ("patch_type", str),
            ("entry", str),
        ),
    )

    Package = NamedTuple(
        "Package",
        (
            ("name", str),
            ("statuses", List[DistroSeriesPackageStatus]),
            ("priority", Optional[Priority]),
            ("tags", Set[str]),
            ("patches", List[Patch]),
        ),
    )

    Note = NamedTuple(
        "Note",
        (
            ("author", str),
            ("text", str),
        ),
    )

    def __init__(
        self,
        path: Path,
        assigned_to: str,
        bugs: List[str],
        cvss: List[CVSS],
        candidate: str,
        crd: Optional[datetime],
        public_date: Optional[datetime],
        public_date_at_USN: Optional[datetime],
        description: str,
        discovered_by: str,
        mitigation: Optional[str],
        notes: List[Note],
        priority: Priority,
        references: List[str],
        ubuntu_description: str,
        packages: List[Package],
    ):
        self.path = path
        self.assigned_to = assigned_to
        self.bugs = bugs
        self.cvss = cvss
        self.candidate = candidate
        self.crd = crd
        self.public_date = public_date
        self.public_date_at_USN = public_date_at_USN
        self.description = description
        self.discovered_by = discovered_by
        self.mitigation = mitigation
        self.notes = notes
        self.priority = priority
        self.references = references
        self.ubuntu_description = ubuntu_description
        self.packages = packages

    def __eq__(self, other):
        if not isinstance(other, UCTRecord):
            raise ValueError("UCTRecord can only be compared to UCTRecord")
        return self.__dict__ == other.__dict__

    @classmethod
    def pop_cve_property(
        cls, cve_data: Dict[str, Any], field_name: str, required=True
    ) -> Optional[Any]:
        if required:
            value = cve_data.pop(field_name)
        else:
            value = cve_data.pop(field_name, None)
        if isinstance(value, str):
            return value.strip()
        return value

    @classmethod
    def load(cls, cve_path: Path) -> "UCTRecord":
        """
        Create a `UCTRecord` instance from a file located at `cve_path`.

        The file is parsed to a dictionary using the code copied from
        `cve_lib` in `ubuntu-cve-tracker`.
        A `UCTRecord` instance is created from that dictionary,
        applying some data transformations along the way.
        """

        cve_data = load_cve(str(cve_path))  # type: Dict[str, Any]

        packages = []
        tags = cls.pop_cve_property(
            cve_data, "tags"
        )  # type: Dict[str, Set[str]]
        patches = cls.pop_cve_property(
            cve_data, "patches"
        )  # type: Dict[str, List[Tuple[str, str]]]
        for package, statuses_dict in cls.pop_cve_property(
            cve_data, "pkgs"
        ).items():
            statuses = []
            for distroseries, (status, reason) in statuses_dict.items():
                distroseries_priority = cls.pop_cve_property(
                    cve_data,
                    "Priority_{package}_{distroseries}".format(
                        package=package,
                        distroseries=distroseries,
                    ),
                    required=False,
                )
                statuses.append(
                    cls.DistroSeriesPackageStatus(
                        distroseries=distroseries,
                        status=cls.PackageStatus(status),
                        reason=reason,
                        priority=(
                            cls.Priority(distroseries_priority)
                            if distroseries_priority
                            else None
                        ),
                    )
                )
            package_priority = cls.pop_cve_property(
                cve_data,
                "Priority_{package}".format(package=package),
                required=False,
            )
            packages.append(
                cls.Package(
                    name=package,
                    statuses=statuses,
                    priority=(
                        cls.Priority(package_priority)
                        if package_priority
                        else None
                    ),
                    tags=tags.pop(package, set()),
                    patches=[
                        cls.Patch(patch_type=patch_type, entry=entry)
                        for patch_type, entry in patches.pop(package, [])
                    ],
                )
            )

        crd = cls.pop_cve_property(cve_data, "CRD", required=False)
        if crd == "unknown":
            crd = None
        public_date = cls.pop_cve_property(
            cve_data, "PublicDate", required=False
        )
        if public_date == "unknown":
            public_date = None
        public_date_at_USN = cls.pop_cve_property(
            cve_data, "PublicDateAtUSN", required=False
        )
        if public_date_at_USN == "unknown":
            public_date_at_USN = None

        cvss = []
        for cvss_dict in cls.pop_cve_property(cve_data, "CVSS"):
            cvss.append(
                CVSS(
                    authority=cvss_dict["source"],
                    vector_string="{} [{} {}]".format(
                        cvss_dict["vector"],
                        cvss_dict["baseScore"],
                        cvss_dict["baseSeverity"],
                    ),
                )
            )

        entry = UCTRecord(
            path=cve_path,
            assigned_to=cls.pop_cve_property(cve_data, "Assigned-to"),
            bugs=cls.pop_cve_property(cve_data, "Bugs").split("\n"),
            cvss=cvss,
            candidate=cls.pop_cve_property(cve_data, "Candidate"),
            crd=dateutil.parser.parse(crd) if crd else None,
            public_date=(
                dateutil.parser.parse(public_date) if public_date else None
            ),
            public_date_at_USN=(
                dateutil.parser.parse(public_date_at_USN)
                if public_date_at_USN
                else None
            ),
            description=cls.pop_cve_property(cve_data, "Description"),
            discovered_by=cls.pop_cve_property(cve_data, "Discovered-by"),
            mitigation=cls.pop_cve_property(
                cve_data, "Mitigation", required=False
            ),
            notes=[
                cls.Note(author=author, text=text)
                for author, text in cls.pop_cve_property(cve_data, "Notes")
            ],
            priority=cls.Priority(cls.pop_cve_property(cve_data, "Priority")),
            references=cls.pop_cve_property(cve_data, "References").split(
                "\n"
            ),
            ubuntu_description=cls.pop_cve_property(
                cve_data, "Ubuntu-Description"
            ),
            packages=packages,
        )

        # make sure all fields are consumed
        if cve_data:
            raise AssertionError(
                "not all fields are consumed: {}".format(cve_data)
            )

        return entry

    def save(self, path: Path) -> None:
        output = open(str(path), "w")
        if self.public_date_at_USN:
            self._write_field(
                "PublicDateAtUSN",
                self._format_datetime(self.public_date_at_USN),
                output,
            )
        self._write_field("Candidate", self.candidate, output)
        if self.crd:
            self._write_field("CRD", self._format_datetime(self.crd), output)
        if self.public_date:
            self._write_field(
                "PublicDate", self._format_datetime(self.public_date), output
            )
        self._write_field("References", self.references, output)
        self._write_field("Description", self.description.split("\n"), output)
        self._write_field(
            "Ubuntu-Description", self.ubuntu_description.split("\n"), output
        )
        notes = []
        for note in self.notes:
            note_lines = note.text.split("\n")
            notes.append("{}> {}".format(note.author, note_lines[0]))
            for line in note_lines[1:]:
                notes.append("  " + line)
        self._write_field("Notes", notes, output)
        self._write_field(
            "Mitigation",
            self.mitigation.split("\n") if self.mitigation else "",
            output,
        )
        self._write_field("Bugs", self.bugs, output)
        self._write_field("Priority", self.priority.value, output)
        self._write_field("Discovered-by", self.discovered_by, output)
        self._write_field("Assigned-to", self.assigned_to, output)
        self._write_field(
            "CVSS",
            [
                "{authority}: {vector_string}".format(**c._asdict())
                for c in self.cvss
            ],
            output,
        )
        for package in self.packages:
            output.write("\n")
            patches = [
                "{}: {}".format(patch.patch_type, patch.entry)
                for patch in package.patches
            ]
            self._write_field(
                "Patches_{}".format(package.name), patches, output
            )
            for status in package.statuses:
                self._write_field(
                    "{}_{}".format(status.distroseries, package.name),
                    (
                        "{} ({})".format(status.status.value, status.reason)
                        if status.reason
                        else status.status.value
                    ),
                    output,
                )
            if package.priority:
                self._write_field(
                    "Priority_{}".format(package.name),
                    package.priority.value,
                    output,
                )
            for status in package.statuses:
                if status.priority:
                    self._write_field(
                        "Priority_{}_{}".format(
                            package.name, status.distroseries
                        ),
                        status.priority.value,
                        output,
                    )

            if package.tags:
                self._write_field(
                    "Tags_{}".format(package.name),
                    " ".join(package.tags),
                    output,
                )

        output.close()

    def _format_datetime(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")

    def _write_field(
        self, name: str, value: Union[str, List[str]], output: TextIO
    ) -> None:
        if isinstance(value, str):
            if value:
                output.write("{}: {}\n".format(name, value))
            else:
                output.write("{}:\n".format(name))
        elif isinstance(value, list):
            output.write("{}:\n".format(name))
            for line in value:
                output.write(" {}\n".format(line))
        else:
            raise AssertionError()


class CVE:

    DistroPackage = NamedTuple(
        "DistroPackage",
        (
            ("package", DistributionSourcePackage),
            ("importance", Optional[BugTaskImportance]),
        ),
    )

    SeriesPackage = NamedTuple(
        "SeriesPackage",
        (
            ("package", SourcePackage),
            ("importance", Optional[BugTaskImportance]),
            ("status", BugTaskStatus),
            ("status_explanation", str),
        ),
    )

    PRIORITY_MAP = {
        UCTRecord.Priority.CRITICAL: BugTaskImportance.CRITICAL,
        UCTRecord.Priority.HIGH: BugTaskImportance.HIGH,
        UCTRecord.Priority.MEDIUM: BugTaskImportance.MEDIUM,
        UCTRecord.Priority.LOW: BugTaskImportance.LOW,
        UCTRecord.Priority.UNTRIAGED: BugTaskImportance.UNDECIDED,
        UCTRecord.Priority.NEGLIGIBLE: BugTaskImportance.WISHLIST,
    }

    BUG_TASK_STATUS_MAP = {
        UCTRecord.PackageStatus.IGNORED: BugTaskStatus.WONTFIX,
        UCTRecord.PackageStatus.NEEDS_TRIAGE: BugTaskStatus.UNKNOWN,
        UCTRecord.PackageStatus.DOES_NOT_EXIST: BugTaskStatus.DOESNOTEXIST,
        UCTRecord.PackageStatus.RELEASED: BugTaskStatus.FIXRELEASED,
        UCTRecord.PackageStatus.NOT_AFFECTED: BugTaskStatus.INVALID,
        # we don't have a corresponding BugTaskStatus for this yet
        # PackageStatus.DEFERRED: ...,
        UCTRecord.PackageStatus.NEEDED: BugTaskStatus.NEW,
        UCTRecord.PackageStatus.PENDING: BugTaskStatus.FIXCOMMITTED,
    }

    VULNERABILITY_STATUS_MAP = {
        "active": VulnerabilityStatus.ACTIVE,
        "ignored": VulnerabilityStatus.IGNORED,
        "retired": VulnerabilityStatus.RETIRED,
    }

    def __init__(
        self,
        sequence: str,
        date_made_public: Optional[datetime],
        distro_packages: List[DistroPackage],
        series_packages: List[SeriesPackage],
        importance: BugTaskImportance,
        status: VulnerabilityStatus,
        assignee: Optional[Person],
        description: str,
        ubuntu_description: str,
        bug_urls: List[str],
        references: List[str],
        notes: str,
        mitigation: str,
        cvss: List[CVSS],
    ):
        self.sequence = sequence
        self.date_made_public = date_made_public
        self.distro_packages = distro_packages
        self.series_packages = series_packages
        self.importance = importance
        self.status = status
        self.assignee = assignee
        self.description = description
        self.ubuntu_description = ubuntu_description
        self.bug_urls = bug_urls
        self.references = references
        self.notes = notes
        self.mitigation = mitigation
        self.cvss = cvss

    @classmethod
    def make_from_uct_record(cls, uct_record: UCTRecord) -> "CVE":
        # Some `UCTRecord` fields are not being used at the moment:
        # - cve.discovered_by: This is supposed to be `Cve.discoverer` but
        #   there may be a difficulty there since the `Cve` table should only
        #   be managed by syncing data from MITRE and not from
        #   ubuntu-cve-tracker
        # - cve.cvss: `Cve.cvss`, but may have a similar issue to
        #   `Cve.discoverer` as above.

        distro_packages = []
        series_packages = []

        spn_set = getUtility(ISourcePackageNameSet)

        for uct_package in uct_record.packages:
            source_package_name = spn_set.getOrCreateByName(uct_package.name)
            package_priority = uct_package.priority or uct_record.priority
            package_importance = (
                cls.PRIORITY_MAP[package_priority]
                if package_priority
                else None
            )

            for uct_package_status in uct_package.statuses:
                distro_series = cls.get_distro_series(
                    uct_package_status.distroseries
                )
                if distro_series is None:
                    continue

                if uct_package_status.status not in cls.BUG_TASK_STATUS_MAP:
                    logger.warning(
                        "Can't find a suitable bug task status for %s",
                        uct_package_status.status,
                    )
                    continue

                distro_package = cls.DistroPackage(
                    package=DistributionSourcePackage(
                        distribution=distro_series.distribution,
                        sourcepackagename=source_package_name,
                    ),
                    importance=package_importance,
                )
                if distro_package not in distro_packages:
                    distro_packages.append(distro_package)

                series_package_priority = (
                    uct_package_status.priority or package_priority
                )
                series_package_importance = (
                    cls.PRIORITY_MAP[series_package_priority]
                    if series_package_priority
                    else None
                )

                series_packages.append(
                    cls.SeriesPackage(
                        package=SourcePackage(
                            sourcepackagename=source_package_name,
                            distroseries=distro_series,
                        ),
                        importance=series_package_importance,
                        status=cls.BUG_TASK_STATUS_MAP[
                            uct_package_status.status
                        ],
                        status_explanation=uct_package_status.reason,
                    )
                )

        if uct_record.assigned_to:
            assignee = getUtility(IPersonSet).getByName(uct_record.assigned_to)
            if not assignee:
                logger.warning(
                    "Could not find the assignee: %s", uct_record.assigned_to
                )
        else:
            assignee = None

        return cls(
            sequence=uct_record.candidate,
            date_made_public=(
                uct_record.crd
                or uct_record.public_date_at_USN
                or uct_record.public_date
            ),
            distro_packages=distro_packages,
            series_packages=series_packages,
            importance=cls.PRIORITY_MAP[uct_record.priority],
            status=cls.infer_vulnerability_status(uct_record),
            assignee=assignee,
            description=uct_record.description,
            ubuntu_description=uct_record.ubuntu_description,
            bug_urls=uct_record.bugs,
            references=uct_record.references,
            notes=cls.format_cve_notes(uct_record.notes),
            mitigation=uct_record.mitigation,
            cvss=uct_record.cvss,
        )

    @cachedproperty
    def affected_distributions(self) -> Set[Distribution]:
        return {p.package.distribution for p in self.distro_packages}

    @cachedproperty
    def affected_distro_series(self) -> Set[DistroSeries]:
        return {p.package.distroseries for p in self.series_packages}

    @classmethod
    def infer_vulnerability_status(
        cls, uct_record: UCTRecord
    ) -> VulnerabilityStatus:
        """
        Infer vulnerability status based on the parent folder of the CVE file.
        """
        cve_folder_name = uct_record.path.absolute().parent.name
        return cls.VULNERABILITY_STATUS_MAP.get(
            cve_folder_name, VulnerabilityStatus.NEEDS_TRIAGE
        )

    @classmethod
    def format_cve_notes(cls, notes: List[UCTRecord.Note]) -> str:
        return "\n".join(
            "{author}> {text}".format(author=note.author, text=note.text)
            for note in notes
        )

    @classmethod
    def get_devel_series(
        cls, distribution: Distribution
    ) -> Optional[DistroSeries]:
        for series in distribution.series:
            if series.status == SeriesStatus.FROZEN:
                return series
        for series in distribution.series:
            if series.status == SeriesStatus.DEVELOPMENT:
                return series

    @classmethod
    def get_distro_series(
        cls, distro_series_name: str
    ) -> Optional[DistroSeries]:
        if "/" in distro_series_name:
            series_name, distro_name = distro_series_name.split("/", 1)
            if distro_name == "esm":
                # TODO: ESM needs special handling
                pass
            return
        else:
            series_name = distro_series_name
            distribution = getUtility(ILaunchpadCelebrities).ubuntu
            if series_name == "devel":
                distro_series = cls.get_devel_series(distribution)
            else:
                distro_series = getUtility(IDistroSeriesSet).queryByName(
                    distribution, series_name
                )
        if not distro_series:
            logger.warning(
                "Could not find the distro series: %s", distro_series_name
            )
        return distro_series


class UCTImportError(Exception):
    pass


class UCTImporter:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.bug_importer = getUtility(ILaunchpadCelebrities).bug_importer

    def import_cve_from_file(self, cve_path: Path) -> None:
        uct_record = UCTRecord.load(cve_path)
        cve = CVE.make_from_uct_record(uct_record)
        self.import_cve(cve)

    def import_cve(self, cve: CVE) -> None:
        if cve.date_made_public is None:
            logger.warning(
                "The CVE does not have a publication date, is it embargoed?"
            )
            return
        lp_cve = getUtility(ICveSet)[cve.sequence]  # type: CveModel
        if lp_cve is None:
            logger.warning("Could not find the CVE in LP: %s", cve.sequence)
            return
        bug = self.find_existing_bug(cve, lp_cve)
        try:
            if bug is None:
                self.create_bug(cve, lp_cve)
            else:
                self.update_bug(bug, cve, lp_cve)
            self.update_launchpad_cve(lp_cve, cve)
        except Exception:
            transaction.abort()
            raise

        if self.dry_run:
            logger.info("Dry-run mode enabled, all changes are reverted.")
            transaction.abort()
        else:
            transaction.commit()

    def find_existing_bug(
        self, cve: CVE, lp_cve: CveModel
    ) -> Optional[BugModel]:
        bug = None
        for vulnerability in lp_cve.vulnerabilities:
            if vulnerability.distribution in cve.affected_distributions:
                bugs = vulnerability.bugs
                if bugs:
                    if bug and bugs[0] != bug:
                        raise UCTImportError(
                            "Multiple existing bugs are found "
                            "for CVE {}".format(cve.sequence)
                        )
                    else:
                        bug = bugs[0]
        return bug

    def create_bug(self, cve: CVE, lp_cve: CveModel) -> Optional[BugModel]:

        logger.debug("creating bug...")

        if not cve.series_packages:
            logger.warning("Could not find any affected packages")
            return None

        distro_package = cve.distro_packages[0]

        # Create the bug
        bug = getUtility(IBugSet).createBug(
            CreateBugParams(
                comment=self.make_bug_description(cve),
                title=cve.sequence,
                information_type=InformationType.PUBLICSECURITY,
                owner=self.bug_importer,
                target=distro_package.package,
                importance=distro_package.importance,
                cve=lp_cve,
            )
        )  # type: BugModel

        self.update_external_bug_urls(bug, cve.bug_urls)

        logger.info("Created bug with ID: %s", bug.id)

        self.create_bug_tasks(
            bug, cve.distro_packages[1:], cve.series_packages
        )
        self.update_statuses_and_importances(
            bug, cve.distro_packages[1:], cve.series_packages
        )
        self.assign_bug_tasks(bug, cve.assignee)

        # Make a note of the import in the activity log:
        getUtility(IBugActivitySet).new(
            bug=bug.id,
            datechanged=UTC_NOW,
            person=self.bug_importer,
            whatchanged="bug",
            message="UCT CVE entry {}".format(cve.sequence),
        )

        # Create the Vulnerabilities
        for distribution in cve.affected_distributions:
            self.create_vulnerability(bug, cve, lp_cve, distribution)

        return bug

    def update_bug(self, bug: BugModel, cve: CVE, lp_cve: CveModel) -> None:
        bug.description = self.make_bug_description(cve)

        self.create_bug_tasks(bug, cve.distro_packages, cve.series_packages)
        self.update_statuses_and_importances(
            bug, cve.distro_packages, cve.series_packages
        )
        self.assign_bug_tasks(bug, cve.assignee)
        self.update_external_bug_urls(bug, cve.bug_urls)

        # Update or add new Vulnerabilities
        vulnerabilities_by_distro = {
            v.distribution: v for v in bug.vulnerabilities
        }
        for distro in cve.affected_distributions:
            vulnerability = vulnerabilities_by_distro.get(distro)
            if vulnerability is None:
                self.create_vulnerability(bug, cve, lp_cve, distro)
            else:
                self.update_vulnerability(vulnerability, cve)

    def create_bug_tasks(
        self,
        bug: BugModel,
        distro_packages: List[CVE.DistroPackage],
        series_packages: List[CVE.SeriesPackage],
    ) -> None:
        bug_tasks = bug.bugtasks  # type: List[BugTask]
        bug_task_by_target = {t.target: t for t in bug_tasks}
        bug_task_set = getUtility(IBugTaskSet)
        for target in (
            p.package for p in chain(distro_packages, series_packages)
        ):
            if target not in bug_task_by_target:
                bug_task_set.createTask(bug, self.bug_importer, target)

    def create_vulnerability(
        self,
        bug: BugModel,
        cve: CVE,
        lp_cve: CveModel,
        distribution: Distribution,
    ) -> Vulnerability:
        date_made_public = cve.date_made_public
        if date_made_public.tzinfo is None:
            date_made_public = date_made_public.replace(tzinfo=timezone.utc)
        vulnerability = getUtility(IVulnerabilitySet).new(
            distribution=distribution,
            creator=bug.owner,
            cve=lp_cve,
            status=cve.status,
            description=cve.description,
            notes=cve.notes,
            mitigation=cve.mitigation,
            importance=cve.importance,
            information_type=InformationType.PUBLICSECURITY,
            date_made_public=date_made_public,
        )  # type: Vulnerability

        vulnerability.linkBug(bug, bug.owner)

        logger.info("Created vulnerability with ID: %s", vulnerability.id)

        return vulnerability

    def update_vulnerability(
        self, vulnerability: Vulnerability, cve: CVE
    ) -> None:
        vulnerability.status = cve.status
        vulnerability.description = cve.description
        vulnerability.notes = cve.notes
        vulnerability.mitigation = cve.mitigation
        vulnerability.importance = cve.importance
        vulnerability.date_made_public = cve.date_made_public

    def assign_bug_tasks(
        self, bug: BugModel, assignee: Optional[Person]
    ) -> None:
        for bug_task in bug.bugtasks:
            bug_task.transitionToAssignee(assignee, validate=False)

    def update_statuses_and_importances(
        self,
        bug: BugModel,
        distro_packages: List[CVE.DistroPackage],
        series_packages: List[CVE.SeriesPackage],
    ) -> None:
        bug_tasks = bug.bugtasks  # type: List[BugTask]
        bug_task_by_target = {t.target: t for t in bug_tasks}

        for dp in distro_packages:
            task = bug_task_by_target[dp.package]
            if task.importance != dp.importance:
                task.transitionToImportance(dp.importance, self.bug_importer)

        for sp in series_packages:
            task = bug_task_by_target[sp.package]
            if task.importance != sp.importance:
                task.transitionToImportance(sp.importance, self.bug_importer)
            if task.status != sp.status:
                task.transitionToStatus(sp.status, self.bug_importer)
            if task.status_explanation != sp.status_explanation:
                task.status_explanation = sp.status_explanation

    def update_external_bug_urls(
        self, bug: BugModel, bug_urls: List[str]
    ) -> None:
        bug_urls = set(bug_urls)
        for watch in bug.watches:
            if watch.url in bug_urls:
                bug_urls.remove(watch.url)
            else:
                watch.destroySelf()
        bug_watch_set = getUtility(IBugWatchSet)
        for external_bug_url in bug_urls:
            bug_watch_set.fromText(external_bug_url, bug, self.bug_importer)

    def make_bug_description(self, cve: CVE) -> str:
        parts = [cve.description]
        if cve.ubuntu_description:
            parts.extend(["", "Ubuntu-Description:", cve.ubuntu_description])
        if cve.references:
            parts.extend(["", "References:"])
            parts.extend(cve.references)
        return "\n".join(parts)

    def update_launchpad_cve(self, lp_cve: CveModel, cve: CVE):
        for cvss in cve.cvss:
            lp_cve.setCVSSVectorForAuthority(
                cvss.authority, cvss.vector_string
            )
