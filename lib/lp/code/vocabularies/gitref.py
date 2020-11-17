# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Vocabularies that contain Git references."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    "GitBranchVocabulary",
    "GitRefVocabulary",
    ]

from lazr.restful.interfaces import IReference
from storm.expr import (
    Desc,
    Like,
    like_escape,
    )
from zope.component import getUtility
from zope.interface import implementer
from zope.schema.vocabulary import SimpleTerm
from zope.security.proxy import isinstance as zope_isinstance

from lp.code.interfaces.gitref import IGitRefRemoteSet
from lp.code.interfaces.gitrepository import (
    IGitRepository,
    IHasGitRepositoryURL,
    )
from lp.code.model.gitref import (
    GitRef,
    GitRefRemote,
    )
from lp.services.database.interfaces import IStore
from storm.databases.postgres import Case
from lp.services.webapp.vocabulary import (
    CountableIterator,
    IHugeVocabulary,
    StormVocabularyBase,
    )


@implementer(IHugeVocabulary)
class GitRefVocabulary(StormVocabularyBase):
    """A vocabulary for references in a given Git repository."""

    _table = GitRef
    # In the base case (i.e. not GitBranchVocabulary) this may also be a
    # more general reference such as refs/tags/foo, but experience suggests
    # that people find talking about references in the web UI to be
    # baffling, so we tell a white lie here.
    displayname = "Select a branch"
    step_title = "Search"

    def __init__(self, context):
        super(GitRefVocabulary, self).__init__(context=context)
        if IReference.providedBy(context):
            context = context.context
        try:
            self.repository = IGitRepository(context)
        except TypeError:
            self.repository = None
        try:
            self.repository_url = (
                IHasGitRepositoryURL(context).git_repository_url)
        except TypeError:
            self.repository_url = None

    def setRepository(self, repository):
        """Set the repository after the vocabulary was instantiated."""
        self.repository = repository
        self.repository_url = None

    def setRepositoryURL(self, repository_url):
        """Set the repository URL after the vocabulary was instantiated."""
        self.repository = None
        self.repository_url = repository_url

    def _assertHasRepository(self):
        if self.repository is None and self.repository_url is None:
            raise AssertionError(
                "GitRefVocabulary cannot be used without setting a "
                "repository or a repository URL.")

    @property
    def _order_by(self):
        rank = Case(
            cases=[(self._table.path == self.repository.default_branch, 2)],
            default=1)
        return [Desc(rank), Desc(self._table.committer_date)]

    def toTerm(self, ref):
        """See `StormVocabularyBase`."""
        return SimpleTerm(ref, ref.path, ref.name)

    def getTermByToken(self, token):
        """See `IVocabularyTokenized`."""
        self._assertHasRepository()
        if self.repository is not None:
            ref = self.repository.getRefByPath(token)
            if ref is None:
                raise LookupError(token)
        else:
            ref = getUtility(IGitRefRemoteSet).new(self.repository_url, token)
        return self.toTerm(ref)

    def _makePattern(self, query=None):
        parts = ["%"]
        if query is not None:
            parts.extend([query.lower().translate(like_escape), "%"])
        return "".join(parts)

    def searchForTerms(self, query=None, vocab_filter=None):
        """See `IHugeVocabulary."""
        self._assertHasRepository()
        if self.repository is not None:
            pattern = self._makePattern(query=query)
            results = IStore(self._table).find(
                self._table,
                self._table.repository_id == self.repository.id,
                Like(self._table.path, pattern, "!")).order_by(self._order_by)
        else:
            results = self.emptySelectResults()
        return CountableIterator(results.count(), results, self.toTerm)

    def getTerm(self, value):
        # remote refs aren't database backed
        if zope_isinstance(value, GitRefRemote):
            return self.toTerm(value)
        return super(GitRefVocabulary, self).getTerm(value)

    def __len__(self):
        """See `IVocabulary`."""
        return self.searchForTerms().count()

    def __contains__(self, obj):
        # We know nothing about GitRefRemote, so we just have to assume
        # that they exist in the remote repository
        if zope_isinstance(obj, GitRefRemote):
            return True
        if obj in self.repository.refs:
            return True
        return False


class GitBranchVocabulary(GitRefVocabulary):
    """A vocabulary for branches in a given Git repository."""

    def _makePattern(self, query=None):
        parts = []
        # XXX allow HEAD?
        if query is None or not query.startswith("refs/heads/"):
            parts.append("refs/heads/".translate(like_escape))
        parts.append("%")
        if query is not None:
            parts.extend([query.lower().translate(like_escape), "%"])
        return "".join(parts)

    def toTerm(self, ref):
        """See `StormVocabularyBase`."""
        return SimpleTerm(ref, ref.name, ref.name)
