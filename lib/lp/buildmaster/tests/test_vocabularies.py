# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from zope.schema.vocabulary import getVocabularyRegistry

from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestBuilderResourceVocabulary(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

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
