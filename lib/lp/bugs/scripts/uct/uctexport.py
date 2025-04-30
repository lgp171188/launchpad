#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.bugs.interfaces.bug import IBugSet
from lp.bugs.interfaces.bugattachment import BugAttachmentType
from lp.bugs.model.bug import Bug as BugModel
from lp.bugs.model.bugtask import BugTask
from lp.bugs.model.cve import Cve as CveModel
from lp.bugs.model.vulnerability import Vulnerability
from lp.bugs.scripts.uct.models import CVE, CVSS
from lp.registry.model.distributionsourcepackage import (
    DistributionSourcePackage,
)
from lp.registry.model.product import Product
from lp.registry.model.sourcepackage import SourcePackage
from lp.registry.model.sourcepackagename import SourcePackageName

__all__ = [
    "UCTExporter",
]


logger = logging.getLogger(__name__)


class UCTExporter:
    """
    `UCTExporter` is used to export LP Bugs, Vulnerabilities and Cve's to
    UCT CVE files.
    """

    class ParsedDescription(NamedTuple):
        description: str
        references: List[str]

    # Example:
    # linux/upstream
    # linux/upstream/5.19.1
    BUG_ATTACHMENT_TITLE_RE = re.compile(
        "^(?P<package_name>.+?)/(?P<patch_type>.+?)(/(?P<notes>.+?))?$"
    )

    def export_bug_to_uct_file(
        self, bug_id: int, output_dir: Path
    ) -> Optional[Path]:
        """
        Export a bug with the given bug_id as a
        UCT CVE record file in the `output_dir`

        :param bug_id: ID of the `Bug` model to be exported
        :param output_dir: the directory where the exported file will be stored
        :return: path to the exported file
        """
        bug = getUtility(IBugSet).get(bug_id)
        if not bug:
            logger.error("Could not find a bug with ID: %s", bug_id)
            return
        cve = self._make_cve_from_bug(bug)
        uct_record = cve.to_uct_record()
        save_to_path = uct_record.save(output_dir)
        logger.info(
            "Bug with ID: %s is exported to: %s", bug_id, str(save_to_path)
        )
        return save_to_path

    def _make_cve_from_bug(self, bug: BugModel) -> CVE:
        """
        Create a `CVE` instances from a `Bug` model and the related
        Vulnerabilities and `Cve`.

        `BugTasks` are converted to `CVE.DistroPackage` and `CVE.SeriesPackage`
        objects.

        Other `CVE` fields are populated from the information contained in the
        `Bug`, its related Vulnerabilities and LP `Cve` model.

        :param bug: `Bug` model
        :return: `CVE` instance
        """
        vulnerabilities = list(bug.vulnerabilities)
        if not vulnerabilities:
            raise ValueError(
                f"Bug with ID: {bug.id} does not have vulnerabilities"
            )
        vulnerability: Vulnerability = vulnerabilities[0]
        if not vulnerability.cve:
            raise ValueError(
                "Bug with ID: {} - vulnerability "
                "is not linked to a CVE".format(bug.id)
            )
        lp_cve: CveModel = vulnerability.cve

        parsed_description = self._parse_bug_description(bug.description)

        bug_urls = []
        for bug_watch in bug.watches:
            bug_urls.append(bug_watch.url)

        bug_tasks: List[BugTask] = list(bug.bugtasks)

        cve_importance = vulnerability.importance

        # When exporting, we shouldn't output the importance value if it
        # hasn't been specified in the original UCT file.
        # So, the following logic is used:
        #  - DistroPackage: export importance only if it's different from
        #  the CVE importance
        #  - SeriesPackage: export importance only if it's different from the
        #  DistroPackage importance
        package_importances = {}

        package_name_by_product: Dict[Product, SourcePackageName] = {}
        # We need to process all distribution package tasks before processing
        # the distro-series tasks to collect importance value for each package.
        distro_packages = []
        for bug_task in bug_tasks:
            target = removeSecurityProxy(bug_task.target)
            if not isinstance(target, DistributionSourcePackage):
                continue
            # This is the `Product` corresponding to the package of this
            # name with the highest version across any of this
            # distribution's series that has a packaging link
            # (it can make a difference if a package name switches to a
            # different upstream project between series)
            product = target.upstream_product
            if product:
                package_name_by_product[product] = target.sourcepackagename
            dp_importance = bug_task.importance
            package_importances[target.sourcepackagename] = dp_importance
            distro_packages.append(
                CVE.DistroPackage(
                    target=target,
                    package_name=target.sourcepackagename,
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
                    target=target,
                    package_name=target.sourcepackagename,
                    importance=(
                        sp_importance
                        if sp_importance != package_importance
                        else None
                    ),
                    status=bug_task.status,
                    status_explanation=bug_task.status_explanation,
                )
            )

        upstream_packages = []
        for bug_task in bug_tasks:
            target = removeSecurityProxy(bug_task.target)
            if not isinstance(target, Product):
                continue
            if target not in package_name_by_product:
                logger.warning(
                    "Could not find a source package for product %s",
                    target.name,
                )
                continue
            package_name = package_name_by_product[target]
            up_importance = bug_task.importance
            package_importance = package_importances.get(target.name)
            upstream_packages.append(
                CVE.UpstreamPackage(
                    target=target,
                    package_name=package_name,
                    importance=(
                        up_importance
                        if up_importance != package_importance
                        else None
                    ),
                    status=bug_task.status,
                    status_explanation=bug_task.status_explanation,
                )
            )

        packages_by_name = {
            p.name: p for p in package_name_by_product.values()
        }
        patch_urls = []
        for attachment in bug.attachments:
            if (
                not attachment.url
                or not attachment.type == BugAttachmentType.PATCH
            ):
                continue
            title_match = self.BUG_ATTACHMENT_TITLE_RE.match(attachment.title)
            if not title_match:
                continue
            spn = packages_by_name.get(title_match.groupdict()["package_name"])
            if not spn:
                continue
            patch_urls.append(
                CVE.PatchURL(
                    package_name=spn,
                    type=title_match.groupdict()["patch_type"],
                    url=attachment.url,
                    notes=title_match.groupdict().get("notes"),
                )
            )

        return CVE(
            sequence=f"CVE-{lp_cve.sequence}",
            date_made_public=vulnerability.date_made_public,
            date_notice_issued=vulnerability.date_notice_issued,
            date_coordinated_release=vulnerability.date_coordinated_release,
            distro_packages=distro_packages,
            series_packages=series_packages,
            upstream_packages=upstream_packages,
            importance=cve_importance,
            importance_explanation=vulnerability.importance_explanation,
            status=vulnerability.status,
            assignee=bug_tasks[0].assignee,
            discovered_by=lp_cve.discovered_by or "",
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
                for authority in lp_cve.cvss
                for vector_string in lp_cve.cvss[authority]
            ],
            global_tags=set(bug.tags),
            patch_urls=patch_urls,
        )

    def _parse_bug_description(
        self, bug_description: str
    ) -> "ParsedDescription":
        """
        Some `CVE` fields can't be mapped to Launchpad models.
        They are saved to bug description.

        This method extracts those fields from the bug description.

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
