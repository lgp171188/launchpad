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


class IOCIRecipeTarget(Interface):

    id = Int(title=_("OCI Recipe Target ID"),
             required=True,
             readonly=True
             )
    date_created = Datetime(title=_("Date created"), required=True)
    date_last_modified = Datetime(title=_("Date last modified"), required=True)
    registrant = Reference(
        IPerson,
        title=_("The person that registered this recipe."),
        required=True
        )
    project = Reference(
        IProduct,
        title=_("The project that this recipe is for."),
        )
    distribution = Reference(
        IDistribution,
        title=_("The distribution that this recipe is associated with.")
        )
    ocirecipename = Reference(
        IOCIRecipeName,
        title=_("The name of this recipe."),
        required=True
        )
    description = Text(title=_("The description for this recipe."))
    bug_supervisor = Reference(
        IPerson,
        title=_("The supervisor for bug reports on this recipe.")
        )
    bug_reporting_guidelines = Text(
        title=_("Guidelines for reporting bugs with this recipe"))
    bug_reported_acknowledgement = Text(
        title=_("Text displayed on a bug being successfully filed"))
    enable_bugfiling_duplicate_search = Bool(
        title=_("Enable duplicate search on filing a bug on this recipe."),
        required=True,
        default=True
        )
