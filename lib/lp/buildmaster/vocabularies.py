# Copyright 2009-2015 Canonical Ltd.  This software is licensed under the GNU
# Affero General Public License version 3 (see the file LICENSE).

"""Soyuz vocabularies."""

__all__ = [
    "BuilderResourceVocabulary",
    "ProcessorVocabulary",
]

from storm.expr import Alias, Cast, Coalesce, Func
from zope.interface import implementer
from zope.schema.interfaces import IVocabularyTokenized
from zope.schema.vocabulary import SimpleTerm

from lp.buildmaster.model.builder import Builder
from lp.buildmaster.model.processor import Processor
from lp.services.database.interfaces import IStore
from lp.services.database.stormexpr import Concatenate
from lp.services.propertycache import cachedproperty
from lp.services.webapp.vocabulary import NamedStormVocabulary


class ProcessorVocabulary(NamedStormVocabulary):
    displayname = "Select a processor"
    _table = Processor
    _order_by = "name"


@implementer(IVocabularyTokenized)
class BuilderResourceVocabulary:
    """A vocabulary of all currently-defined builder resources.

    The context is anything with a `builder_constraints` attribute; the
    current constraints are merged into the set of available builder
    resources, to avoid problems if some unknown resources are already set
    as constraints.
    """

    def __init__(self, context):
        self.context = context

    @cachedproperty
    def _resources(self):
        builder_resources = set(
            IStore(Builder)
            .find(
                Alias(
                    Func(
                        "jsonb_array_elements_text",
                        Concatenate(
                            Coalesce(
                                Builder.open_resources, Cast("[]", "jsonb")
                            ),
                            Coalesce(
                                Builder.restricted_resources,
                                Cast("[]", "jsonb"),
                            ),
                        ),
                    ),
                    "resource",
                ),
                Builder.active,
            )
            .config(distinct=True)
        )
        return sorted(
            builder_resources.union(self.context.builder_constraints or set())
        )

    def __contains__(self, value):
        """See `zope.schema.interfaces.ISource`."""
        return value in self._resources

    def __iter__(self):
        """See `zope.schema.interfaces.IIterableVocabulary`."""
        for resource in self._resources:
            yield SimpleTerm(resource)

    def __len__(self):
        """See `zope.schema.interfaces.IIterableVocabulary`."""
        return len(self._resources)

    def getTerm(self, value):
        """See `zope.schema.interfaces.IBaseVocabulary`."""
        if value in self._resources:
            return SimpleTerm(value)
        else:
            raise LookupError(value)

    def getTermByToken(self, token):
        """See `zope.schema.interfaces.IVocabularyTokenized`."""
        if token in self._resources:
            return SimpleTerm(token)
        else:
            raise LookupError(token)
