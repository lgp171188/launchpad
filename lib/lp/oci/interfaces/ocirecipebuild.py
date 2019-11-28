# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for a build record for OCI recipes."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIRecipeBuild',
    'IOCIRecipeBuildSet'
    ]

from lazr.restful.fields import Reference
from zope.interface import Interface

from lp import _
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.oci.interfaces.ocirecipe import IOCIRecipe
from lp.services.database.constants import DEFAULT
from lp.services.fields import PublicPersonChoice


class IOCIRecipeBuildEdit(Interface):
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
    pass


class IOCIRecipeBuild(IOCIRecipeBuildAdmin, IOCIRecipeBuildEdit,
                      IOCIRecipeBuildView):
    """A build record for an OCI recipe."""


class IOCIRecipeBuildSet(Interface):
    """A utility to create and access OCIRecipeBuilds."""

    def new(requester, recipe, channel_name, processor, virtualized,
            date_created=DEFAULT):
        """Create an `IOCIRecipeBuild`."""
