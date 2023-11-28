# Copyright 2014-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""An `IBuildFarmJobBehaviour` for `LiveFSBuild`.

Dispatches live filesystem build jobs to build-farm workers.
"""

__all__ = [
    "LiveFSBuildBehaviour",
]

from typing import Any, Generator, cast

from twisted.internet import defer
from zope.component import adapter
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildBaseImageType
from lp.buildmaster.interfaces.builder import CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    BuildArgs,
    IBuildFarmJobBehaviour,
)
from lp.buildmaster.model.buildfarmjobbehaviour import (
    BuildFarmJobBehaviourBase,
)
from lp.registry.interfaces.series import SeriesStatus
from lp.services.config import config
from lp.services.twistedsupport import cancel_on_timeout
from lp.soyuz.adapters.archivedependencies import get_sources_list_for_building
from lp.soyuz.interfaces.archive import ArchiveDisabled
from lp.soyuz.interfaces.livefs import LiveFSBuildArchiveOwnerMismatch
from lp.soyuz.interfaces.livefsbuild import ILiveFSBuild


@adapter(ILiveFSBuild)
@implementer(IBuildFarmJobBehaviour)
class LiveFSBuildBehaviour(BuildFarmJobBehaviourBase):
    """Dispatches `LiveFSBuild` jobs to workers."""

    builder_type = "livefs"
    image_types = [BuildBaseImageType.LXD, BuildBaseImageType.CHROOT]

    def getLogFileName(self):
        das = self.build.distro_arch_series
        archname = das.architecturetag
        if self.build.unique_key:
            archname += "_%s" % self.build.unique_key

        # Examples:
        #   buildlog_ubuntu_trusty_i386_ubuntu-desktop_FULLYBUILT.txt
        return "buildlog_%s_%s_%s_%s_%s.txt" % (
            das.distroseries.distribution.name,
            das.distroseries.name,
            archname,
            self.build.livefs.name,
            self.build.status.name,
        )

    def verifyBuildRequest(self, logger):
        """Assert some pre-build checks.

        The build request is checked:
         * Virtualized builds can't build on a non-virtual builder
         * The source archive may not be disabled
         * If the source archive is private, the livefs owner must match the
           archive owner (see `LiveFSBuildArchiveOwnerMismatch` docstring)
         * Ensure that we have a chroot
        """
        build = self.build
        if build.virtualized and not self._builder.virtualized:
            raise AssertionError(
                "Attempt to build virtual item on a non-virtual builder."
            )

        if not build.archive.enabled:
            raise ArchiveDisabled(build.archive.displayname)
        if build.archive.private and build.livefs.owner != build.archive.owner:
            raise LiveFSBuildArchiveOwnerMismatch()

        chroot = build.distro_arch_series.getChroot(pocket=build.pocket)
        if chroot is None:
            raise CannotBuild(
                "Missing chroot for %s" % build.distro_arch_series.displayname
            )

    def issueMacaroon(self):
        """See `IBuildFarmJobBehaviour`."""
        return cancel_on_timeout(
            self._authserver.callRemote(
                "issueMacaroon", "livefs-build", "LiveFSBuild", self.build.id
            ),
            config.builddmaster.authentication_timeout,
        )

    @defer.inlineCallbacks
    def extraBuildArgs(self, logger=None) -> Generator[Any, Any, BuildArgs]:
        """
        Return the extra arguments required by the worker for the given build.
        """
        build = self.build
        base_args: BuildArgs = yield super().extraBuildArgs(logger=logger)
        # Non-trivial metadata values may have been security-wrapped, which
        # is pointless here and just gets in the way of xmlrpc.client
        # serialisation.
        args = cast(
            BuildArgs, dict(removeSecurityProxy(build.livefs.metadata))
        )
        if build.metadata_override is not None:
            args.update(removeSecurityProxy(build.metadata_override))
        # Everything else overrides anything in the metadata.
        # https://github.com/python/mypy/issues/6462
        args.update(base_args)  # type: ignore[typeddict-item]
        args["pocket"] = build.pocket.name.lower()
        args["datestamp"] = build.version
        (
            args["archives"],
            args["trusted_keys"],
        ) = yield get_sources_list_for_building(
            self, build.distro_arch_series, None, logger=logger
        )
        return args

    def verifySuccessfulBuild(self):
        """See `IBuildFarmJobBehaviour`."""
        # The implementation in BuildFarmJobBehaviourBase checks whether the
        # target suite is modifiable in the target archive.  However, a
        # `LiveFSBuild`'s archive is a source rather than a target, so that
        # check does not make sense.  We do, however, refuse to build for
        # obsolete series.
        assert self.build.distro_series.status != SeriesStatus.OBSOLETE
