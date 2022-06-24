# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the archivepublisher package."""
from typing import List

from lp.archivepublisher.interfaces.publisherconfig import IPublisherConfig
from lp.security import AdminByAdminsTeam

__all__ = []  # type: List[str]


class ViewPublisherConfig(AdminByAdminsTeam):
    usedfor = IPublisherConfig
