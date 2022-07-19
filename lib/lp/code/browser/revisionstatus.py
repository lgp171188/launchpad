# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lp.code.enums import RevisionStatusResult
from lp.code.interfaces.revisionstatus import IRevisionStatusArtifact
from lp.services.librarian.browser import FileNavigationMixin
from lp.services.webapp import Navigation
from lp.services.webapp.batching import BatchNavigator


class RevisionStatusArtifactNavigation(Navigation, FileNavigationMixin):
    """Traversal to +files/${filename}."""

    usedfor = IRevisionStatusArtifact


class HasRevisionStatusReportsMixin:
    def getStatusReports(self, commit_sha1):
        reports = self.context.getStatusReports(commit_sha1)
        return BatchNavigator(reports, self.request)

    def getOverallIcon(self, repository, commit_sha1):
        """Show an appropriate icon at the top of the report."""
        icon_template = (
            '<img width="14" height="14" alt="%(title)s" '
            'title="%(title)s" src="%(src)s" />'
        )
        reports = repository.getStatusReports(commit_sha1)
        if all(
            report.result == RevisionStatusResult.SKIPPED for report in reports
        ):
            title = "Skipped"
            source = "/@@/yes-gray"
        elif all(
            report.result
            in (RevisionStatusResult.SUCCEEDED, RevisionStatusResult.SKIPPED)
            for report in reports
        ):
            title = "Succeeded"
            source = "/@@/yes"
        elif any(
            report.result
            in (RevisionStatusResult.FAILED, RevisionStatusResult.CANCELLED)
            for report in reports
        ):
            title = "Failed"
            source = "/@@/no"
        else:
            title = "In progress"
            source = "/@@/processing"
        return icon_template % {"title": title, "src": source}
