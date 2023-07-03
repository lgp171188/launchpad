# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI vocabularies."""

__all__ = []

from urllib.parse import quote, unquote

from zope.component import getUtility
from zope.interface import implementer
from zope.schema.vocabulary import SimpleTerm

from lp.oci.interfaces.ociregistrycredentials import IOCIRegistryCredentialsSet
from lp.oci.model.ocirecipe import OCIRecipe
from lp.oci.model.ociregistrycredentials import OCIRegistryCredentials
from lp.services.webapp.vocabulary import IHugeVocabulary, StormVocabularyBase
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


class OCIRegistryCredentialsVocabulary(StormVocabularyBase):
    _table = OCIRegistryCredentials

    def toTerm(self, obj):
        if obj.username:
            token = "%s %s" % (quote(obj.url), quote(obj.username))
            title = "%s (%s)" % (obj.url, obj.username)
        else:
            token = quote(obj.url)
            title = obj.url

        return SimpleTerm(obj, token, title)

    @property
    def _entries(self):
        return list(
            getUtility(IOCIRegistryCredentialsSet).findByOwner(
                self.context.owner
            )
        )

    def __contains__(self, value):
        """See `IVocabulary`."""
        return value in self._entries

    def __len__(self):
        return len(self._entries)

    def getTermByToken(self, token):
        """See `IVocabularyTokenized`."""
        try:
            if " " in token:
                url, username = token.split(" ", 1)
                url = unquote(url)
                username = unquote(username)
            else:
                username = None
                url = unquote(token)
            for obj in self._entries:
                if obj.url == url and obj.username == username:
                    return self.toTerm(obj)
        except ValueError:
            raise LookupError(token)


@implementer(IHugeVocabulary)
class OCIRecipeVocabulary(StormVocabularyBase):
    """All OCI Recipes of a given OCI project."""

    _table = OCIRecipe
    displayname = "Select a recipe"
    step_title = "Search"

    def toTerm(self, recipe):
        token = "%s/%s" % (recipe.owner.name, recipe.name)
        title = "~%s" % token
        return SimpleTerm(recipe, token, title)

    def getTermByToken(self, token):
        owner_name, recipe_name = token.split("/")
        recipe = self.context.getRecipeByNameAndOwner(recipe_name, owner_name)
        if recipe is None:
            raise LookupError(token)
        return self.toTerm(recipe)

    def search(self, query, vocab_filter=None):
        return self.context.searchRecipes(query)

    @property
    def _entries(self):
        return self.context.getRecipes()
