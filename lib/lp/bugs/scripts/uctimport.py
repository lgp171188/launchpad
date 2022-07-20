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
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

import dateutil.parser
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
from lp.bugs.interfaces.cve import ICveSet
from lp.bugs.interfaces.vulnerability import IVulnerabilitySet
from lp.bugs.model.bug import Bug as BugModel
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
from lp.registry.model.sourcepackage import SourcePackage
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.database.constants import UTC_NOW
from lp.services.messages.interfaces.message import IMessageSet

__all__ = [
    "Priority",
    "PackageStatus",
    "DistroSeriesPackageStatus",
    "Patch",
    "Package",
    "Note",
    "CVE",
    "load_cve_from_file",
    "UCTImporter",
]


DEFAULT_LOGGER = logging.getLogger("lp.bugs.scripts.import")


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
    [
        ("distroseries", str),
        ("status", PackageStatus),
        ("reason", str),
        ("priority", Optional[Priority]),
    ],
)


Patch = NamedTuple(
    "Patch",
    [
        ("patch_type", str),
        ("entry", str),
    ],
)


Package = NamedTuple(
    "Package",
    [
        ("name", str),
        ("statuses", List[DistroSeriesPackageStatus]),
        ("priority", Optional[Priority]),
        ("tags", Set[str]),
        ("patches", List[Patch]),
    ],
)

Note = NamedTuple(
    "Note",
    [
        ("author", str),
        ("text", str),
    ],
)


CVE = NamedTuple(
    "CVE",
    [
        ("assigned_to", str),
        ("bugs", List[str]),
        ("cvss", List[Dict[str, Any]]),
        ("candidate", str),
        ("date_made_public", Optional[datetime]),
        ("description", str),
        ("discovered_by", str),
        ("mitigation", Optional[str]),
        ("notes", List[Note]),
        ("priority", Priority),
        ("references", List[str]),
        ("ubuntu_description", str),
        ("packages", List[Package]),
    ],
)


class UCTImporter:

    PRIORITY_MAP = {
        Priority.CRITICAL: BugTaskImportance.CRITICAL,
        Priority.HIGH: BugTaskImportance.HIGH,
        Priority.MEDIUM: BugTaskImportance.MEDIUM,
        Priority.LOW: BugTaskImportance.LOW,
        Priority.UNTRIAGED: BugTaskImportance.UNDECIDED,
        Priority.NEGLIGIBLE: BugTaskImportance.WISHLIST,
    }

    STATUS_MAP = {
        PackageStatus.IGNORED: BugTaskStatus.WONTFIX,
        PackageStatus.NEEDS_TRIAGE: BugTaskStatus.UNKNOWN,
        PackageStatus.DOES_NOT_EXIST: BugTaskStatus.DOESNOTEXIST,
        PackageStatus.RELEASED: BugTaskStatus.FIXRELEASED,
        PackageStatus.NOT_AFFECTED: BugTaskStatus.INVALID,
        # we don't have a corresponding BugTaskStatus for this yet
        # PackageStatus.DEFERRED: ...,
        PackageStatus.NEEDED: BugTaskStatus.NEW,
        PackageStatus.PENDING: BugTaskStatus.FIXCOMMITTED,
    }

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or DEFAULT_LOGGER

    def import_cve_from_file(self, cve_path: Path) -> None:
        cve = load_cve_from_file(cve_path)
        self.import_cve(cve)

    def import_cve(self, cve: CVE) -> None:
        if cve.date_made_public is None:
            self.logger.warning(
                "The CVE does not have a publication date, is it embargoed?"
            )
            return
        lp_cve = getUtility(ICveSet)[cve.candidate]  # type: CveModel
        if lp_cve is None:
            self.logger.warning(
                "Could not find the CVE in LP: %s", cve.candidate
            )
            return
        self.create_bug(cve, lp_cve)

    def create_bug(
        self, cve: CVE, lp_cve: CveModel
    ) -> Tuple[Optional[BugModel], List[Vulnerability]]:
        # Some `CVE` fields are not being used at the moment:
        # - cve.discovered_by: This is supposed to be `Cve.discoverer` but
        #   there may be a difficulty there since the `Cve` table should only
        #   be managed by syncing data from MITRE and not from
        #   ubuntu-cve-tracker
        # - cve.cvss: `Cve.cvss`, but may have a similar issue to
        #   `Cve.discoverer` as above.

        self.logger.debug("creating bug...")

        affected_packages = []  # type: List[DistributionSourcePackage]
        affected_distro_series = []  # type: List[DistroSeries]
        affected_distributions = set()  # type: Set[Distribution]
        importances = {}
        statuses_with_explanations = {}

        for cve_package in cve.packages:
            source_package_name = self.get_source_package_name(
                cve_package.name
            )

            package_priority = cve_package.priority or cve.priority
            importances[source_package_name] = (
                self.PRIORITY_MAP[package_priority]
                if package_priority
                else None
            )

            for cve_package_status in cve_package.statuses:
                distro_series = self.get_distro_series(
                    cve_package_status.distroseries
                )
                if distro_series is None:
                    continue
                if cve_package_status.status not in self.STATUS_MAP:
                    self.logger.warning(
                        "Can't find a suitable bug task status for %s",
                        cve_package_status.status,
                    )
                    continue

                if distro_series not in affected_distro_series:
                    affected_distro_series.append(distro_series)

                affected_distributions.add(distro_series.distribution)

                distro_package = DistributionSourcePackage(
                    distribution=distro_series.distribution,
                    sourcepackagename=source_package_name,
                )
                if distro_package not in affected_packages:
                    affected_packages.append(distro_package)

                distro_series_package_priority = (
                    cve_package_status.priority or package_priority
                )
                series_package = SourcePackage(
                    sourcepackagename=source_package_name,
                    distroseries=distro_series,
                )
                importances[series_package] = (
                    self.PRIORITY_MAP[distro_series_package_priority]
                    if distro_series_package_priority
                    else None
                )
                statuses_with_explanations[series_package] = (
                    self.STATUS_MAP[cve_package_status.status],
                    cve_package_status.reason,
                )

        if not affected_packages:
            self.logger.warning("Could not find any affected packages")
            return None, []

        distro_package = affected_packages.pop(0)
        affected_distributions = {distro_package.distribution}

        # Create the bug
        owner = getUtility(ILaunchpadCelebrities).bug_importer
        bug = getUtility(IBugSet).createBug(
            CreateBugParams(
                description=cve.ubuntu_description,
                title=cve.candidate,
                information_type=InformationType.PUBLICSECURITY,
                owner=owner,
                msg=getUtility(IMessageSet).fromText(
                    "", cve.description, owner=owner
                ),
                target=distro_package,
                importance=importances[distro_package.sourcepackagename],
            )
        )  # type: BugModel

        # Add links to external bug trackers
        for external_bug_url in cve.bugs:
            bug.newMessage(owner=owner, content=external_bug_url)

        # Add references
        for reference in cve.references:
            bug.newMessage(owner=owner, content=reference)

        self.logger.info("Created bug with ID: %s", bug.id)

        # Create bug tasks for distribution packages
        bug_task_set = getUtility(IBugTaskSet)
        for distro_package in affected_packages:
            bug_task_set.createTask(
                bug,
                owner,
                distro_package,
                importance=importances[distro_package.sourcepackagename],
            )

        # Create bug tasks for distro series by adding nominations
        # This may create some extra bug tasks which we will delete later
        for distro_series in affected_distro_series:
            nomination = bug.addNomination(owner, distro_series)
            nomination.approve(owner)

        # Set importance and status on distro series bug tasks
        # If the bug task's package/series isn't listed in the
        # CVE entry - delete it
        for bug_task in bug.bugtasks:
            distro_series = bug_task.distroseries
            if not distro_series:
                continue
            source_package_name = bug_task.sourcepackagename
            series_package = SourcePackage(
                sourcepackagename=source_package_name,
                distroseries=distro_series,
            )
            if series_package not in importances:
                # This combination of package/series is not present in the CVE
                # Delete it
                bug_task.delete(owner)
                continue
            bug_task.transitionToImportance(importances[series_package], owner)
            status, status_explanation = statuses_with_explanations[
                series_package
            ]
            bug_task.transitionToStatus(status, owner)
            bug_task.status_explanation = status_explanation

        # Assign the bug tasks
        if cve.assigned_to:
            assignee = getUtility(IPersonSet).getByName(cve.assigned_to)
            if assignee is not None:
                for bug_task in bug.bugtasks:
                    bug_task.transitionToAssignee(assignee, validate=False)
            else:
                self.logger.warning(
                    "Could not find the assignee: %s", cve.assigned_to
                )

        # Link the bug to CVE
        bug.linkCVE(lp_cve, owner)

        # Make a note of the import in the activity log:
        getUtility(IBugActivitySet).new(
            bug=bug.id,
            datechanged=UTC_NOW,
            person=owner,
            whatchanged="bug",
            message="UCT CVE entry {}".format(cve.candidate),
        )

        # Create the Vulnerabilities
        vulnerabilities = []
        for distribution in affected_distributions:
            vulnerabilities.append(
                self.create_vulnerability(bug, cve, lp_cve, distribution)
            )

        return bug, vulnerabilities

    def get_source_package_name(self, package_name: str) -> SourcePackageName:
        return getUtility(ISourcePackageNameSet).getOrCreateByName(
            package_name
        )

    def get_devel_series(
        self, distribution: Distribution
    ) -> Optional[DistroSeries]:
        for series in distribution.series:
            if series.status == SeriesStatus.FROZEN:
                return series
        for series in distribution.series:
            if series.status == SeriesStatus.DEVELOPMENT:
                return series

    def get_distro_series(
        self, distro_series_name: str
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
                distro_series = self.get_devel_series(distribution)
            else:
                distro_series = getUtility(IDistroSeriesSet).queryByName(
                    distribution, series_name
                )
        if not distro_series:
            self.logger.warning(
                "Could not find the distro series: %s", distro_series_name
            )
        return distro_series

    def create_vulnerability(
        self,
        bug: BugModel,
        cve: CVE,
        lp_cve: CveModel,
        distribution: Distribution,
    ) -> Vulnerability:
        vulnerability = getUtility(IVulnerabilitySet).new(
            distribution=distribution,
            creator=bug.owner,
            cve=lp_cve,
            status=VulnerabilityStatus.NEEDS_TRIAGE,
            description=cve.description,
            notes=format_cve_notes(cve.notes),
            mitigation=cve.mitigation,
            importance=self.PRIORITY_MAP[cve.priority],
            information_type=InformationType.PUBLICSECURITY,
            date_made_public=cve.date_made_public,
        )  # type: Vulnerability

        vulnerability.linkBug(bug, bug.owner)

        self.logger.info("Create vulnerability with ID: %s", vulnerability)

        return vulnerability


def load_cve_from_file(cve_path: Path) -> CVE:
    """
    Load a `CVE` instance from data contained in `cve_path`.

    The file is parsed to a dictionary using the code copied from
    `cve_lib` in `ubuntu-cve-tracker`.

    A `CVE` instance is created from that dictionary, applying some data
    transformations along the way.
    """

    cve_data = load_cve(str(cve_path))  # type: Dict[str, Any]

    packages = []  # type: List[Package]
    tags = pop_cve_property(cve_data, "tags")  # type: Dict[str, Set[str]]
    patches = pop_cve_property(
        cve_data, "patches"
    )  # type: Dict[str, List[Tuple[str, str]]]
    for package, statuses_dict in sorted(
        pop_cve_property(cve_data, "pkgs").items()
    ):
        statuses = []  # type: List[DistroSeriesPackageStatus]
        for distroseries, (status, reason) in sorted(statuses_dict.items()):
            distroseries_priority = pop_cve_property(
                cve_data,
                "Priority_{package}_{distroseries}".format(
                    package=package,
                    distroseries=distroseries,
                ),
                required=False,
            )
            statuses.append(
                DistroSeriesPackageStatus(
                    distroseries=distroseries,
                    status=PackageStatus(status),
                    reason=reason,
                    priority=(
                        Priority(distroseries_priority)
                        if distroseries_priority
                        else None
                    ),
                )
            )
        package_priority = pop_cve_property(
            cve_data,
            "Priority_{package}".format(package=package),
            required=False,
        )
        packages.append(
            Package(
                name=package,
                statuses=statuses,
                priority=(
                    Priority(package_priority) if package_priority else None
                ),
                tags=tags.pop(package, set()),
                patches=[
                    Patch(patch_type=patch_type, entry=entry)
                    for patch_type, entry in patches.pop(package, [])
                ],
            )
        )

    crd = pop_cve_property(cve_data, "CRD", required=False)
    if crd == "unknown":
        crd = None
    public_date = pop_cve_property(cve_data, "PublicDate", required=False)
    if public_date == "unknown":
        public_date = None
    public_date_at_USN = pop_cve_property(
        cve_data, "PublicDateAtUSN", required=False
    )
    if public_date_at_USN == "unknown":
        public_date_at_USN = None

    date_made_public = crd or public_date or public_date_at_USN

    cve = CVE(
        assigned_to=pop_cve_property(cve_data, "Assigned-to"),
        bugs=pop_cve_property(cve_data, "Bugs").split("\n"),
        cvss=pop_cve_property(cve_data, "CVSS"),
        candidate=pop_cve_property(cve_data, "Candidate"),
        date_made_public=(
            dateutil.parser.parse(date_made_public)
            if date_made_public
            else None
        ),
        description=pop_cve_property(cve_data, "Description"),
        discovered_by=pop_cve_property(cve_data, "Discovered-by"),
        mitigation=pop_cve_property(cve_data, "Mitigation", required=False),
        notes=[
            Note(author=author, text=text)
            for author, text in pop_cve_property(cve_data, "Notes")
        ],
        priority=Priority(pop_cve_property(cve_data, "Priority")),
        references=pop_cve_property(cve_data, "References").split("\n"),
        ubuntu_description=pop_cve_property(cve_data, "Ubuntu-Description"),
        packages=packages,
    )

    # make sure all fields are consumed
    if cve_data:
        raise AssertionError(
            "not all fields are consumed: {}".format(cve_data)
        )

    return cve


def pop_cve_property(
    cve_data: Dict[str, Any], field_name: str, required=True
) -> Optional[Any]:
    if required:
        value = cve_data.pop(field_name)
    else:
        value = cve_data.pop(field_name, None)
    if isinstance(value, str):
        return value.strip()
    return value


def format_cve_notes(notes: List[Note]) -> str:
    return "\n".join(
        "{author}> {text}".format(author=note.author, text=note.text)
        for note in notes
    )
