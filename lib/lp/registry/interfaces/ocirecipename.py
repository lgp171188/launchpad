from zope.interface import (
    Interface
)
from zope.schema import (
    Int,
    Text,
    )

from lp import _


class IOCIRecipeName(Interface):

    id = Int(title=_("OCI Recipe Name ID"),
             required=True,
             readonly=True
             )

    name = Text(title=_("Name of recipe"))
