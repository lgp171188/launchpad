# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIRecipeName',
    'IOCIRecipeNameSet',
    ]

from zope.interface import (
    Interface
)
from zope.schema import (
    Int,
    Text,
    )

from lp import _


class IOCIRecipeName(Interface):
    """Interface provided by an OCIRecipeName.

    This is a tiny table that allows multiple OCIRecipeTarget entities to share
    a single name.
    """
    id = Int(title=_("OCI Recipe Name ID"),
             required=True,
             readonly=True
             )

    name = Text(title=_("Name of recipe"))


class IOCIRecipeNameSet(Interface):
    """A set of OCIRecipeName."""

    def __getitem__(name):
        """Retrieve a ocirecipename by name."""

    def getByName(name):
        """Return a ocirecipename by its name.

        If the ocirecipename can't be found a NoSuchOCIRecipeName will be
        raised.
        """

    def getAll():
        """return an iselectresults representing all package names"""

    def new(name):
        """Create a new oci recipe name."""
