# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

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
