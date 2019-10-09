# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Recipe Name interfaces."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIRecipeName',
    'IOCIRecipeNameSet',
    ]

from zope.interface import Interface
from zope.schema import (
    Int,
    Text,
    )

from lp import _
from lp.app.validators.name import name_validator


class IOCIRecipeName(Interface):
    """A name of an Open Container Initiative recipe.

    This is a tiny table that allows multiple OCIRecipeTarget entities to share
    a single name.
    """
    id = Int(title=_("ID"), required=True, readonly=True)

    name = Text(title=_("Name of recipe"), constraint=name_validator)


class IOCIRecipeNameSet(Interface):
    """A set of `OCIRecipeName`."""

    def __getitem__(name):
        """Retrieve a `OCIRecipeName` by name."""

    def getByName(name):
        """Return a `OCIRecipeName` by its name.

        :raises NoSuchOCIRecipeName: if the `OCIRecipeName` can't be found.
        """

    def new(name):
        """Create a new `OCIRecipeName`."""
