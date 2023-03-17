# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the Git reference vocabularies."""

from datetime import datetime, timedelta, timezone

from testtools.matchers import MatchesStructure
from zope.schema.vocabulary import SimpleTerm
from zope.security.proxy import removeSecurityProxy

from lp.code.vocabularies.gitref import GitBranchVocabulary, GitRefVocabulary
from lp.services.webapp.vocabulary import IHugeVocabulary
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestGitRefVocabulary(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    vocabulary_class = GitRefVocabulary

    def test_getTermByToken(self):
        [ref] = self.factory.makeGitRefs()
        vocab = self.vocabulary_class(ref.repository)
        term = SimpleTerm(ref, ref.path, ref.name)
        self.assertEqual(term.token, vocab.getTermByToken(ref.name).token)
        self.assertEqual(term.token, vocab.getTermByToken(ref.path).token)
        self.assertRaises(LookupError, vocab.getTermByToken, "nonexistent")

    def test_provides_IHugeVocabulary(self):
        vocab = self.vocabulary_class(self.factory.makeGitRepository())
        self.assertProvides(vocab, IHugeVocabulary)

    def test_init_no_repository(self):
        # The repository is None if the context cannot be adapted to a
        # repository.
        vocab = self.vocabulary_class(
            self.factory.makeSnap(branch=self.factory.makeAnyBranch())
        )
        self.assertIsNone(vocab.repository)

    def test_setRepository(self):
        # Callers can set the repository after instantiation.
        vocab = self.vocabulary_class(
            self.factory.makeSnap(branch=self.factory.makeAnyBranch())
        )
        repository = self.factory.makeGitRepository()
        vocab.setRepository(repository)
        self.assertEqual(repository, vocab.repository)

    def test_toTerm(self):
        [ref] = self.factory.makeGitRefs()
        self.assertThat(
            self.vocabulary_class(ref.repository).toTerm(ref),
            MatchesStructure.byEquality(
                value=ref, token=ref.path, title=ref.name
            ),
        )

    def test_searchForTerms(self):
        ref_master, ref_next, ref_next_squared, _ = self.factory.makeGitRefs(
            paths=[
                "refs/heads/master",
                "refs/heads/next",
                "refs/heads/next-squared",
                "refs/tags/next-1.0",
            ]
        )
        removeSecurityProxy(
            ref_master.repository
        )._default_branch = ref_master.path
        vocab = self.vocabulary_class(ref_master.repository)
        self.assertContentEqual(
            [term.value.path for term in vocab.searchForTerms("master")],
            ["refs/heads/master"],
        )
        self.assertContentEqual(
            [term.value.path for term in vocab.searchForTerms("next")],
            [
                "refs/heads/next",
                "refs/heads/next-squared",
                "refs/tags/next-1.0",
            ],
        )
        self.assertContentEqual(
            [
                term.value.path
                for term in vocab.searchForTerms("refs/heads/next")
            ],
            ["refs/heads/next", "refs/heads/next-squared"],
        )
        self.assertContentEqual(
            [term.value.path for term in vocab.searchForTerms("")],
            [
                "refs/heads/master",
                "refs/heads/next",
                "refs/heads/next-squared",
                "refs/tags/next-1.0",
            ],
        )
        self.assertContentEqual(
            [term.token for term in vocab.searchForTerms("nonexistent")], []
        )

    def test_searchForTerms_ordering(self):
        # The default branch (if it matches) is shown first, followed by
        # other matches in decreasing order of last commit date.
        (
            ref_master,
            ref_master_old,
            ref_master_older,
        ) = self.factory.makeGitRefs(
            paths=[
                "refs/heads/master",
                "refs/heads/master-old",
                "refs/heads/master-older",
            ]
        )
        removeSecurityProxy(
            ref_master.repository
        )._default_branch = ref_master.path
        now = datetime.now(timezone.utc)
        removeSecurityProxy(ref_master_old).committer_date = now - timedelta(
            days=1
        )
        removeSecurityProxy(ref_master_older).committer_date = now - timedelta(
            days=2
        )
        vocab = self.vocabulary_class(ref_master.repository)
        self.assertEqual(
            [term.value.path for term in vocab.searchForTerms("master")],
            [
                "refs/heads/master",
                "refs/heads/master-old",
                "refs/heads/master-older",
            ],
        )

    def test_len(self):
        ref_master, _, _, _ = self.factory.makeGitRefs(
            paths=[
                "refs/heads/master",
                "refs/heads/next",
                "refs/heads/next-squared",
                "refs/tags/next-1.0",
            ]
        )
        self.assertEqual(4, len(self.vocabulary_class(ref_master.repository)))

    def test_no_term_with_no_repository(self):
        # Form validation can mean that we don't always have a repository
        # available before a widget is rendered, which needs to not error
        vocab = self.vocabulary_class(
            self.factory.makeSnap(branch=self.factory.makeAnyBranch())
        )
        [ref] = self.factory.makeGitRefs()
        term = SimpleTerm(ref, ref.name, ref.name)
        self.assertRaises(LookupError, vocab.getTermByToken, term.token)

    def test_no_results_with_no_repository(self):
        vocab = self.vocabulary_class(
            self.factory.makeSnap(branch=self.factory.makeAnyBranch())
        )
        results = vocab.searchForTerms("master")
        self.assertEqual(results.count(), 0)


class TestGitBranchVocabulary(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    vocabulary_class = GitBranchVocabulary

    def test_getTermByToken(self):
        [ref] = self.factory.makeGitRefs()
        vocab = self.vocabulary_class(ref.repository)
        term = SimpleTerm(ref, ref.name, ref.name)
        self.assertEqual(term.token, vocab.getTermByToken(ref.name).token)
        self.assertEqual(term.token, vocab.getTermByToken(ref.path).token)
        self.assertRaises(LookupError, vocab.getTermByToken, "nonexistent")

    def test_toTerm(self):
        [ref] = self.factory.makeGitRefs()
        self.assertThat(
            self.vocabulary_class(ref.repository).toTerm(ref),
            MatchesStructure.byEquality(
                value=ref, token=ref.name, title=ref.name
            ),
        )

    def test_searchForTerms(self):
        ref_master, ref_next, ref_next_squared, _ = self.factory.makeGitRefs(
            paths=[
                "refs/heads/master",
                "refs/heads/next",
                "refs/heads/next-squared",
                "refs/tags/next-1.0",
            ]
        )
        removeSecurityProxy(
            ref_master.repository
        )._default_branch = ref_master.path
        vocab = self.vocabulary_class(ref_master.repository)
        self.assertContentEqual(
            [term.title for term in vocab.searchForTerms("master")], ["master"]
        )
        self.assertContentEqual(
            [term.title for term in vocab.searchForTerms("next")],
            ["next", "next-squared"],
        )
        self.assertContentEqual(
            [term.title for term in vocab.searchForTerms("refs/heads/next")],
            ["next", "next-squared"],
        )
        self.assertContentEqual(
            [term.title for term in vocab.searchForTerms("")],
            ["master", "next", "next-squared"],
        )
        self.assertContentEqual(
            [term.token for term in vocab.searchForTerms("nonexistent")], []
        )

    def test_searchForTerms_ordering(self):
        # The default branch (if it matches) is shown first, followed by
        # other matches in decreasing order of last commit date.
        (
            ref_master,
            ref_master_old,
            ref_master_older,
        ) = self.factory.makeGitRefs(
            paths=[
                "refs/heads/master",
                "refs/heads/master-old",
                "refs/heads/master-older",
            ]
        )
        removeSecurityProxy(
            ref_master.repository
        )._default_branch = ref_master.path
        now = datetime.now(timezone.utc)
        removeSecurityProxy(ref_master_old).committer_date = now - timedelta(
            days=1
        )
        removeSecurityProxy(ref_master_older).committer_date = now - timedelta(
            days=2
        )
        vocab = self.vocabulary_class(ref_master.repository)
        self.assertEqual(
            [term.title for term in vocab.searchForTerms("master")],
            ["master", "master-old", "master-older"],
        )

    def test_len(self):
        ref_master, _, _, _ = self.factory.makeGitRefs(
            paths=[
                "refs/heads/master",
                "refs/heads/next",
                "refs/heads/next-squared",
                "refs/tags/next-1.0",
            ]
        )
        self.assertEqual(3, len(self.vocabulary_class(ref_master.repository)))
