# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The vocabularies relating to sprints."""

__all__ = [
    'FutureSprintVocabulary',
    'SprintVocabulary',
    ]

from lp.blueprints.model.sprint import Sprint
from lp.services.database.constants import UTC_NOW
from lp.services.webapp.vocabulary import NamedStormVocabulary


class FutureSprintVocabulary(NamedStormVocabulary):
    """A vocab of all sprints that have not yet finished."""

    _table = Sprint
    _clauses = [Sprint.time_ends > UTC_NOW]


class SprintVocabulary(NamedStormVocabulary):
    _table = Sprint
