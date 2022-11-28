# Copyright 2009-2015 Canonical Ltd.  This software is licensed under the GNU
# Affero General Public License version 3 (see the file LICENSE).

"""Soyuz vocabularies."""

__all__ = [
    "builder_resource_vocabulary_factory",
    "ProcessorVocabulary",
]

from storm.expr import Alias, Cast, Coalesce, Func
from zope.schema.vocabulary import SimpleTerm, SimpleVocabulary

from lp.buildmaster.model.builder import Builder
from lp.buildmaster.model.processor import Processor
from lp.services.database.interfaces import IStore
from lp.services.database.stormexpr import Concatenate
from lp.services.webapp.vocabulary import NamedSQLObjectVocabulary


class ProcessorVocabulary(NamedSQLObjectVocabulary):

    displayname = "Select a processor"
    _table = Processor
    _orderBy = "name"


def builder_resource_vocabulary_factory(context):
    """Return a vocabulary of all currently-defined builder resources.

    The context is anything with a `builder_constraints` attribute; the
    current constraints are merged into the set of available builder
    resources, to avoid problems if some unknown resources are already set
    as constraints.
    """
    resources = set(
        IStore(Builder)
        .find(
            Alias(
                Func(
                    "jsonb_array_elements_text",
                    Concatenate(
                        Coalesce(Builder.open_resources, Cast("[]", "jsonb")),
                        Coalesce(
                            Builder.restricted_resources, Cast("[]", "jsonb")
                        ),
                    ),
                ),
                "resource",
            ),
            Builder.active,
        )
        .config(distinct=True)
    ).union(context.builder_constraints or set())
    return SimpleVocabulary(
        [SimpleTerm(resource) for resource in sorted(resources)]
    )
