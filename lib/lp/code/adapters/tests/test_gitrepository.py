# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lazr.lifecycle.snapshot import Snapshot
from testtools.matchers import MatchesStructure
from zope.component import getUtility
from zope.interface import providedBy

from lp.code.adapters.gitrepository import GitRepositoryDelta
from lp.code.interfaces.gitrepository import IGitRepository, IGitRepositorySet
from lp.registry.model.persondistributionsourcepackage import (
    PersonDistributionSourcePackage,
)
from lp.registry.model.personociproject import PersonOCIProject
from lp.registry.model.personproduct import PersonProduct
from lp.testing import TestCaseWithFactory, admin_logged_in, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadFunctionalLayer


class TestAdapters(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def assertTargetBehaviour(self, target):
        self.assertRaises(TypeError, IGitRepository, target)
        repository = self.factory.makeGitRepository(target=target)
        self.assertRaises(TypeError, IGitRepository, target)
        with admin_logged_in():
            getUtility(IGitRepositorySet).setDefaultRepository(
                target, repository
            )
        self.assertEqual(repository, IGitRepository(target))

    def test_project(self):
        self.assertTargetBehaviour(self.factory.makeProduct())

    def test_distribution_source_package(self):
        self.assertTargetBehaviour(
            self.factory.makeDistributionSourcePackage()
        )

    def test_oci_project(self):
        self.assertTargetBehaviour(self.factory.makeOCIProject())

    def assertPersonTargetBehaviour(self, target, person_target_factory):
        person = self.factory.makePerson()
        person_target = person_target_factory(person, target)
        self.assertRaises(TypeError, IGitRepository, person_target)
        repository = self.factory.makeGitRepository(
            owner=person, target=target
        )
        self.assertRaises(TypeError, IGitRepository, person_target)
        with person_logged_in(person):
            getUtility(IGitRepositorySet).setDefaultRepositoryForOwner(
                person, target, repository, person
            )
        self.assertEqual(repository, IGitRepository(person_target))

    def test_person_project(self):
        self.assertPersonTargetBehaviour(
            self.factory.makeProduct(), PersonProduct
        )

    def test_person_distribution_source_package(self):
        self.assertPersonTargetBehaviour(
            self.factory.makeDistributionSourcePackage(),
            PersonDistributionSourcePackage,
        )

    def test_person_oci_project(self):
        self.assertPersonTargetBehaviour(
            self.factory.makeOCIProject(), PersonOCIProject
        )


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
