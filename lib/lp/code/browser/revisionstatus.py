# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lp.code.interfaces.revisionstatus import IRevisionStatusArtifact
from lp.services.librarian.browser import FileNavigationMixin
from lp.services.webapp import Navigation


class RevisionStatusArtifactNavigation(Navigation, FileNavigationMixin):
    """Traversal to +files/${filename}."""

    usedfor = IRevisionStatusArtifact
