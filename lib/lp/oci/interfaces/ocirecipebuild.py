# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for a build record for OCI recipes."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIFile',
    'IOCIRecipeBuild',
    'IOCIRecipeBuildSet',
    ]

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import TextLine

from lp import _
from lp.buildmaster.interfaces.buildfarmjob import ISpecificBuildFarmJobSource
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.oci.interfaces.ocirecipe import IOCIRecipe
from lp.services.database.constants import DEFAULT
from lp.services.fields import PublicPersonChoice
from lp.services.librarian.interfaces import ILibraryFileAlias


class IOCIRecipeBuildEdit(Interface):
    # XXX twom 2020-02-10 This will probably need cancel() implementing
    pass


class IOCIRecipeBuildView(IPackageBuild):

    requester = PublicPersonChoice(
        title=_("Requester"),
        description=_("The person who requested this OCI recipe build."),
        vocabulary='ValidPersonOrTeam', required=True, readonly=True)

    recipe = Reference(
        IOCIRecipe,
        title=_("The OCI recipe to build."),
        required=True,
        readonly=True)


class IOCIRecipeBuildAdmin(Interface):
    # XXX twom 2020-02-10 This will probably need rescore() implementing
    pass


class IOCIRecipeBuild(IOCIRecipeBuildAdmin, IOCIRecipeBuildEdit,
                      IOCIRecipeBuildView):
    """A build record for an OCI recipe."""


class IOCIRecipeBuildSet(ISpecificBuildFarmJobSource):
    """A utility to create and access OCIRecipeBuilds."""

    def new(requester, recipe, distro_arch_series,
            date_created=DEFAULT):
        """Create an `IOCIRecipeBuild`."""

    def preloadBuildsData(builds):
        """Load the data related to a list of OCI recipe builds."""


class IOCIFile(Interface):
    """A link between an OCI recipe build and a file in the librarian."""

    build = Reference(
        # Really IOCIBuild, patched in _schema_circular_imports.py.
        Interface,
        title=_("The OCI recipe build producing this file."),
        required=True, readonly=True)

    libraryfile = Reference(
        ILibraryFileAlias, title=_("A file in the librarian."),
        required=True, readonly=True)

    digest = TextLine(
        title=_("Content-addressable hash of the file''s contents, "
                "used for image layers."),
        required=False, readonly=True)
