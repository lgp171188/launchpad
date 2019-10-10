# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Recipe Target interfaces."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIRecipeTarget',
    'IOCIRecipeTargetSet',
    ]

from lazr.restful.declarations import (
    export_as_webservice_entry,
    exported,
    )
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import (
    Bool,
    Datetime,
    Int,
    Text,
    )

from lp import _
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.ocirecipename import IOCIRecipeName
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.role import IHasOwner


class IOCIRecipeTargetView(Interface):
    """IOCIRecipeTarget attributes that require launchpad.View permision."""

    id = Int(title=_("OCI Recipe Target ID"),
             required=True,
             readonly=True
             )
    date_created = Datetime(title=_("Date created"), required=True)
    date_last_modified = Datetime(title=_("Date last modified"), required=True)

    registrant = exported(Reference(
        IPerson,
        title=_("The person that registered this recipe."),
        required=True))


class IOCIRecipeTargetEditableAttributes(IHasOwner):
    """IOCIRecipeTarget attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    project = exported(Reference(
        IProduct,
        title=_("The project that this recipe is for.")))
    distribution = exported(Reference(
        IDistribution,
        title=_("The distribution that this recipe is associated with.")))
    ocirecipename = exported(Reference(
        IOCIRecipeName,
        title=_("The name of this recipe."),
        required=True))
    description = exported(Text(title=_("The description for this recipe.")))
    bug_supervisor = exported(Reference(
        IPerson,
        title=_("The supervisor for bug reports on this recipe.")))
    bug_reporting_guidelines = exported(Text(
        title=_("Guidelines for reporting bugs with this recipe")))
    bug_reported_acknowledgement = exported(Text(
        title=_("Text displayed on a bug being successfully filed")))
    enable_bugfiling_duplicate_search = exported(Bool(
        title=_("Enable duplicate search on filing a bug on this recipe."),
        required=True,
        default=True))


class IOCIRecipeTarget(IOCIRecipeTargetView,
                       IOCIRecipeTargetEditableAttributes):
    """A target of project or distribution for an OCIRecipe."""

    export_as_webservice_entry()


class IOCIRecipeTargetSet(Interface):
    """A utility of this interface that can be used to create and access
       recipe targets.
    """

    def new(registrant, project, distribution, ocirecipename,
            date_created=None, description=None, bug_supervisor=None,
            bug_reporting_guidelines=None, bug_reported_acknowledgement=None,
            bugfiling_duplicate_search=False):
        """Create an `IOCIRecipeTarget`."""

    def getByProject(project):
        """Get the OCIRecipeTargets for a given project."""

    def getByDistribution(distribution):
        """Get the OCIRecipeTargets for a given distribution."""
