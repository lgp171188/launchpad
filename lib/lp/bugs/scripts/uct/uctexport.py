#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

import logging
from collections import defaultdict
from pathlib import Path
from typing import List, NamedTuple

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.bugs.interfaces.bug import IBugSet
from lp.bugs.model.bug import Bug as BugModel
from lp.bugs.model.bugtask import BugTask
from lp.bugs.model.cve import Cve as CveModel
from lp.bugs.model.vulnerability import Vulnerability
from lp.registry.model.distributionsourcepackage import (
    DistributionSourcePackage,
)
from lp.registry.model.sourcepackage import SourcePackage

from .models import CVE, CVSS

__all__ = [
    "UCTExporter",
]


logger = logging.getLogger(__name__)


class UCTExporter:
    """
    `UCTExporter` is used to export LP Bugs, Vulnerabilities and Cve's to
    UCT CVE files.
    """

    ParsedDescription = NamedTuple(
        "ParsedDescription",
        (
            ("description", str),
            ("references", List[str]),
        ),
    )

    def export_bug_to_uct_file(self, bug_id: int, output_dir: Path) -> Path:
        """
        Export a bug with the given bug_id as a
        UCT CVE record file in the `output_dir`

        :param bug_id: ID of the `Bug` model to be exported
        :param output_dir: the directory where the exported file will be stored
        :return: path to the exported file
        """
        bug = getUtility(IBugSet).get(bug_id)
        if not bug:
            raise ValueError("Could not find bug with ID: {}".format(bug_id))
        cve = self._make_cve_from_bug(bug)
        uct_record = cve.to_uct_record()
        save_to_path = uct_record.save(output_dir)
        logger.info(
            "Bug with ID: %s is saved to path: %s", bug_id, str(save_to_path)
        )
        return save_to_path

    def _make_cve_from_bug(self, bug: BugModel) -> CVE:
        """
        Create a `CVE` instances from a `Bug` model and the related
        Vulnerabilities and `Cve`.

        `BugTasks` are converted to `CVE.DistroPackage` and `CVE.SEriesPackage`
        objects.

        Other `CVE` fields are populated from the information contained in the
        `Bug`, its related Vulnerabilities and LP `Cve` model.

        :param bug: `Bug` model
        :return: `CVE` instance
        """
        vulnerabilities = list(bug.vulnerabilities)
        if not vulnerabilities:
            raise ValueError(
                "Bug with ID: {} does not have vulnerabilities".format(bug.id)
            )
        vulnerability = vulnerabilities[0]  # type: Vulnerability
        if not vulnerability.cve:
            raise ValueError(
                "Bug with ID: {} - vulnerability "
                "is not linked to a CVE".format(bug.id)
            )
        lp_cve = vulnerability.cve  # type: CveModel

        parsed_description = self._parse_bug_description(bug.description)

        bug_urls = []
        for bug_watch in bug.watches:
            bug_urls.append(bug_watch.url)

        bug_tasks = list(bug.bugtasks)  # type: List[BugTask]

        cve_importance = vulnerability.importance
        package_importances = {}

        distro_packages = []
        for bug_task in bug_tasks:
            target = removeSecurityProxy(bug_task.target)
            if not isinstance(target, DistributionSourcePackage):
                continue
            dp_importance = bug_task.importance
            package_importances[target.sourcepackagename] = dp_importance
            distro_packages.append(
                CVE.DistroPackage(
                    package=target,
                    importance=(
                        dp_importance
                        if dp_importance != cve_importance
                        else None
                    ),
                )
            )

        series_packages = []
        for bug_task in bug_tasks:
            target = removeSecurityProxy(bug_task.target)
            if not isinstance(target, SourcePackage):
                continue
            sp_importance = bug_task.importance
            package_importance = package_importances[target.sourcepackagename]
            series_packages.append(
                CVE.SeriesPackage(
                    package=target,
                    importance=(
                        sp_importance
                        if sp_importance != package_importance
                        else None
                    ),
                    status=bug_task.status,
                    status_explanation=bug_task.status_explanation,
                )
            )

        return CVE(
            sequence="CVE-{}".format(lp_cve.sequence),
            crd=None,  # TODO: fix this
            public_date=vulnerability.date_made_public,
            public_date_at_USN=None,  # TODO: fix this
            distro_packages=distro_packages,
            series_packages=series_packages,
            importance=cve_importance,
            status=vulnerability.status,
            assignee=bug_tasks[0].assignee,
            discovered_by="",  # TODO: fix this
            description=parsed_description.description,
            ubuntu_description=vulnerability.description,
            bug_urls=bug_urls,
            references=parsed_description.references,
            notes=vulnerability.notes,
            mitigation=vulnerability.mitigation,
            cvss=[
                CVSS(
                    authority=authority,
                    vector_string=vector_string,
                )
                for authority, vector_string in lp_cve.cvss.items()
            ],
        )

    def _parse_bug_description(
        self, bug_description: str
    ) -> "ParsedDescription":
        """
        Some `CVE` fields can't be mapped to Launchpad models.
        They are saved to bug description.

        This method extract those fields from the bug description.

        :param bug_description: bug description
        :return: parsed description
        """
        field_values = defaultdict(list)
        current_field = "description"
        known_fields = {
            "References:": "references",
        }
        lines = bug_description.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line in known_fields:
                current_field = known_fields[line]
                continue
            field_values[current_field].append(line)
        return UCTExporter.ParsedDescription(
            description="\n".join(field_values.get("description", [])),
            references=field_values.get("references", []),
        )
