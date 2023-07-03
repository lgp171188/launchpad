# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lazr.lifecycle.snapshot import Snapshot
from testtools.matchers import MatchesStructure
from zope.interface import providedBy

from lp.code.adapters.gitrepository import GitRepositoryDelta
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.layers import LaunchpadFunctionalLayer


class TestGitRepositoryDelta(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_no_modification(self):
        # If there are no modifications, no delta is returned.
        repository = self.factory.makeGitRepository(name="foo")
        old_repository = Snapshot(repository, providing=providedBy(repository))
        delta = GitRepositoryDelta.construct(
            old_repository, repository, repository.owner
        )
        self.assertIsNone(delta)

    def test_modification(self):
        # If there are modifications, the delta reflects them.
        owner = self.factory.makePerson(name="person")
        project = self.factory.makeProduct(name="project")
        repository = self.factory.makeGitRepository(
            owner=owner, target=project, name="foo"
        )
        old_repository = Snapshot(repository, providing=providedBy(repository))
        with person_logged_in(repository.owner):
            repository.setName("bar", repository.owner)
        delta = GitRepositoryDelta.construct(old_repository, repository, owner)
        self.assertIsNotNone(delta)
        self.assertThat(
            delta,
            MatchesStructure.byEquality(
                name={
                    "old": "foo",
                    "new": "bar",
                },
                git_identity={
                    "old": "lp:~person/project/+git/foo",
                    "new": "lp:~person/project/+git/bar",
                },
            ),
        )
