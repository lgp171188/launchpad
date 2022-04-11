# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""An `IBuildFarmJobBehaviour` for `CIBuild`."""

__all__ = [
    "CIBuildBehaviour",
    ]

import json
import os

from twisted.internet import defer
from zope.component import adapter
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.builderproxy import BuilderProxyMixin
from lp.buildmaster.enums import BuildBaseImageType
from lp.buildmaster.interfaces.builder import CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
    )
from lp.buildmaster.model.buildfarmjobbehaviour import (
    BuildFarmJobBehaviourBase,
    )
from lp.code.interfaces.cibuild import ICIBuild
from lp.soyuz.adapters.archivedependencies import (
    get_sources_list_for_building,
    )


@adapter(ICIBuild)
@implementer(IBuildFarmJobBehaviour)
class CIBuildBehaviour(BuilderProxyMixin, BuildFarmJobBehaviourBase):
    """Dispatches `CIBuild` jobs to builders."""

    builder_type = "ci"
    image_types = [BuildBaseImageType.LXD, BuildBaseImageType.CHROOT]

    ALLOWED_STATUS_NOTIFICATIONS = []

    def getLogFileName(self):
        return "buildlog_ci_%s_%s_%s.txt" % (
            self.build.git_repository.name, self.build.commit_sha1,
            self.build.status.name)

    def verifyBuildRequest(self, logger):
        """Assert some pre-build checks.

        The build request is checked:
         * Virtualized builds can't build on a non-virtual builder
         * We have a base image
        """
        build = self.build
        if build.virtualized and not self._builder.virtualized:
            raise AssertionError(
                "Attempt to build virtual item on a non-virtual builder.")

        chroot = build.distro_arch_series.getChroot(pocket=build.pocket)
        if chroot is None:
            raise CannotBuild(
                "Missing chroot for %s" % build.distro_arch_series.displayname)

    @defer.inlineCallbacks
    def extraBuildArgs(self, logger=None):
        """Return extra builder arguments for this build."""
        build = self.build
        if not build.stages:
            raise CannotBuild(
                "No stages defined for %s:%s" %
                (build.git_repository.unique_name, build.commit_sha1))

        args = yield super().extraBuildArgs(logger=logger)
        yield self.addProxyArgs(args)
        args["archives"], args["trusted_keys"] = (
            yield get_sources_list_for_building(
                self, build.distro_arch_series, None, logger=logger))
        args["jobs"] = removeSecurityProxy(build.stages)
        args["git_repository"] = build.git_repository.git_https_url
        args["git_path"] = build.commit_sha1
        args["private"] = build.is_private
        return args

    def verifySuccessfulBuild(self):
        """See `IBuildFarmJobBehaviour`."""
        # We have no interesting checks to perform here.

    @defer.inlineCallbacks
    def _downloadFiles(self, worker_status, upload_path, logger):
        # In addition to downloading everything from the filemap, we need to
        # save the "jobs" field in order to reliably map files to individual
        # CI jobs.
        if "jobs" in worker_status:
            jobs_path = os.path.join(upload_path, "jobs.json")
            with open(jobs_path, "w") as jobs_file:
                json.dump(worker_status["jobs"], jobs_file)
        yield super()._downloadFiles(worker_status, upload_path, logger)
