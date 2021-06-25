# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe build interfaces."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    "ICharmFile",
    "ICharmRecipeBuild",
    "ICharmRecipeBuildSet",
    ]

from lazr.restful.fields import Reference
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import (
    Bool,
    Datetime,
    Dict,
    Int,
    TextLine,
    )

from lp import _
from lp.buildmaster.interfaces.buildfarmjob import ISpecificBuildFarmJobSource
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.charms.interfaces.charmrecipe import (
    ICharmRecipe,
    ICharmRecipeBuildRequest,
    )
from lp.registry.interfaces.person import IPerson
from lp.services.database.constants import DEFAULT
from lp.services.librarian.interfaces import ILibraryFileAlias
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries


class ICharmRecipeBuildView(IPackageBuild):
    """`ICharmRecipeBuild` attributes that require launchpad.View."""

    build_request = Reference(
        ICharmRecipeBuildRequest,
        title=_("The build request that caused this build to be created."),
        required=True, readonly=True)

    requester = Reference(
        IPerson,
        title=_("The person who requested this build."),
        required=True, readonly=True)

    recipe = Reference(
        ICharmRecipe,
        title=_("The charm recipe to build."),
        required=True, readonly=True)

    distro_arch_series = Reference(
        IDistroArchSeries,
        title=_("The series and architecture for which to build."),
        required=True, readonly=True)

    channels = Dict(
        title=_("Source snap channels to use for this build."),
        description=_(
            "A dictionary mapping snap names to channels to use for this "
            "build.  Currently only 'core', 'core18', 'core20', "
            "and 'charmcraft' keys are supported."),
        key_type=TextLine())

    virtualized = Bool(
        title=_("If True, this build is virtualized."), readonly=True)

    score = Int(
        title=_("Score of the related build farm job (if any)."),
        required=False, readonly=True)

    can_be_rescored = Bool(
        title=_("Can be rescored"),
        required=True, readonly=True,
        description=_("Whether this build record can be rescored manually."))

    can_be_retried = Bool(
        title=_("Can be retried"),
        required=False, readonly=True,
        description=_("Whether this build record can be retried."))

    can_be_cancelled = Bool(
        title=_("Can be cancelled"),
        required=True, readonly=True,
        description=_("Whether this build record can be cancelled."))

    eta = Datetime(
        title=_("The datetime when the build job is estimated to complete."),
        readonly=True)

    estimate = Bool(
        title=_("If true, the date value is an estimate."), readonly=True)

    date = Datetime(
        title=_(
            "The date when the build completed or is estimated to complete."),
        readonly=True)

    revision_id = TextLine(
        title=_("Revision ID"), required=False, readonly=True,
        description=_(
            "The revision ID of the branch used for this build, if "
            "available."))

    store_upload_metadata = Attribute(
        _("A dict of data about store upload progress."))

    def getFiles():
        """Retrieve the build's `ICharmFile` records.

        :return: A result set of (`ICharmFile`, `ILibraryFileAlias`,
            `ILibraryFileContent`).
        """

    def getFileByName(filename):
        """Return the corresponding `ILibraryFileAlias` in this context.

        The following file types (and extension) can be looked up:

         * Build log: '.txt.gz'
         * Upload log: '_log.txt'

        Any filename not matching one of these extensions is looked up as a
        charm recipe output file.

        :param filename: The filename to look up.
        :raises NotFoundError: if no file exists with the given name.
        :return: The corresponding `ILibraryFileAlias`.
        """


class ICharmRecipeBuildEdit(Interface):
    """`ICharmRecipeBuild` methods that require launchpad.Edit."""

    def addFile(lfa):
        """Add a file to this build.

        :param lfa: An `ILibraryFileAlias`.
        :return: An `ICharmFile`.
        """

    def retry():
        """Restore the build record to its initial state.

        Build record loses its history, is moved to NEEDSBUILD and a new
        non-scored BuildQueue entry is created for it.
        """

    def cancel():
        """Cancel the build if it is either pending or in progress.

        Check the can_be_cancelled property prior to calling this method to
        find out if cancelling the build is possible.

        If the build is in progress, it is marked as CANCELLING until the
        buildd manager terminates the build and marks it CANCELLED.  If the
        build is not in progress, it is marked CANCELLED immediately and is
        removed from the build queue.

        If the build is not in a cancellable state, this method is a no-op.
        """


class ICharmRecipeBuildAdmin(Interface):
    """`ICharmRecipeBuild` methods that require launchpad.Admin."""

    def rescore(score):
        """Change the build's score."""


class ICharmRecipeBuild(
        ICharmRecipeBuildView, ICharmRecipeBuildEdit, ICharmRecipeBuildAdmin):
    """A build record for a charm recipe."""


class ICharmRecipeBuildSet(ISpecificBuildFarmJobSource):
    """Utility to create and access `ICharmRecipeBuild`s."""

    def new(build_request, recipe, distro_arch_series, channels=None,
            store_upload_metadata=None, date_created=DEFAULT):
        """Create an `ICharmRecipeBuild`."""

    def preloadBuildsData(builds):
        """Load the data related to a list of charm recipe builds."""


class ICharmFile(Interface):
    """A file produced by a charm recipe build."""

    build = Reference(
        ICharmRecipeBuild,
        title=_("The charm recipe build producing this file."),
        required=True, readonly=True)

    library_file = Reference(
        ILibraryFileAlias, title=_("the library file alias for this file."),
        required=True, readonly=True)
