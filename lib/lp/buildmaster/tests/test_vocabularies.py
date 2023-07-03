# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from zope.schema.interfaces import ITerm, ITokenizedTerm, IVocabularyTokenized
from zope.schema.vocabulary import getVocabularyRegistry

from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestBuilderResourceVocabulary(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def test_provides_interface(self):
        self.factory.makeBuilder()
        repository = self.factory.makeGitRepository()
        vocab = getVocabularyRegistry().get(repository, "BuilderResource")
        self.assertProvides(vocab, IVocabularyTokenized)

    def test___contains__(self):
        self.factory.makeBuilder(open_resources=["large"])
        repository = self.factory.makeGitRepository()
        vocab = getVocabularyRegistry().get(repository, "BuilderResource")
        self.assertIn("large", vocab)
        self.assertNotIn("small", vocab)

    def test___len__(self):
        self.factory.makeBuilder(open_resources=["large", "larger"])
        repository = self.factory.makeGitRepository()
        vocab = getVocabularyRegistry().get(repository, "BuilderResource")
        self.assertEqual(2, len(vocab))

    def test_getTerm(self):
        self.factory.makeBuilder(open_resources=["large"])
        repository = self.factory.makeGitRepository()
        vocab = getVocabularyRegistry().get(repository, "BuilderResource")
        term = vocab.getTerm("large")
        self.assertProvides(term, ITerm)
        self.assertEqual("large", term.value)
        self.assertRaises(LookupError, vocab.getTerm, "small")

    def test_getTermByToken(self):
        self.factory.makeBuilder(open_resources=["large"])
        repository = self.factory.makeGitRepository()
        vocab = getVocabularyRegistry().get(repository, "BuilderResource")
        term = vocab.getTermByToken("large")
        self.assertProvides(term, ITokenizedTerm)
        self.assertEqual("large", term.value)
        self.assertEqual("large", term.token)
        self.assertRaises(LookupError, vocab.getTerm, "small")

    def test_no_resources(self):
        self.factory.makeBuilder()
        repository = self.factory.makeGitRepository()
        vocab = getVocabularyRegistry().get(repository, "BuilderResource")
        self.assertEqual([], list(vocab))

    def test_current_resources(self):
        for open_resources, restricted_resources in (
            (None, None),
            (["large"], None),
            (["large", "larger"], None),
            (None, ["gpu"]),
            (["large"], ["gpu"]),
        ):
            self.factory.makeBuilder(
                open_resources=open_resources,
                restricted_resources=restricted_resources,
            )
        repository = self.factory.makeGitRepository()
        vocab = getVocabularyRegistry().get(repository, "BuilderResource")
        self.assertEqual(
            ["gpu", "large", "larger"], [term.value for term in vocab]
        )
        self.assertEqual(
            ["gpu", "large", "larger"], [term.token for term in vocab]
        )

    def test_merges_constraints_from_context(self):
        self.factory.makeBuilder(open_resources=["large"])
        repository = self.factory.makeGitRepository(
            builder_constraints=["really-large"]
        )
        vocab = getVocabularyRegistry().get(repository, "BuilderResource")
        self.assertEqual(
            ["large", "really-large"], [term.value for term in vocab]
        )
        self.assertEqual(
            ["large", "really-large"], [term.token for term in vocab]
        )

    def test_skips_invisible_builders(self):
        self.factory.makeBuilder(open_resources=["large"])
        self.factory.makeBuilder(active=False, open_resources=["old"])
        repository = self.factory.makeGitRepository()
        vocab = getVocabularyRegistry().get(repository, "BuilderResource")
        self.assertEqual(["large"], [term.value for term in vocab])
        self.assertEqual(["large"], [term.token for term in vocab])
