# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
#
# This is the python package that defines the
# 'lp.archivepublisher.config' package. This package is related
# to managing the archive publisher's configuration as stored in the
# distribution and distroseries tables

import logging
import os

from zope.component import getUtility

from lp.archivepublisher.artifactory import ArtifactoryPool
from lp.archivepublisher.diskpool import DiskPool
from lp.archivepublisher.interfaces.publisherconfig import IPublisherConfigSet
from lp.registry.interfaces.distribution import IDistributionSet
from lp.services.config import config
from lp.soyuz.enums import (
    ArchivePublishingMethod,
    ArchivePurpose,
    ArchiveRepositoryFormat,
    archive_suffixes,
)

APT_FTPARCHIVE_PURPOSES = (ArchivePurpose.PRIMARY, ArchivePurpose.COPY)


def getPubConfig(archive):
    """Return an overridden Publisher Configuration instance.

    The original publisher configuration based on the distribution is
    modified according local context, it basically fixes the archive
    paths to cope with non-primary and PPA archives publication workflow.
    """
    pubconf = Config(archive)
    ppa_config = config.personalpackagearchive
    db_pubconf = getUtility(IPublisherConfigSet).getByDistribution(
        archive.distribution
    )
    if db_pubconf is None:
        return None

    pubconf.temproot = os.path.join(
        db_pubconf.absolute_root_dir, "%s-temp" % archive.distribution.name
    )

    if archive.publishing_method == ArchivePublishingMethod.ARTIFACTORY:
        if config.artifactory.base_url is None:
            raise AssertionError(
                "Cannot publish to Artifactory because "
                "config.artifactory.base_url is unset."
            )
        pubconf.distroroot = None
        # XXX cjwatson 2022-04-01: This assumes that only admins can
        # configure archives to publish to Artifactory, since Archive.name
        # isn't unique.  We may eventually need to use a new column with a
        # unique constraint, but this is enough to get us going for now.
        pubconf.archiveroot = "%s/%s" % (
            config.artifactory.base_url.rstrip("/"),
            archive.name,
        )
    elif archive.is_ppa:
        if archive.private:
            pubconf.distroroot = ppa_config.private_root
        else:
            pubconf.distroroot = ppa_config.root
        pubconf.archiveroot = os.path.join(
            pubconf.distroroot,
            archive.owner.name,
            archive.name,
            archive.distribution.name,
        )
    elif archive.is_main:
        pubconf.distroroot = db_pubconf.absolute_root_dir
        pubconf.archiveroot = os.path.join(
            pubconf.distroroot, archive.distribution.name
        )
        pubconf.archiveroot += archive_suffixes[archive.purpose]
    elif archive.is_copy:
        pubconf.distroroot = db_pubconf.absolute_root_dir
        pubconf.archiveroot = os.path.join(
            pubconf.distroroot,
            archive.distribution.name + "-" + archive.name,
            archive.distribution.name,
        )
    else:
        raise AssertionError(
            "Unknown archive purpose %s when getting publisher config.",
            archive.purpose,
        )

    # There can be multiple copy archives, so the temp dir needs to be
    # within the archive.
    if archive.is_copy:
        pubconf.temproot = pubconf.archiveroot + "-temp"

    if (
        archive.publishing_method == ArchivePublishingMethod.LOCAL
        and archive.purpose in APT_FTPARCHIVE_PURPOSES
    ):
        pubconf.overrideroot = pubconf.archiveroot + "-overrides"
        pubconf.cacheroot = pubconf.archiveroot + "-cache"
        pubconf.miscroot = pubconf.archiveroot + "-misc"
    else:
        pubconf.overrideroot = None
        pubconf.cacheroot = None
        pubconf.miscroot = None

    if archive.is_main:
        pubconf.signingroot = pubconf.archiveroot + "-uefi"
        if not os.path.exists(pubconf.signingroot):
            pubconf.signingroot = pubconf.archiveroot + "-signing"
        pubconf.signingautokey = False
    elif archive.is_ppa:
        signing_keys_root = os.path.join(ppa_config.signing_keys_root, "uefi")
        if not os.path.exists(signing_keys_root):
            signing_keys_root = os.path.join(
                ppa_config.signing_keys_root, "signing"
            )
        pubconf.signingroot = os.path.join(
            signing_keys_root, archive.owner.name, archive.name
        )
        pubconf.signingautokey = True
    else:
        pubconf.signingroot = None
        pubconf.signingautokey = False

    if archive.repository_format == ArchiveRepositoryFormat.DEBIAN:
        pubconf.poolroot = os.path.join(pubconf.archiveroot, "pool")
        pubconf.distsroot = os.path.join(pubconf.archiveroot, "dists")
    else:
        pubconf.poolroot = pubconf.archiveroot
        pubconf.distsroot = None

    # META_DATA custom uploads are stored in a separate directory
    # outside the archive root so Ubuntu Software Center can get some
    # data from P3As without accessing the P3A itself. But the metadata
    # hierarchy doesn't include the distribution name, so it conflicts
    # for PPAs with the same owner and name. META_DATA uploads are only used
    # by a few PPAs, and only by USC, so we leave metaroot unset and
    # ignore the uploads for anything except Ubuntu PPAs.
    ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    if (
        archive.publishing_method == ArchivePublishingMethod.LOCAL
        and archive.is_ppa
        and archive.distribution == ubuntu
    ):
        meta_root = os.path.join(pubconf.distroroot, archive.owner.name)
        pubconf.metaroot = os.path.join(meta_root, "meta", archive.name)
    else:
        pubconf.metaroot = None

    # Files under this directory are moved into distsroot by the publisher
    # the next time it runs.  This can be used by code that runs externally
    # to the publisher (e.g. Contents generation) to publish files in a
    # race-free way.
    if archive.is_main:
        pubconf.stagingroot = pubconf.archiveroot + "-staging"
    else:
        pubconf.stagingroot = None

    return pubconf


class Config:
    """Manage a publisher configuration from the database. (Read Only)
    This class provides a useful abstraction so that if we change
    how the database stores configuration then the publisher will not
    need to be re-coded to cope"""

    disk_pool_factory = {
        ArchivePublishingMethod.LOCAL: DiskPool,
        ArchivePublishingMethod.ARTIFACTORY: (
            # Artifactory publishing doesn't need a temporary directory on
            # the same filesystem as the pool, since the pool is remote
            # anyway.
            lambda archive, rootpath, temppath, logger: ArtifactoryPool(
                archive, rootpath, logger
            )
        ),
    }

    def __init__(self, archive):
        self.archive = archive

    def setupArchiveDirs(self):
        """Create missing required directories in archive."""
        if self.archive.publishing_method != ArchivePublishingMethod.LOCAL:
            return

        required_directories = [
            self.distroroot,
            self.poolroot,
            self.distsroot,
            self.archiveroot,
            self.cacheroot,
            self.overrideroot,
            self.miscroot,
            self.temproot,
            self.stagingroot,
        ]

        for directory in required_directories:
            if directory is None:
                continue
            if not os.path.exists(directory):
                os.makedirs(directory, 0o755)

    def getDiskPool(self, log, pool_root_override=None):
        """Return a DiskPool instance for this publisher configuration.

        It ensures the given archive location matches the minimal structure
        required.

        :param log: A logger.
        :param pool_root_override: Use this pool root for the archive
            instead of the one provided by the publishing configuration.
        """
        log.debug("Preparing on-disk pool representation.")
        dp_log = logging.getLogger("DiskPool")
        pool_root = pool_root_override
        if pool_root is None:
            pool_root = self.poolroot
        dp_factory = self.disk_pool_factory[self.archive.publishing_method]
        dp = dp_factory(self.archive, pool_root, self.temproot, dp_log)
        # Set the diskpool's log level to INFO to suppress debug output.
        dp_log.setLevel(logging.INFO)
        return dp
