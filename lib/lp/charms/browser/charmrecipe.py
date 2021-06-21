# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    "CharmRecipeURL",
    ]

from zope.component import getUtility
from zope.interface import implementer

from lp.registry.interfaces.personproduct import IPersonProductFactory
from lp.services.webapp.interfaces import ICanonicalUrlData


@implementer(ICanonicalUrlData)
class CharmRecipeURL:
    """Charm recipe URL creation rules."""
    rootsite = 'mainsite'

    def __init__(self, recipe):
        self.recipe = recipe

    @property
    def inside(self):
        owner = self.recipe.owner
        project = self.recipe.project
        return getUtility(IPersonProductFactory).create(owner, project)

    @property
    def path(self):
        return "+charm/%s" % self.recipe.name
