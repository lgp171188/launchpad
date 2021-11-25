# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The processing of translated packages descriptions (ddtp) tarballs.

DDTP (Debian Descripton Translation Project) aims to offer the description
of all supported packages translated in several languages.

DDTP-TARBALL is a custom format upload supported by Launchpad infrastructure
to enable developers to publish indexes of DDTP contents.
"""

__all__ = [
    'DdtpTarballUpload',
    ]

import os

from zope.component import getUtility

from lp.archivepublisher.config import getPubConfig
from lp.archivepublisher.customupload import CustomUpload
from lp.registry.interfaces.distroseries import IDistroSeriesSet
from lp.services.features import getFeatureFlag
from lp.soyuz.enums import ArchivePurpose


class DdtpTarballUpload(CustomUpload):
    """DDTP (Debian Description Translation Project) tarball upload

    The tarball filename must be of the form:

     <NAME>_<COMPONENT>_<VERSION>.tar.gz

    where:

     * NAME: anything reasonable (ddtp-tarball);
     * COMPONENT: LP component (main, universe, etc);
     * VERSION: debian-like version token.

    It is consisted of a tarball containing all the supported indexes
    files for the DDTP system (under 'i18n' directory) contents driven
    by component.

    Results will be published (installed in archive) under:

       <ARCHIVE>dists/<SUITE>/<COMPONENT>/i18n

    Old contents will be preserved.
    """
    custom_type = "ddtp-tarball"

    @staticmethod
    def parsePath(tarfile_path):
        tarfile_base = os.path.basename(tarfile_path)
        bits = tarfile_base.split("_")
        if len(bits) != 3:
            raise ValueError("%s is not NAME_COMPONENT_VERSION" % tarfile_base)
        return tuple(bits)

    def setComponents(self, tarfile_path):
        _, self.component, self.version = self.parsePath(tarfile_path)
        self.arch = None

    def setTargetDirectory(self, archive, tarfile_path, suite):
        self.setComponents(tarfile_path)
        self.archive = archive
        self.distro_series, _ = getUtility(IDistroSeriesSet).fromSuite(
            archive.distribution, suite)
        pubconf = getPubConfig(archive)
        self.targetdir = os.path.join(
            pubconf.archiveroot, 'dists', suite, self.component)

    @classmethod
    def getSeriesKey(cls, tarfile_path):
        try:
            return cls.parsePath(tarfile_path)[1]
        except ValueError:
            return None

    def checkForConflicts(self):
        # We just overwrite older files, so no conflicts are possible.
        pass

    def shouldInstall(self, filename):
        # Ignore files outside of the i18n subdirectory
        if not filename.startswith("i18n/"):
            return False
        # apt-ftparchive or the PPA publisher (with slightly different
        # conditions depending on the archive purpose) may be configured to
        # create its own Translation-en files.  If so, we must take care not
        # to allow ddtp-tarball custom uploads to collide with those.
        if (filename == "i18n/Translation-en" or
                filename.startswith("i18n/Translation-en.")):
            # Compare with the step C condition in
            # PublishDistro.publishArchive.
            if self.archive.purpose in (
                    ArchivePurpose.PRIMARY, ArchivePurpose.COPY):
                # See FTPArchiveHandler.writeAptConfig.
                if not self.distro_series.include_long_descriptions:
                    return False
            else:
                # See Publisher._writeComponentIndexes.
                if (not self.distro_series.include_long_descriptions and
                        getFeatureFlag(
                            "soyuz.ppa.separate_long_descriptions")):
                    return False
        return True

    def fixCurrentSymlink(self):
        # There is no symlink to fix up for DDTP uploads
        pass
