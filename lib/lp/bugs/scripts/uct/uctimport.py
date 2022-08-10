#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

"""A UCT (Ubuntu CVE Tracker) bug importer

This code can import CVE summaries stored in UCT repository to bugs in
Launchpad.

For each entry in UCT we:

1. Create a Bug instance
2. Create a Vulnerability instance for each affected distribution and link it
   to the bug
3. Create a Bug Task for each distribution/series package in the CVE entry
4. Update the statuses of Bug Tasks based on the information in the CVE entry
5. Update the information the related Launchpad's `Cve` model, if necessary
"""
import logging
from datetime import timezone
from itertools import chain
from pathlib import Path
from typing import List, Optional

import transaction
from zope.component import getUtility

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.bugs.interfaces.bug import CreateBugParams, IBugSet
from lp.bugs.interfaces.bugactivity import IBugActivitySet
from lp.bugs.interfaces.bugtask import BugTaskImportance, IBugTaskSet
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.bugs.interfaces.cve import ICveSet
from lp.bugs.interfaces.vulnerability import IVulnerabilitySet
from lp.bugs.model.bug import Bug as BugModel
from lp.bugs.model.bugtask import BugTask
from lp.bugs.model.cve import Cve as CveModel
from lp.bugs.model.vulnerability import Vulnerability
from lp.registry.model.distribution import Distribution
from lp.registry.model.person import Person
from lp.services.database.constants import UTC_NOW

from .models import CVE, UCTRecord

__all__ = [
    "UCTImporter",
    "UCTImportError",
]

logger = logging.getLogger(__name__)


class UCTImportError(Exception):
    pass


class UCTImporter:
    """
    `UCTImporter` is used to import UCT CVE files to Launchpad database.
    """

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.bug_importer = getUtility(ILaunchpadCelebrities).bug_importer

    def import_cve_from_file(self, cve_path: Path) -> None:
        """
        Import a UCT CVE record from a file located at `cve_path`.

        :param cve_path: path to the UCT CVE file
        """
        uct_record = UCTRecord.load(cve_path)
        cve = CVE.make_from_uct_record(uct_record)
        self.import_cve(cve)

    def import_cve(self, cve: CVE) -> None:
        """
        Import a `CVE` instance to Launchpad database.

        :param cve: `CVE` with information from UCT
        """
        if cve.date_made_public is None:
            logger.warning(
                "The CVE does not have a publication date, is it embargoed?"
            )
            return
        lp_cve = getUtility(ICveSet)[cve.sequence]  # type: CveModel
        if lp_cve is None:
            logger.warning("Could not find the CVE in LP: %s", cve.sequence)
            return
        bug = self._find_existing_bug(cve, lp_cve)
        try:
            if bug is None:
                self.create_bug(cve, lp_cve)
            else:
                self.update_bug(bug, cve, lp_cve)
            self._update_launchpad_cve(lp_cve, cve)
        except Exception:
            transaction.abort()
            raise

        if self.dry_run:
            logger.info("Dry-run mode enabled, all changes are reverted.")
            transaction.abort()
        else:
            transaction.commit()

    def create_bug(self, cve: CVE, lp_cve: CveModel) -> Optional[BugModel]:
        """
        Create a `Bug` model based on the information contained in a `CVE`.

        :param cve: `CVE` with information from UCT
        :param lp_cve: Launchpad `Cve` model
        """

        logger.debug("creating bug...")

        if not cve.series_packages:
            logger.warning("Could not find any affected packages")
            return None

        distro_package = cve.distro_packages[0]

        # Create the bug
        bug = getUtility(IBugSet).createBug(
            CreateBugParams(
                comment=self._make_bug_description(cve),
                title=cve.sequence,
                information_type=InformationType.PUBLICSECURITY,
                owner=self.bug_importer,
                target=distro_package.package,
                importance=distro_package.importance,
                cve=lp_cve,
            )
        )  # type: BugModel

        self._update_external_bug_urls(bug, cve.bug_urls)

        logger.info("Created bug with ID: %s", bug.id)

        self._create_bug_tasks(
            bug, cve.distro_packages[1:], cve.series_packages
        )
        self._update_statuses_and_importances(
            bug, cve.importance, cve.distro_packages, cve.series_packages
        )
        self._assign_bug_tasks(bug, cve.assignee)

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
            self._create_vulnerability(bug, cve, lp_cve, distribution)

        return bug

    def update_bug(self, bug: BugModel, cve: CVE, lp_cve: CveModel) -> None:
        """
        Update a `Bug` model with the information contained in a `CVE`.

        :param bug: `Bug` model to be updated
        :param cve: `CVE` with information from UCT
        :param lp_cve: Launchpad `Cve` model
        """
        bug.description = self._make_bug_description(cve)

        self._create_bug_tasks(bug, cve.distro_packages, cve.series_packages)
        self._update_statuses_and_importances(
            bug, cve.importance, cve.distro_packages, cve.series_packages
        )
        self._assign_bug_tasks(bug, cve.assignee)
        self._update_external_bug_urls(bug, cve.bug_urls)

        # Update or add new Vulnerabilities
        vulnerabilities_by_distro = {
            v.distribution: v for v in bug.vulnerabilities
        }
        for distro in cve.affected_distributions:
            vulnerability = vulnerabilities_by_distro.get(distro)
            if vulnerability is None:
                self._create_vulnerability(bug, cve, lp_cve, distro)
            else:
                self._update_vulnerability(vulnerability, cve)

    def _find_existing_bug(
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

    def _create_bug_tasks(
        self,
        bug: BugModel,
        distro_packages: List[CVE.DistroPackage],
        series_packages: List[CVE.SeriesPackage],
    ) -> None:
        """
        Add bug tasks to the given `Bug` model based on the information
        from a `CVE`.

        `distro_packages` and `series_packages` from the `CVE`
        are used as bug task targets.

        This may be called multiple times, only new targets will be processed.

        :param bug: `Bug` model to be updated
        :param distro_packages: list of `DistroPackage`s from a `CVE`
        :param series_packages: list of `SeriesPackage`s from a `CVE`
        """
        bug_tasks = bug.bugtasks  # type: List[BugTask]
        bug_task_by_target = {t.target: t for t in bug_tasks}
        bug_task_set = getUtility(IBugTaskSet)
        for target in (
            p.package for p in chain(distro_packages, series_packages)
        ):
            if target not in bug_task_by_target:
                bug_task_set.createTask(bug, self.bug_importer, target)

    def _create_vulnerability(
        self,
        bug: BugModel,
        cve: CVE,
        lp_cve: CveModel,
        distribution: Distribution,
    ) -> Vulnerability:
        """
        Create a Vulnerability instance based on the information from
        the given `CVE` instance and link to the specified `Bug`
        and LP's `Cve` model.

        :param bug: `Bug` model associated with the vulnerability
        :param cve: `CVE` with information from UCT
        :param lp_cve: Launchpad `Cve` model
        :param distribution: a `Distribution` affected by the vulnerability
        :return: a Vulnerability
        """
        date_made_public = cve.date_made_public
        if date_made_public.tzinfo is None:
            date_made_public = date_made_public.replace(tzinfo=timezone.utc)
        vulnerability = getUtility(IVulnerabilitySet).new(
            distribution=distribution,
            creator=bug.owner,
            cve=lp_cve,
            status=cve.status,
            description=cve.ubuntu_description,
            notes=cve.notes,
            mitigation=cve.mitigation,
            importance=cve.importance,
            information_type=InformationType.PUBLICSECURITY,
            date_made_public=date_made_public,
        )  # type: Vulnerability

        vulnerability.linkBug(bug, bug.owner)

        logger.info("Created vulnerability with ID: %s", vulnerability.id)

        return vulnerability

    def _update_vulnerability(
        self, vulnerability: Vulnerability, cve: CVE
    ) -> None:
        """
        Update a `Vulnerability` model with the information
        contained in a `CVE`

        :param vulnerability: `Vulnerability` model to be updated
        :param cve: `CVE` with information from UCT
        """
        vulnerability.status = cve.status
        vulnerability.description = cve.ubuntu_description
        vulnerability.notes = cve.notes
        vulnerability.mitigation = cve.mitigation
        vulnerability.importance = cve.importance
        vulnerability.date_made_public = cve.date_made_public

    def _assign_bug_tasks(
        self, bug: BugModel, assignee: Optional[Person]
    ) -> None:
        """
        Assign all bug tasks from the given bug to the given assignee.

        :param bug: `Bug` model to be updated
        :param assignee: a person to be assigned (may be None)
        """
        for bug_task in bug.bugtasks:
            bug_task.transitionToAssignee(assignee, validate=False)

    def _update_statuses_and_importances(
        self,
        bug: BugModel,
        cve_importance: BugTaskImportance,
        distro_packages: List[CVE.DistroPackage],
        series_packages: List[CVE.SeriesPackage],
    ) -> None:
        """
        Update statuses and importances of bug tasks according to the
        information contained in `CVE`.

        If a distro package doesn't have importance information, the
        `cve_importance` is used instead.

        If a series package doesn't have importance information, the
        importance of the corresponding distro package is used instead.

        :param bug: `Bug` model to be updated
        :param cve_importance: `CVE` importance
        :param distro_packages: list of `DistroPackage`s from a `CVE`
        :param series_packages: list of `SeriesPackage`s from a `CVE`
        """
        bug_tasks = bug.bugtasks  # type: List[BugTask]
        bug_task_by_target = {t.target: t for t in bug_tasks}

        package_importances = {}

        for dp in distro_packages:
            task = bug_task_by_target[dp.package]
            dp_importance = dp.importance or cve_importance
            package_importances[dp.package.sourcepackagename] = dp_importance
            if task.importance != dp_importance:
                task.transitionToImportance(dp_importance, self.bug_importer)

        for sp in series_packages:
            task = bug_task_by_target[sp.package]
            package_importance = package_importances[
                sp.package.sourcepackagename
            ]
            sp_importance = sp.importance or package_importance
            if task.importance != sp_importance:
                task.transitionToImportance(sp_importance, self.bug_importer)
            if task.status != sp.status:
                task.transitionToStatus(sp.status, self.bug_importer)
            if task.status_explanation != sp.status_explanation:
                task.status_explanation = sp.status_explanation

    def _update_external_bug_urls(
        self, bug: BugModel, bug_urls: List[str]
    ) -> None:
        """
        Save links to external bug trackers as bug watches.

        :param bug: `Bug` model to be updated
        :param bug_urls: links to external bug trackers
        """
        bug_urls = set(bug_urls)
        for watch in bug.watches:
            if watch.url in bug_urls:
                bug_urls.remove(watch.url)
            else:
                watch.destroySelf()
        bug_watch_set = getUtility(IBugWatchSet)
        for external_bug_url in bug_urls:
            bug_watch_set.fromText(external_bug_url, bug, self.bug_importer)

    def _make_bug_description(self, cve: CVE) -> str:
        """
        Some `CVE` fields can't be mapped to Launchpad models.

        They are saved to bug description.

        :param cve: `CVE` with information from UCT
        :return: bug description
        """
        parts = [cve.description]
        if cve.references:
            parts.extend(["", "References:"])
            parts.extend(cve.references)
        return "\n".join(parts)

    def _update_launchpad_cve(self, lp_cve: CveModel, cve: CVE) -> None:
        """
        Update LP's `Cve` model based on the information contained in `CVE`.

        :param lp_cve: LP's `CVE` model to be updated
        :param cve: `CVE` with information from UCT
        """
        for cvss in cve.cvss:
            lp_cve.setCVSSVectorForAuthority(
                cvss.authority, cvss.vector_string
            )
