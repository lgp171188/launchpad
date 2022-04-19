# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for CI builds."""

__all__ = [
    "CannotFetchConfiguration",
    "CannotParseConfiguration",
    "CIBuildAlreadyRequested",
    "CIBuildDisallowedArchitecture",
    "ICIBuild",
    "ICIBuildSet",
    "MissingConfiguration",
    ]

import http.client

from lazr.restful.declarations import error_status
from lazr.restful.fields import Reference
from zope.schema import (
    Bool,
    Datetime,
    Dict,
    Int,
    List,
    TextLine,
    )

from lp import _
from lp.buildmaster.interfaces.buildfarmjob import (
    IBuildFarmJobAdmin,
    IBuildFarmJobEdit,
    ISpecificBuildFarmJobSource,
    )
from lp.buildmaster.interfaces.packagebuild import (
    IPackageBuild,
    IPackageBuildView,
    )
from lp.code.interfaces.gitrepository import IGitRepository
from lp.services.database.constants import DEFAULT
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries


class MissingConfiguration(Exception):
    """The repository for this CI build does not have a .launchpad.yaml."""

    def __init__(self, name):
        super().__init__("Cannot find .launchpad.yaml in %s" % name)


class CannotFetchConfiguration(Exception):
    """Launchpad cannot fetch this CI build's .launchpad.yaml."""

    def __init__(self, message, unsupported_remote=False):
        super().__init__(message)
        self.unsupported_remote = unsupported_remote


class CannotParseConfiguration(Exception):
    """Launchpad cannot parse this CI build's .launchpad.yaml."""


@error_status(http.client.BAD_REQUEST)
class CIBuildDisallowedArchitecture(Exception):
    """A build was requested for a disallowed architecture."""

    def __init__(self, das, pocket):
        super().__init__(
            "Builds for %s/%s are not allowed." % (
                das.distroseries.getSuite(pocket), das.architecturetag)
            )


@error_status(http.client.BAD_REQUEST)
class CIBuildAlreadyRequested(Exception):
    """An identical build was requested more than once."""

    def __init__(self):
        super().__init__(
            "An identical build for this commit was already requested.")


class ICIBuildView(IPackageBuildView):
    """`ICIBuild` attributes that require launchpad.View."""

    git_repository = Reference(
        IGitRepository,
        title=_("The Git repository for this CI build."),
        required=False, readonly=True)

    commit_sha1 = TextLine(
        title=_("The Git commit ID for this CI build."),
        required=True, readonly=True)

    distro_arch_series = Reference(
        IDistroArchSeries,
        title=_(
            "The series and architecture that this CI build should run on."),
        required=True, readonly=True)

    arch_tag = TextLine(
        title=_("Architecture tag"), required=True, readonly=True)

    score = Int(
        title=_("Score of the related build farm job (if any)."),
        required=False, readonly=True)

    eta = Datetime(
        title=_("The datetime when the build job is estimated to complete."),
        readonly=True)

    estimate = Bool(
        title=_("If true, the date value is an estimate."), readonly=True)

    date = Datetime(
        title=_(
            "The date when the build completed or is estimated to complete."),
        readonly=True)

    stages = List(
        title=_("A list of stages in this build's configured pipeline."))

    results = Dict(
        title=_(
            "A mapping from job IDs to result tokens, retrieved from the "
            "builder."))

    def getConfiguration(logger=None):
        """Fetch a CI build's .launchpad.yaml from code hosting, if possible.

        :param logger: An optional logger.

        :return: The build's parsed .launchpad.yaml.
        :raises MissingConfiguration: if this package has no
            .launchpad.yaml.
        :raises CannotFetchConfiguration: if it was not possible to fetch
            .launchpad.yaml from the code hosting backend for some other
            reason.
        :raises CannotParseConfiguration: if the fetched .launchpad.yaml
            cannot be parsed.
        """

    def getOrCreateRevisionStatusReport(job_id):
        """Get the `IRevisionStatusReport` for a given job in this build.

        Create the report if necessary.

        :param job_id: A job ID, in the form "JOB_NAME:JOB_INDEX".
        :return: An `IRevisionStatusReport`.
        """

    def getFileByName(filename):
        """Return the corresponding `ILibraryFileAlias` in this context.

        The following file types (and extension) can be looked up:

         * Build log: '.txt.gz'
         * Upload log: '_log.txt'

        :param filename: The filename to look up.
        :raises NotFoundError: if no file exists with the given name.
        :return: The corresponding `ILibraryFileAlias`.
        """


class ICIBuildEdit(IBuildFarmJobEdit):
    """`ICIBuild` methods that require launchpad.Edit."""


class ICIBuildAdmin(IBuildFarmJobAdmin):
    """`ICIBuild` methods that require launchpad.Admin."""


class ICIBuild(ICIBuildView, ICIBuildEdit, ICIBuildAdmin, IPackageBuild):
    """A build record for a pipeline of CI jobs."""


class ICIBuildSet(ISpecificBuildFarmJobSource):
    """Utility to create and access `ICIBuild`s."""

    def new(git_repository, commit_sha1, distro_arch_series, stages,
            date_created=DEFAULT):
        """Create an `ICIBuild`."""

    def findByGitRepository(git_repository, commit_sha1s=None):
        """Return all CI builds for the given Git repository.

        :param git_repository: An `IGitRepository`.
        :param commit_sha1s: If not None, only return CI builds for one of
            these Git commit IDs.
        """

    def requestBuild(git_repository, commit_sha1, distro_arch_series, stages):
        """Request a CI build.

        This checks that the architecture is allowed and that there isn't
        already a matching pending build.

        :param git_repository: The `IGitRepository` for the new build.
        :param commit_sha1: The Git commit ID for the new build.
        :param distro_arch_series: The `IDistroArchSeries` that the new
            build should run on.
        :param stages: A list of stages in this build's pipeline according
            to its `.launchpad.yaml`, each of which is a list of (job_name,
            job_index) tuples.
        :raises CIBuildDisallowedArchitecture: if builds on
            `distro_arch_series` are not allowed.
        :raises CIBuildAlreadyRequested: if a matching build was already
            requested.
        :return: `ICIBuild`.
        """

    def requestBuildsForRefs(git_repository, ref_paths, logger=None):
        """Request CI builds for a collection of refs.

        This fetches `.launchpad.yaml` from the repository and parses it to
        work out which series/architectures need builds.

        :param git_repository: The `IGitRepository` for which to request
            builds.
        :param ref_paths: A collection of Git reference paths within
            `git_repository`; builds will be requested for the commits that
            each of them points to.
        :param logger: An optional logger.
        """

    def deleteByGitRepository(git_repository):
        """Delete all CI builds for the given Git repository.

        :param git_repository: An `IGitRepository`.
        """
