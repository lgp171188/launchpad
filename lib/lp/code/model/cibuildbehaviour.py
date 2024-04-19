# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""An `IBuildFarmJobBehaviour` for `CIBuild`."""

__all__ = [
    "CIBuildBehaviour",
]

import json
from configparser import NoSectionError
from copy import deepcopy
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
from lp.code.enums import RevisionStatusResult
from lp.code.interfaces.cibuild import ICIBuild
from lp.code.interfaces.codehosting import LAUNCHPAD_SERVICES
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.services.config import config
from lp.services.twistedsupport import cancel_on_timeout
from lp.soyuz.adapters.archivedependencies import get_sources_list_for_building


def replace_auth_placeholder(s: str) -> str:
    return s % {"read_auth": config.artifactory.read_credentials}


def build_environment_variables(distribution_name: str) -> dict:
    # - load key/value pairs from JSON Object
    # - replace authentication placeholder
    try:
        pairs = config["cibuild." + distribution_name]["environment_variables"]
    except NoSectionError:
        return {}
    if pairs is None:
        return {}
    rv = {}
    for key, value in json.loads(pairs).items():
        rv[key] = replace_auth_placeholder(value)
    return rv


def build_package_repositories(distribution_name: str) -> list:
    # - load package repository configuration lines from JSON Array
    # - replace authentication placeholder
    try:
        lines = config["cibuild." + distribution_name]["package_repositories"]
    except NoSectionError:
        return []
    if lines is None:
        return []
    rv = []
    for line in json.loads(lines):
        rv.append(replace_auth_placeholder(line))
    return rv


def build_plugin_settings(distribution_name: str) -> dict:
    # - load key/value pairs from JSON Object
    # - replace authentication placeholder
    try:
        pairs = config["cibuild." + distribution_name]["plugin_settings"]
    except NoSectionError:
        return {}
    if pairs is None:
        return {}
    rv = {}
    for key, value in json.loads(pairs).items():
        rv[key] = replace_auth_placeholder(value)
    return rv


def build_secrets(distribution_name: str) -> dict:
    # For now: load and return the distribution specific secrets
    # In future this could also load secrets from repository settings.
    try:
        pairs = config["cibuild." + distribution_name]["secrets"]
    except NoSectionError:
        return {}
    if pairs is None:
        return {}
    rv = {}
    for key, value in json.loads(pairs).items():
        rv[key] = replace_auth_placeholder(value)
    return rv


def should_scan_malware(distribution_name: str) -> bool:
    try:
        return config["cibuild." + distribution_name]["scan_malware"]
    except NoSectionError:
        return False


@adapter(ICIBuild)
@implementer(IBuildFarmJobBehaviour)
class CIBuildBehaviour(BuilderProxyMixin, BuildFarmJobBehaviourBase):
    """Dispatches `CIBuild` jobs to builders."""

    builder_type = "ci"
    image_types = [BuildBaseImageType.LXD, BuildBaseImageType.CHROOT]

    ALLOWED_STATUS_NOTIFICATIONS = ["PACKAGEFAIL"]

    def redactXmlrpcArguments(self, args):
        # we do not want to have secrets in logs

        # we need to copy the input in order to avoid mutating `args` which
        # will be passed to the builders
        args = deepcopy(args)
        if args["args"].get("secrets"):
            for key in args["args"]["secrets"].keys():
                args["args"]["secrets"][key] = "<redacted>"
        return super().redactXmlrpcArguments(args)

    def getLogFileName(self):
        return "buildlog_ci_%s_%s_%s.txt" % (
            self.build.git_repository.name,
            self.build.commit_sha1,
            self.build.status.name,
        )

    def verifyBuildRequest(self, logger):
        """Assert some pre-build checks.

        The build request is checked:
         * Virtualized builds can't build on a non-virtual builder
         * We have a base image
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
                "issueMacaroon", "ci-build", "CIBuild", self.build.id
            ),
            config.builddmaster.authentication_timeout,
        )

    @defer.inlineCallbacks
    def extraBuildArgs(self, logger=None) -> Generator[Any, Any, BuildArgs]:
        """Return extra builder arguments for this build."""
        build = self.build
        if not build.stages:
            raise CannotBuild(
                "No stages defined for %s:%s"
                % (build.git_repository.unique_name, build.commit_sha1)
            )

        args: BuildArgs = yield super().extraBuildArgs(logger=logger)
        yield self.startProxySession(args)
        (
            args["archives"],
            args["trusted_keys"],
        ) = yield get_sources_list_for_building(
            self, build.distro_arch_series, None, logger=logger
        )
        args["jobs"] = removeSecurityProxy(build.stages)
        if build.git_repository.private:
            macaroon_raw = yield self.issueMacaroon()
            url = build.git_repository.getCodebrowseUrl(
                username=LAUNCHPAD_SERVICES, password=macaroon_raw
            )
            args["git_repository"] = url
        else:
            args["git_repository"] = build.git_repository.git_https_url
        args["git_path"] = build.commit_sha1
        args["private"] = build.is_private
        if IDistributionSourcePackage.providedBy(build.git_repository.target):
            distribution_name = build.git_repository.target.distribution.name
            args["environment_variables"] = build_environment_variables(
                distribution_name
            )
            args["package_repositories"] = build_package_repositories(
                distribution_name
            )
            args["plugin_settings"] = build_plugin_settings(distribution_name)
            args["secrets"] = build_secrets(distribution_name)
            args["scan_malware"] = should_scan_malware(distribution_name)
        return args

    def verifySuccessfulBuild(self):
        """See `IBuildFarmJobBehaviour`."""
        # We have no interesting checks to perform here.

    @defer.inlineCallbacks
    def storeLogFromWorker(self, worker_status):
        if "jobs" in worker_status:
            # Save the "jobs" field so that the uploader can reliably map
            # files to individual CI jobs.
            removeSecurityProxy(self.build).results = worker_status["jobs"]
            # Update status reports for each individual job.
            for job_id, job_status in worker_status["jobs"].items():
                report = self.build.getOrCreateRevisionStatusReport(job_id)
                report.transitionToNewResult(
                    RevisionStatusResult.items[job_status["result"]]
                )
        yield super().storeLogFromWorker(worker_status)
