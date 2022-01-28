# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for CI builds."""

__all__ = [
    "CannotFetchConfiguration",
    "CannotParseConfiguration",
    "ICIBuild",
    "ICIBuildSet",
    "MissingConfiguration",
    ]

from lazr.restful.fields import Reference
from zope.schema import (
    Bool,
    Datetime,
    Int,
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


class ICIBuildEdit(IBuildFarmJobEdit):
    """`ICIBuild` methods that require launchpad.Edit."""


class ICIBuildAdmin(IBuildFarmJobAdmin):
    """`ICIBuild` methods that require launchpad.Admin."""


class ICIBuild(ICIBuildView, ICIBuildEdit, ICIBuildAdmin, IPackageBuild):
    """A build record for a pipeline of CI jobs."""


class ICIBuildSet(ISpecificBuildFarmJobSource):
    """Utility to create and access `ICIBuild`s."""

    def new(git_repository, commit_sha1, distro_arch_series,
            date_created=DEFAULT):
        """Create an `ICIBuild`."""

    def findByGitRepository(git_repository, commit_sha1s=None):
        """Return all CI builds for the given Git repository.

        :param git_repository: An `IGitRepository`.
        :param commit_sha1s: If not None, only return CI builds for one of
            these Git commit IDs.
        """

    def deleteByGitRepository(git_repository):
        """Delete all CI builds for the given Git repository.

        :param git_repository: An `IGitRepository`.
        """
