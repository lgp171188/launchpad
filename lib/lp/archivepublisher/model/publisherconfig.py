# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database class for table PublisherConfig."""

__all__ = [
    "PublisherConfig",
    "PublisherConfigSet",
]

import os.path

from storm.locals import Int, Reference, Unicode
from zope.interface import implementer

from lp.archivepublisher.interfaces.publisherconfig import (
    IPublisherConfig,
    IPublisherConfigSet,
)
from lp.services.config import config
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase


@implementer(IPublisherConfig)
class PublisherConfig(StormBase):
    """See `IPublisherConfig`."""

    __storm_table__ = "PublisherConfig"

    id = Int(primary=True)

    distribution_id = Int(name="distribution", allow_none=False)
    distribution = Reference(distribution_id, "Distribution.id")

    root_dir = Unicode(name="root_dir", allow_none=False)

    base_url = Unicode(name="base_url", allow_none=False)

    copy_base_url = Unicode(name="copy_base_url", allow_none=False)

    @property
    def absolute_root_dir(self):
        """See `IPublisherConfig`."""
        if os.path.isabs(self.root_dir):
            return self.root_dir
        else:
            return os.path.join(
                config.archivepublisher.archives_dir, self.root_dir
            )


@implementer(IPublisherConfigSet)
class PublisherConfigSet:
    """See `IPublisherConfigSet`."""

    title = "Soyuz Publisher Configurations"

    def new(self, distribution, root_dir, base_url, copy_base_url):
        """Make and return a new `PublisherConfig`."""
        store = IPrimaryStore(PublisherConfig)
        pubconf = PublisherConfig()
        pubconf.distribution = distribution
        pubconf.root_dir = root_dir
        pubconf.base_url = base_url
        pubconf.copy_base_url = copy_base_url
        store.add(pubconf)
        return pubconf

    def getByDistribution(self, distribution):
        """See `IArchiveAuthTokenSet`."""
        return (
            IStore(PublisherConfig)
            .find(
                PublisherConfig,
                PublisherConfig.distribution_id == distribution.id,
            )
            .one()
        )
