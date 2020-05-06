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
    """All OCI Recipes of a given OCI Project."""

    _table = OCIRecipe

    def toTerm(self, recipe):
        title = "~%s/%s" % (recipe.owner.name, recipe.name)
        return SimpleTerm(recipe, title, title)

    def getTermByToken(self, token):
        # Remove the starting tilde, and split owner and recipe name.
        owner_name, recipe_name = token[1:].split('/')
        recipe = self.context.searchRecipes(recipe_name, owner_name).one()
        if recipe is None:
            raise LookupError(token)
        return self.toTerm(recipe)

    def search(self, query, vocab_filter=None):
        return self.context.searchRecipes(query)

    def __iter__(self):
        for obj in self.context.getRecipes():
            yield self.toTerm(obj)

    def __len__(self):
        return self.context.getRecipes().count()
