# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Vocabularies that contain Git references."""

__all__ = [
    "GitBranchVocabulary",
    "GitRefVocabulary",
    ]

from lazr.restful.interfaces import IReference
from storm.databases.postgres import Case
from storm.expr import (
    Desc,
    Like,
    like_escape,
    )
from zope.component import getUtility
from zope.interface import (
    implementer,
    Interface,
    )
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
from lp.services.webapp.vocabulary import (
    CountableIterator,
    IHugeVocabulary,
    StormVocabularyBase,
    )


class IRepositoryManagerGitRefVocabulary(Interface):

    def setRepository(self, repository):
        """Set the repository after the vocabulary was instantiated."""

    def setRepositoryURL(self, repository_url):
        """Set the repository URL after the vocabulary was instantiated."""


@implementer(IHugeVocabulary)
@implementer(IRepositoryManagerGitRefVocabulary)
class GitRefVocabulary(StormVocabularyBase):
    """A vocabulary for references in a given Git repository."""

    _table = GitRef
    displayname = "Select a branch or tag"
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
        """See `IRepositoryManagerGitRefVocabulary`."""
        self.repository = repository
        self.repository_url = None

    def setRepositoryURL(self, repository_url):
        """See `IRepositoryManagerGitRefVocabulary`."""
        self.repository = None
        self.repository_url = repository_url

    def _checkHasRepository(self):
        return not (self.repository is None and self.repository_url is None)

    @property
    def _order_by(self):
        rank = Case(
            cases=[(self._table.path == self.repository.default_branch, 2)],
            default=1)
        return [
            Desc(rank),
            Desc(self._table.committer_date),
            self._table.path]

    def toTerm(self, ref):
        """See `StormVocabularyBase`."""
        return SimpleTerm(ref, ref.path, ref.name)

    def getTermByToken(self, token):
        """See `IVocabularyTokenized`."""
        if not self._checkHasRepository():
            raise LookupError(token)
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
        if not self._checkHasRepository():
            return CountableIterator(0, [], self.toTerm)
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

    displayname = "Select a branch"

    def _makePattern(self, query=None):
        parts = []
        if query is None or not query.startswith("refs/heads/"):
            parts.append("refs/heads/".translate(like_escape))
        parts.append("%")
        if query is not None:
            parts.extend([query.lower().translate(like_escape), "%"])
        return "".join(parts)

    def toTerm(self, ref):
        """See `StormVocabularyBase`."""
        return SimpleTerm(ref, ref.name, ref.name)
