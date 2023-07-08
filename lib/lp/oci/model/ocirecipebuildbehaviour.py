# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""An `IBuildFarmJobBehaviour` for `OCIRecipeBuild`.

Dispatches OCI image build jobs to build-farm workers.
"""

__all__ = [
    "OCIRecipeBuildBehaviour",
]


import json
import os
from datetime import datetime, timezone
from typing import Any, Generator

from twisted.internet import defer
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.builderproxy import BuilderProxyMixin
from lp.buildmaster.enums import BuildBaseImageType
from lp.buildmaster.interfaces.builder import BuildDaemonError, CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    BuildArgs,
    IBuildFarmJobBehaviour,
)
from lp.buildmaster.model.buildfarmjobbehaviour import (
    BuildFarmJobBehaviourBase,
)
from lp.code.interfaces.codehosting import LAUNCHPAD_SERVICES
from lp.oci.interfaces.ocirecipebuild import IOCIFileSet
from lp.registry.interfaces.series import SeriesStatus
from lp.services.config import config
from lp.services.librarian.utils import copy_and_close
from lp.services.twistedsupport import cancel_on_timeout
from lp.services.webapp import canonical_url
from lp.soyuz.adapters.archivedependencies import get_sources_list_for_building


@implementer(IBuildFarmJobBehaviour)
class OCIRecipeBuildBehaviour(BuilderProxyMixin, BuildFarmJobBehaviourBase):
    builder_type = "oci"
    image_types = [BuildBaseImageType.LXD, BuildBaseImageType.CHROOT]

    def getLogFileName(self):
        series = self.build.distro_series

        # Examples:
        #   buildlog_oci_ubuntu_wily_amd64_name_FULLYBUILT.txt
        return "buildlog_oci_%s_%s_%s_%s_%s.txt" % (
            series.distribution.name,
            series.name,
            self.build.processor.name,
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

        chroot = build.distro_arch_series.getChroot(pocket=build.pocket)
        if chroot is None:
            raise CannotBuild(
                "Missing chroot for %s" % build.distro_arch_series.displayname
            )

    def issueMacaroon(self):
        """See `IBuildFarmJobBehaviour`."""
        return cancel_on_timeout(
            self._authserver.callRemote(
                "issueMacaroon",
                "oci-recipe-build",
                "OCIRecipeBuild",
                self.build.id,
            ),
            config.builddmaster.authentication_timeout,
        )

    def _getBuildInfoArgs(self):
        def format_user(user):
            if user is None:
                return None
            hide_email = not user.preferredemail or user.hide_email_addresses
            return {
                "name": user.name,
                "email": (None if hide_email else user.preferredemail.email),
            }

        build = self.build
        build_request = build.build_request
        builds = list(build_request.builds) if build_request else [build]
        info = {
            "architectures": [],
            "recipe_owner": format_user(self.build.recipe.owner),
            "build_request_id": None,
            "build_request_timestamp": None,
            # With build_request set, all builds in this list will have the
            # same requester. Without build_request, we only care about the
            # only existing build in this list.
            "build_requester": format_user(builds[0].requester),
            # Build URL per architecture.
            "build_urls": {},
        }
        if build_request:
            info["build_request_id"] = build_request.id
            info[
                "build_request_timestamp"
            ] = build_request.date_requested.isoformat()
        info["architectures"] = [
            i.distro_arch_series.architecturetag for i in builds
        ]
        info["build_urls"] = {
            i.distro_arch_series.architecturetag: canonical_url(i)
            for i in builds
        }
        return info

    @defer.inlineCallbacks
    def extraBuildArgs(self, logger=None) -> Generator[Any, Any, BuildArgs]:
        """
        Return the extra arguments required by the worker for the given build.
        """
        build = self.build
        args = yield super().extraBuildArgs(logger=logger)  # type: BuildArgs
        yield self.addProxyArgs(args, build.recipe.allow_internet)
        # XXX twom 2020-02-17 This may need to be more complex, and involve
        # distribution name.
        args["name"] = build.recipe.name
        (
            args["archives"],
            args["trusted_keys"],
        ) = yield get_sources_list_for_building(
            self,
            build.distro_arch_series,
            None,
            tools_source=None,
            tools_fingerprint=None,
            logger=logger,
        )

        args["build_file"] = build.recipe.build_file

        # Do our work on a new dict, so we don't try to update the
        # copy on the model
        build_args = {
            "LAUNCHPAD_BUILD_ARCH": build.distro_arch_series.architecturetag
        }
        # We have to remove the security proxy that Zope applies to this
        # dict, since otherwise we'll be unable to serialise it to
        # XML-RPC.
        build_args.update(removeSecurityProxy(build.recipe.build_args))
        args["build_args"] = build_args
        args["build_path"] = build.recipe.build_path
        args["metadata"] = self._getBuildInfoArgs()

        if build.recipe.git_ref is not None:
            if build.recipe.git_repository.private:
                macaroon_raw = yield self.issueMacaroon()
                url = build.recipe.git_repository.getCodebrowseUrl(
                    username=LAUNCHPAD_SERVICES, password=macaroon_raw
                )
                args["git_repository"] = url
            else:
                args[
                    "git_repository"
                ] = build.recipe.git_repository.git_https_url
        else:
            raise CannotBuild(
                "Source repository for ~%s/%s has been deleted."
                % (build.recipe.owner.name, build.recipe.name)
            )

        if build.recipe.git_path != "HEAD":
            args["git_path"] = build.recipe.git_ref.name

        return args

    def _ensureFilePath(self, file_name, file_path, upload_path):
        # If the evaluated output file name is not within our
        # upload path, then we don't try to copy this or any
        # subsequent files.
        if not os.path.normpath(file_path).startswith(upload_path + "/"):
            raise BuildDaemonError(
                "Build returned a file named '%s'." % file_name
            )

    @defer.inlineCallbacks
    def _fetchIntermediaryFile(self, name, filemap, upload_path):
        file_hash = filemap[name]
        file_path = os.path.join(upload_path, name)
        self._ensureFilePath(name, file_path, upload_path)
        yield self._worker.getFile(file_hash, file_path)

        with open(file_path) as file_fp:
            return json.load(file_fp)

    def _extractLayerFiles(self, upload_path, section, config, digests, files):
        # These are different sets of ids, in the same order
        # layer_id is the filename, diff_id is the internal (docker) id
        for diff_id in config["rootfs"]["diff_ids"]:
            for digests_section in digests:
                layer_id = digests_section[diff_id]["layer_id"]
                # This is in the form '<id>/layer.tar', we only need the first
                layer_filename = "{}.tar.gz".format(layer_id.split("/")[0])
                digest = digests_section[diff_id]["digest"]
                # Check if the file already exists in the librarian
                oci_file = getUtility(IOCIFileSet).getByLayerDigest(digest)
                if oci_file:
                    librarian_file = oci_file.library_file
                    unsecure_file = removeSecurityProxy(oci_file)
                    unsecure_file.date_last_used = datetime.now(timezone.utc)
                # If it doesn't, we need to download it
                else:
                    files.add(layer_filename)
                    continue
                # If the file already exists, retrieve it from the librarian
                # so we can add it to the build artifacts
                layer_path = os.path.join(upload_path, layer_filename)
                librarian_file.open()
                copy_and_close(librarian_file, open(layer_path, "wb"))

    def _convertToRetrievableFile(self, upload_path, file_name, filemap):
        file_path = os.path.join(upload_path, file_name)
        self._ensureFilePath(file_name, file_path, upload_path)
        return (filemap[file_name], file_path)

    @defer.inlineCallbacks
    def _downloadFiles(self, worker_status, upload_path, logger):
        """Download required artifact files."""
        filemap = worker_status["filemap"]

        # We don't want to download all of the files that have been created,
        # just the ones that are mentioned in the manifest and config.
        manifest = yield self._fetchIntermediaryFile(
            "manifest.json", filemap, upload_path
        )
        digests = yield self._fetchIntermediaryFile(
            "digests.json", filemap, upload_path
        )

        files = set()
        for section in manifest:
            config = yield self._fetchIntermediaryFile(
                section["Config"], filemap, upload_path
            )
            self._extractLayerFiles(
                upload_path, section, config, digests, files
            )

        files_to_download = [
            self._convertToRetrievableFile(upload_path, filename, filemap)
            for filename in files
        ]
        yield self._worker.getFiles(files_to_download, logger=logger)

    def verifySuccessfulBuild(self):
        """See `IBuildFarmJobBehaviour`."""
        # The implementation in BuildFarmJobBehaviourBase checks whether the
        # target suite is modifiable in the target archive.  However, an
        # `OCIRecipeBuild` does not use an archive in this manner.
        # We do, however, refuse to build for
        # obsolete series.
        assert self.build.distro_series.status != SeriesStatus.OBSOLETE
