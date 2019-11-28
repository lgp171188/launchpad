# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A recipe for building Open Container Initiative images."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeChannel',
    ]


from storm.locals import (
    Int,
    Reference,
    Storm,
    Unicode,
    )
from zope.interface import implementer

from lp.oci.interfaces.ocirecipechannel import IOCIRecipeChannel


@implementer(IOCIRecipeChannel)
class OCIRecipeChannel(Storm):

    __storm_table__ = "OCIRecipeChannel"
    __storm_primary__ = ("recipe_id", "name")

    recipe_id = Int(name="recipe", allow_none=False)
    recipe = Reference(recipe_id, "OCIRecipe.id")

    name = Unicode(name="name", allow_none=False)
    git_path = Unicode(name="git_path", allow_none=False)
    build_file = Unicode(name="build_file", allow_none=False)

    def __init__(self, recipe, name, git_path, build_file):
        self.recipe = recipe
        self.name = name
        self.git_path = git_path
        self.build_file = build_file
