# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""An `IBuildFarmJobBehaviour` for `CraftRecipeBuild`.

Dispatches craft recipe build jobs to build-farm workers.
"""

__all__ = [
    "CraftRecipeBuildBehaviour",
]

from typing import Any, Generator

from twisted.internet import defer
from zope.component import adapter
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.builderproxy import BuilderProxyMixin
from lp.buildmaster.enums import BuildBaseImageType
from lp.buildmaster.interfaces.builder import CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    BuildArgs,
    IBuildFarmJobBehaviour,
)
from lp.buildmaster.model.buildfarmjobbehaviour import (
    BuildFarmJobBehaviourBase,
)
from lp.crafts.interfaces.craftrecipebuild import ICraftRecipeBuild
from lp.registry.interfaces.series import SeriesStatus
from lp.soyuz.adapters.archivedependencies import get_sources_list_for_building


@adapter(ICraftRecipeBuild)
@implementer(IBuildFarmJobBehaviour)
class CraftRecipeBuildBehaviour(BuilderProxyMixin, BuildFarmJobBehaviourBase):
    """Dispatches `CraftRecipeBuild` jobs to workers."""

    builder_type = "craft"
    image_types = [BuildBaseImageType.LXD, BuildBaseImageType.CHROOT]

    def getLogFileName(self):
        das = self.build.distro_arch_series

        # Examples:
        #   buildlog_craft_ubuntu_wily_amd64_name_FULLYBUILT.txt
        return "buildlog_craft_%s_%s_%s_%s_%s.txt" % (
            das.distroseries.distribution.name,
            das.distroseries.name,
            das.architecturetag,
            self.build.recipe.name,
            self.build.status.name,
        )

    def verifyBuildRequest(self, logger):
        """Assert some pre-build checks.

        The build request is checked:
         * Virtualized builds can't build on a non-virtual builder
         * Ensure that we have a chroot
        """
        build = self.build
        if build.virtualized and not self._builder.virtualized:
            raise AssertionError(
                "Attempt to build virtual item on a non-virtual builder."
            )

        chroot = build.distro_arch_series.getChroot()
        if chroot is None:
            raise CannotBuild(
                "Missing chroot for %s" % build.distro_arch_series.displayname
            )

    @defer.inlineCallbacks
    def extraBuildArgs(self, logger=None) -> Generator[Any, Any, BuildArgs]:
        """
        Return the extra arguments required by the worker for the given build.
        """
        build = self.build
        args: BuildArgs = yield super().extraBuildArgs(logger=logger)
        yield self.startProxySession(
            args, use_fetch_service=build.recipe.use_fetch_service
        )
        args["name"] = build.recipe.store_name or build.recipe.name
        channels = build.channels or {}
        # We have to remove the security proxy that Zope applies to this
        # dict, since otherwise we'll be unable to serialise it to XML-RPC.
        args["channels"] = removeSecurityProxy(channels)
        (
            args["archives"],
            args["trusted_keys"],
        ) = yield get_sources_list_for_building(
            self, build.distro_arch_series, None, logger=logger
        )
        if build.recipe.build_path is not None:
            args["build_path"] = build.recipe.build_path
        if build.recipe.git_ref is not None:
            if build.recipe.git_ref.repository_url is not None:
                args["git_repository"] = build.recipe.git_ref.repository_url
            else:
                args["git_repository"] = (
                    build.recipe.git_repository.git_https_url
                )
            # "git clone -b" doesn't accept full ref names.  If this becomes
            # a problem then we could change launchpad-buildd to do "git
            # clone" followed by "git checkout" instead.
            if build.recipe.git_path != "HEAD":
                args["git_path"] = build.recipe.git_ref.name
        else:
            raise CannotBuild(
                "Source repository for ~%s/%s/+craft/%s has been deleted."
                % (
                    build.recipe.owner.name,
                    build.recipe.project.name,
                    build.recipe.name,
                )
            )
        args["private"] = build.is_private
        return args

    def verifySuccessfulBuild(self):
        """See `IBuildFarmJobBehaviour`."""
        # The implementation in BuildFarmJobBehaviourBase checks whether the
        # target suite is modifiable in the target archive.  However, a
        # `CraftRecipeBuild`'s archive is a source rather than a target, so
        # that check does not make sense.  We do, however, refuse to build
        # for obsolete series.
        assert self.build.distro_series.status != SeriesStatus.OBSOLETE

    @defer.inlineCallbacks
    def _saveBuildSpecificFiles(self, upload_path):
        yield self.endProxySession(upload_path)
