# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helpers for doing natural language phrase search using the
full text index.
"""

__all__ = ["nl_phrase_search"]

import re

import six
from storm.databases.postgres import Case
from storm.locals import SQL, Count, Select
from zope.component import getUtility

from lp.services.database.interfaces import (
    DEFAULT_FLAVOR,
    MAIN_STORE,
    IStore,
    IStoreSelector,
)
from lp.services.database.stormexpr import fti_search

# Regular expression to extract terms from the printout of a ts_query
TS_QUERY_TERM_RE = re.compile(r"'([^']+)'")


def nl_term_candidates(phrase):
    """Returns in an array the candidate search terms from phrase.
    Stop words are removed from the phrase and every term is normalized
    according to the full text rules (lowercased and stemmed).

    :phrase: a search phrase
    """
    phrase = six.ensure_text(phrase)
    store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
    rs = store.execute(Select(SQL("ftq(?)::text", params=(phrase,)))).get_all()
    assert len(rs) == 1, "ftq() returned more than one row"
    terms = rs[0][0]
    if not terms:
        # Only stop words
        return []
    return TS_QUERY_TERM_RE.findall(terms)


def nl_phrase_search(
    phrase, table, constraint_clauses=None, fast_enabled=True
):
    """Return the tsearch2 query that should be used to do a phrase search.

    The precise heuristics applied by this function will vary as we tune
    the system.

    It is the interface by which a user query should be turned into a backend
    search language query.

    Caveats: The model class must define a 'fti' column which is then used used
    for full text searching.

    :param phrase: A search phrase.
    :param table: This should be the Storm class representing the base type.
    :param constraint_clauses: Additional Storm clauses that limit the rows
        to a subset of the table.
    :param fast_enabled: If true use a fast, but less precise, code path. When
        feature flags are available this will be converted to a feature flag.
    :return: A tsearch2 query string.
    """
    terms = nl_term_candidates(phrase)
    if len(terms) == 0:
        return ""
    if fast_enabled:
        return _nl_phrase_search(terms, table, constraint_clauses)
    else:
        return _slow_nl_phrase_search(terms, table, constraint_clauses)


def _nl_phrase_search(terms, table, constraint_clauses):
    """Perform a very simple pruning of the phrase, letting fti do ranking.

    This function groups the terms with & clause, and creates an additional
    & grouping for each subset of terms created by discarding one term.

    See nl_phrase_search for the contract of this function.
    """
    terms = set(terms)
    # Special cased because in the two-term case there is no benefit by having
    # a more complex rank & search function.
    # sorted for doctesting convenience - should have no impact on tsearch2.
    if len(terms) < 3:
        return "|".join(sorted(terms))
    # Expand
    and_groups = [None] * (len(terms) + 1)
    for pos in range(len(terms) + 1):
        and_groups[pos] = set(terms)
    # sorted for doctesting convenience - should have no impact on tsearch2.
    for pos, term in enumerate(sorted(terms)):
        and_groups[pos + 1].discard(term)
    # sorted for doctesting convenience - should have no impact on tsearch2.
    and_clauses = ["(" + "&".join(sorted(group)) + ")" for group in and_groups]
    return "|".join(and_clauses)


def _slow_nl_phrase_search(terms, table, constraint_clauses):
    """Return the tsearch2 query that should be use to do a phrase search.

    This function implement an algorithm similar to the one used by MySQL
    natural language search (as documented at
    http://dev.mysql.com/doc/refman/5.0/en/fulltext-search.html).

    It eliminates stop words from the phrase and normalize each terms
    according to the full text indexation rules (lowercasing and stemming)
    Each term that is present in more than 50% of the candidate rows is also
    eliminated from the query. That term eliminatation is only done when there
    are 5 candidate rows or more.

    The remaining terms are then ORed together. One should use the
    ts_rank() or ts_rank_cd() function to order the results from running
    that query. This will make rows that use more of the terms and for
    which the terms are found closer in the text at the top of the list,
    while still returning rows that use only some of the terms.

    :terms: Some candidate search terms.

    :table: This should be the Storm class representing the base type.

    :constraints: Additional Storm clause that limits the rows to a subset
        of the table.

    Caveat: The model class must define a 'fti' column which is then used
    for full text searching.
    """
    if constraint_clauses is None:
        constraint_clauses = []

    store = IStore(table)
    total = store.find(table, *constraint_clauses).count()
    term_candidates = terms
    if total < 5:
        return "|".join(term_candidates)

    # Build the query to get all the counts. We get all the counts in
    # one query, using COUNT(CASE ...), since issuing separate queries
    # with COUNT(*) is a lot slower.
    counts = store.find(
        tuple(
            Count(Case([(fti_search(table, term), True)], default=None))
            for term in term_candidates
        ),
        *constraint_clauses,
    ).one()

    # Remove words that are too common.
    terms = [
        term
        for count, term in zip(counts, term_candidates)
        if float(count) / total < 0.5
    ]
    return "|".join(terms)
