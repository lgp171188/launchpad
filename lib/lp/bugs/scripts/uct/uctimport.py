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

Three types of bug tags are created:

1. Bug tasks with a distribution package as a target - they represent
   importance of the package
2. Bug tasks with distribution series packages as a target - they represent
   importance and status of the package in a particular series
3. Bug tasks with a product as a target - they represent importance and
   status of the package in upstream.
"""
import logging
from datetime import timezone
from itertools import chain
from pathlib import Path
from typing import Dict, List, Optional

import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.bugs.interfaces.bug import CreateBugParams, IBugSet
from lp.bugs.interfaces.bugactivity import IBugActivitySet
from lp.bugs.interfaces.bugattachment import BugAttachmentType
from lp.bugs.interfaces.bugtask import BugTaskImportance, IBugTaskSet
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.bugs.interfaces.cve import ICveSet
from lp.bugs.interfaces.vulnerability import IVulnerabilitySet
from lp.bugs.model.bug import Bug as BugModel
from lp.bugs.model.bugtask import BugTask
from lp.bugs.model.cve import Cve as CveModel
from lp.bugs.model.vulnerability import Vulnerability
from lp.bugs.scripts.uct.models import CVE, UCTRecord
from lp.registry.model.distribution import Distribution
from lp.registry.model.person import Person
from lp.services.database.constants import UTC_NOW

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
        logger.info("Importing %s", cve_path)
        uct_record = UCTRecord.load(cve_path)
        cve = CVE.make_from_uct_record(uct_record)
        self.import_cve(cve)
        logger.info("%s was imported successfully", cve_path)

    def import_cve(self, cve: CVE) -> None:
        """
        Import a `CVE` instance to Launchpad database.

        :param cve: `CVE` with information from UCT
        """
        if cve.date_made_public is None:
            logger.warning(
                "%s does not have a publication date, "
                "is it embargoed? Aborting.",
                cve.sequence,
            )
            return
        if not cve.series_packages:
            logger.warning(
                "%s: could not find any affected packages, aborting.",
                cve.series_packages,
            )
            return
        lp_cve: CveModel = removeSecurityProxy(
            getUtility(ICveSet)[cve.sequence]
        )
        if lp_cve is None:
            logger.warning(
                "%s: could not find the CVE in LP. Aborting.", cve.sequence
            )
            return
        bug = self._find_existing_bug(cve, lp_cve)
        try:
            if bug is None:
                bug = self.create_bug(cve, lp_cve)
                logger.info(
                    "%s: created bug with ID: %s", cve.sequence, bug.id
                )
            else:
                logging.info(
                    "%s: found existing bug with ID: %s",
                    cve.sequence,
                    bug.id,
                )
                self.update_bug(bug, cve, lp_cve)
                logger.info(
                    "%s: updated bug with ID: %s", cve.sequence, bug.id
                )
            self._update_launchpad_cve(lp_cve, cve)
        except Exception:
            transaction.abort()
            raise

        if self.dry_run:
            logger.info(
                "%s: dry-run mode enabled, all changes are reverted.",
                cve.sequence,
            )
            transaction.abort()
        else:
            transaction.commit()

    def create_bug(self, cve: CVE, lp_cve: CveModel) -> BugModel:
        """
        Create a `Bug` model based on the information contained in a `CVE`.

        :param cve: `CVE` with information from UCT
        :param lp_cve: Launchpad `Cve` model
        """

        distro_package = cve.distro_packages[0]

        # Create the bug
        bug: BugModel = getUtility(IBugSet).createBug(
            CreateBugParams(
                comment=self._make_bug_description(cve),
                title=cve.sequence,
                information_type=InformationType.PUBLICSECURITY,
                owner=self.bug_importer,
                target=distro_package.target,
                importance=distro_package.importance,
                cve=lp_cve,
            )
        )

        self._update_external_bug_urls(bug, cve.bug_urls)
        self._update_patches(bug, cve.patch_urls)

        self._create_bug_tasks(
            bug,
            cve.distro_packages[1:],
            cve.series_packages,
            cve.upstream_packages,
        )
        self._update_statuses_and_importances(
            bug,
            cve.importance,
            cve.distro_packages,
            cve.series_packages,
            cve.upstream_packages,
        )
        self._assign_bug_tasks(bug, cve.assignee)

        # Make a note of the import in the activity log:
        getUtility(IBugActivitySet).new(
            bug=bug.id,
            datechanged=UTC_NOW,
            person=self.bug_importer,
            whatchanged="bug",
            message=f"UCT CVE entry {cve.sequence}",
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

        self._create_bug_tasks(
            bug,
            cve.distro_packages,
            cve.series_packages,
            cve.upstream_packages,
        )
        self._update_statuses_and_importances(
            bug,
            cve.importance,
            cve.distro_packages,
            cve.series_packages,
            cve.upstream_packages,
        )
        self._assign_bug_tasks(bug, cve.assignee)
        self._update_external_bug_urls(bug, cve.bug_urls)
        self._update_patches(bug, cve.patch_urls)

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
        upstream_packages: List[CVE.UpstreamPackage],
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
        bug_tasks: List[BugTask] = bug.bugtasks
        bug_task_by_target = {t.target: t for t in bug_tasks}
        bug_task_set = getUtility(IBugTaskSet)
        for package in chain(
            distro_packages, series_packages, upstream_packages
        ):
            if package.target not in bug_task_by_target:
                bug_task_set.createTask(bug, self.bug_importer, package.target)

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
        vulnerability: Vulnerability = getUtility(IVulnerabilitySet).new(
            distribution=distribution,
            status=cve.status,
            importance=cve.importance,
            creator=bug.owner,
            information_type=InformationType.PUBLICSECURITY,
            cve=lp_cve,
        )
        self._update_vulnerability(vulnerability, cve)

        vulnerability.linkBug(bug, bug.owner)

        logger.info(
            "%s: created vulnerability with ID: %s for distribution: %s",
            cve.sequence,
            vulnerability.id,
            distribution.name,
        )

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
        date_made_public = cve.date_made_public
        if date_made_public and date_made_public.tzinfo is None:
            date_made_public = date_made_public.replace(tzinfo=timezone.utc)
        date_notice_issued = cve.date_notice_issued
        if date_notice_issued and date_notice_issued.tzinfo is None:
            date_notice_issued = date_notice_issued.replace(
                tzinfo=timezone.utc
            )
        date_coordinated_release = cve.date_coordinated_release
        if (
            date_coordinated_release
            and date_coordinated_release.tzinfo is None
        ):
            date_coordinated_release = date_coordinated_release.replace(
                tzinfo=timezone.utc
            )

        vulnerability.status = cve.status
        vulnerability.description = cve.ubuntu_description
        vulnerability.notes = cve.notes
        vulnerability.mitigation = cve.mitigation
        vulnerability.importance = cve.importance
        vulnerability.date_made_public = date_made_public
        vulnerability.date_notice_issued = date_notice_issued
        vulnerability.date_coordinated_release = date_coordinated_release

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
        upstream_packages: List[CVE.UpstreamPackage],
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
        bug_tasks: List[BugTask] = bug.bugtasks
        bug_task_by_target = {t.target: t for t in bug_tasks}

        package_importances: Dict[str, BugTaskImportance] = {}

        for dp in distro_packages:
            task = bug_task_by_target[dp.target]
            dp_importance = dp.importance or cve_importance
            package_importances[dp.package_name.name] = dp_importance
            task.transitionToImportance(dp_importance)

        for sp in chain(series_packages, upstream_packages):
            task = bug_task_by_target[sp.target]
            package_name = sp.package_name.name
            package_importance = package_importances[package_name]
            sp_importance = sp.importance or package_importance
            task.transitionToImportance(sp_importance)
            task.transitionToStatus(sp.status)
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

    def _update_patches(self, bug: BugModel, patch_urls: List[CVE.PatchURL]):
        attachments_by_url = {a.url: a for a in bug.attachments if a.url}
        for patch_url in patch_urls:
            title = f"{patch_url.package_name.name}/{patch_url.type}"
            if patch_url.notes:
                title = f"{title}/{patch_url.notes}"
            if patch_url in attachments_by_url:
                attachment = removeSecurityProxy(
                    attachments_by_url[patch_url.url]
                )
                attachment.title = title
                attachment.type = BugAttachmentType.PATCH
            else:
                bug.addAttachment(
                    owner=bug.owner,
                    data=None,
                    comment=None,
                    filename=None,
                    url=patch_url.url,
                    is_patch=True,
                    description=title,
                )

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
        lp_cve.discovered_by = cve.discovered_by
