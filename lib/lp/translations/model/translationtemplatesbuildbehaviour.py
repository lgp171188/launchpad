# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""An `IBuildFarmJobBehaviour` for `TranslationTemplatesBuild`.

Dispatches translation template build jobs to build-farm workers.
"""

__all__ = [
    'TranslationTemplatesBuildBehaviour',
    ]

import os
import re
import tempfile

import transaction
from twisted.internet import defer
from zope.component import getUtility
from zope.interface import implementer

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
    )
from lp.buildmaster.model.buildfarmjobbehaviour import (
    BuildFarmJobBehaviourBase,
    )
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.productseries import IProductSeriesSet
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue,
    )
from lp.translations.model.approver import TranslationBuildApprover


@implementer(IBuildFarmJobBehaviour)
class TranslationTemplatesBuildBehaviour(BuildFarmJobBehaviourBase):
    """Dispatches `TranslationTemplateBuildJob`s to workers."""

    builder_type = "translation-templates"

    # Filename for the tarball of templates that the worker builds.
    templates_tarball_path = 'translation-templates.tar.gz'

    unsafe_chars = '[^a-zA-Z0-9_+-]'

    ALLOWED_STATUS_NOTIFICATIONS = []

    def getLogFileName(self):
        """See `IBuildFarmJob`."""
        safe_name = re.sub(
            self.unsafe_chars, '_', self.build.branch.unique_name)
        return "translationtemplates_%s_%d.txt" % (safe_name, self.build.id)

    @property
    def archive(self):
        return self.distro_arch_series.main_archive

    @property
    def distro_arch_series(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        return ubuntu.currentseries.nominatedarchindep

    @property
    def pocket(self):
        return PackagePublishingPocket.RELEASE

    def extraBuildArgs(self, logger=None):
        args = super().extraBuildArgs(logger=logger)
        args["branch_url"] = self.build.branch.composePublicURL()
        return args

    def _readTarball(self, buildqueue, filemap, logger):
        """Read tarball with generated translation templates from worker."""
        if filemap is None:
            logger.error("Worker returned no filemap.")
            return defer.succeed(None)

        worker_filename = filemap.get(self.templates_tarball_path)
        if worker_filename is None:
            logger.error("Did not find templates tarball in worker output.")
            return defer.succeed(None)

        fd, fname = tempfile.mkstemp()
        os.close(fd)
        d = self._worker.getFile(worker_filename, fname)
        return d.addCallback(lambda ignored: fname)

    def _uploadTarball(self, branch, tarball, logger):
        """Upload tarball to productseries that want it."""
        queue = getUtility(ITranslationImportQueue)
        productseriesset = getUtility(IProductSeriesSet)
        related_series = (
            productseriesset.findByTranslationsImportBranch(branch))
        for series in related_series:
            queue.addOrUpdateEntriesFromTarball(
                tarball, False, branch.owner, productseries=series,
                approver_factory=TranslationBuildApprover)

    @defer.inlineCallbacks
    def handleSuccess(self, worker_status, logger):
        """Deal with a finished build job.

        Retrieves tarball and logs from the worker, then cleans up the
        worker so it's ready for a next job and destroys the queue item.

        If this fails for whatever unforeseen reason, a future run will
        retry it.
        """
        self.build.updateStatus(
            BuildStatus.UPLOADING,
            builder=self.build.buildqueue_record.builder)
        transaction.commit()
        logger.debug("Processing successful templates build.")
        filemap = worker_status.get('filemap')
        filename = yield self._readTarball(
            self.build.buildqueue_record, filemap, logger)

        if filename is None:
            logger.error("Build produced no tarball.")
        else:
            tarball_file = open(filename, "rb")
            try:
                logger.debug("Uploading translation templates tarball.")
                self._uploadTarball(
                    self.build.buildqueue_record.specific_build.branch,
                    tarball_file, logger)
                transaction.commit()
                logger.debug("Upload complete.")
            finally:
                tarball_file.close()
                os.remove(filename)
        return BuildStatus.FULLYBUILT
