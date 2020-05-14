# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI vocabularies."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = []

from zope.interface import implementer
from zope.schema.vocabulary import SimpleTerm

from lp.oci.model.ocirecipe import OCIRecipe
from lp.services.webapp.vocabulary import (
    IHugeVocabulary,
    StormVocabularyBase,
    )
from lp.soyuz.model.distroarchseries import DistroArchSeries


class OCIRecipeDistroArchSeriesVocabulary(StormVocabularyBase):
    """All architectures of an OCI recipe's distribution series."""

    _table = DistroArchSeries

    def toTerm(self, das):
        return SimpleTerm(das, das.id, das.architecturetag)

    def __iter__(self):
        for obj in self.context.getAllowedArchitectures():
            yield self.toTerm(obj)

    def __len__(self):
        return len(self.context.getAllowedArchitectures())


@implementer(IHugeVocabulary)
class OCIRecipeVocabulary(StormVocabularyBase):
    """All OCI Recipes of a given OCI project."""

    _table = OCIRecipe
    displayname = 'Select a recipe'
    step_title = 'Search'

    def toTerm(self, recipe):
        token = "%s/%s" % (recipe.owner.name, recipe.name)
        title = "~%s" % token
        return SimpleTerm(recipe, token, title)

    def getTermByToken(self, token):
        owner_name, recipe_name = token.split('/')
        recipe = self.context.getRecipeByNameAndOwner(recipe_name, owner_name)
        if recipe is None:
            raise LookupError(token)
        return self.toTerm(recipe)

    def search(self, query, vocab_filter=None):
        return self.context.searchRecipes(query)

    def _entries(self):
        return self.context.getRecipes()
