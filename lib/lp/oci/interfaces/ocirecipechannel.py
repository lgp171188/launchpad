# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for defining channel attributes for an OCI Recipe."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIRecipeChannel',
    ]

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import TextLine

from lp import _
from lp.app.validators.name import name_validator
from lp.app.validators.path import path_within_repo
from lp.oci.interfaces.ocirecipe import IOCIRecipe


class IOCIRecipeChannel(Interface):
    """The channels that exist for an OCI recipe."""

    recipe = Reference(
        IOCIRecipe,
        title=_("The OCI recipe for which a channel is specified."),
        required=True,
        readonly=True)

    name = TextLine(
        title=_("The name of this channel."),
        constraint=name_validator,
        required=True)

    git_path = TextLine(
        title=_("The branch within this recipe's Git "
                "repository where its build files are maintained."),
        required=True)

    build_file = TextLine(
        title=_("The relative path to the file within this recipe's "
                "branch that defines how to build the recipe."),
        constraint=path_within_repo,
        required=True)
