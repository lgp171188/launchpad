# Copyright 2015-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `IGitNamespace` implementations."""

from unittest import mock

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import (
    FREE_INFORMATION_TYPES,
    NON_EMBARGOED_INFORMATION_TYPES,
    PUBLIC_INFORMATION_TYPES,
    InformationType,
)
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.app.interfaces.services import IService
from lp.app.validators import LaunchpadValidationError
from lp.code.enums import GitRepositoryType
from lp.code.errors import (
    GitDefaultConflict,
    GitRepositoryCreatorNotMemberOfOwnerTeam,
    GitRepositoryCreatorNotOwner,
    GitRepositoryExists,
)
from lp.code.interfaces.githosting import IGitHostingClient
from lp.code.interfaces.gitnamespace import (
    IGitNamespace,
    IGitNamespacePolicy,
    get_git_namespace,
)
from lp.code.interfaces.gitrepository import IGitRepositorySet
from lp.code.model.gitnamespace import (
    OCIProjectGitNamespace,
    PackageGitNamespace,
    PersonalGitNamespace,
    ProjectGitNamespace,
)
from lp.registry.enums import (
    BranchSharingPolicy,
    PersonVisibility,
    SharingPermission,
)
from lp.registry.interfaces.accesspolicy import (
    IAccessPolicyGrantFlatSource,
    IAccessPolicySource,
)
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import DatabaseFunctionalLayer


class NamespaceMixin:
    """Tests common to all namespace implementations.

    You might even call these 'interface tests'.
    """

    def test_provides_interface(self):
        # All Git namespaces provide IGitNamespace.
        self.assertProvides(self.getNamespace(), IGitNamespace)

    def test_createRepository_right_namespace(self):
        # createRepository creates a repository in that namespace.
        namespace = self.getNamespace()
        repository_name = self.factory.getUniqueUnicode()
        registrant = removeSecurityProxy(namespace).owner
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED, registrant, repository_name
        )
        self.assertEqual(
            "%s/+git/%s" % (namespace.name, repository_name),
            repository.unique_name,
        )
        self.assertEqual(InformationType.PUBLIC, repository.information_type)

    def test_createRepository_passes_through(self):
        # createRepository takes all the arguments that the `GitRepository`
        # constructor takes, except for the ones that define the namespace.
        namespace = self.getNamespace()
        repository_name = self.factory.getUniqueUnicode()
        registrant = removeSecurityProxy(namespace).owner
        reviewer = self.factory.makePerson()
        description = self.factory.getUniqueUnicode()
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED,
            registrant,
            repository_name,
            reviewer=reviewer,
            description=description,
        )
        self.assertEqual(GitRepositoryType.HOSTED, repository.repository_type)
        self.assertEqual(repository_name, repository.name)
        self.assertEqual(registrant, repository.registrant)
        self.assertEqual(reviewer, repository.reviewer)
        self.assertEqual(description, repository.description)
        self.assertIsNone(repository.builder_constraints)

    def test_createRepository_subscribes_owner(self):
        owner = self.factory.makeTeam()
        namespace = self.getNamespace(owner)
        repository_name = self.factory.getUniqueUnicode()
        registrant = owner.teamowner
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED, registrant, repository_name
        )
        self.assertEqual([owner], list(repository.subscribers))

    def test_createRepository_creates_on_githosting_sync(self):
        hosting_client = mock.Mock()
        self.useFixture(ZopeUtilityFixture(hosting_client, IGitHostingClient))
        owner = self.factory.makeTeam()
        namespace = self.getNamespace(owner)
        repository_name = self.factory.getUniqueUnicode()
        registrant = owner.teamowner
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED,
            registrant,
            repository_name,
            with_hosting=True,
        )
        path = repository.getInternalPath()
        self.assertEqual(
            [mock.call(path, clone_from=None, async_create=False)],
            hosting_client.create.call_args_list,
        )

    def test_createRepository_creates_on_githosting_async(self):
        hosting_client = mock.Mock()
        self.useFixture(ZopeUtilityFixture(hosting_client, IGitHostingClient))
        owner = self.factory.makeTeam()
        namespace = self.getNamespace(owner)
        repository_name = self.factory.getUniqueUnicode()
        registrant = owner.teamowner
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED,
            registrant,
            repository_name,
            with_hosting=True,
            async_hosting=True,
        )
        path = repository.getInternalPath()
        self.assertEqual(
            [mock.call(path, clone_from=None, async_create=True)],
            hosting_client.create.call_args_list,
        )

    def test_createRepository_builder_constraints(self):
        # createRepository can be told to create a repository whose builds
        # have certain builder constraints.
        namespace = self.getNamespace()
        repository_name = self.factory.getUniqueUnicode()
        registrant = removeSecurityProxy(namespace).owner
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED,
            registrant,
            repository_name,
            builder_constraints=["gpu"],
        )
        self.assertEqual(("gpu",), repository.builder_constraints)

    def test_getRepositories_no_repositories(self):
        # getRepositories on an IGitNamespace returns a result set of
        # repositories in that namespace.  If there are no repositories, the
        # result set is empty.
        namespace = self.getNamespace()
        self.assertEqual([], list(namespace.getRepositories()))

    def test_getRepositories_some_repositories(self):
        # getRepositories on an IGitNamespace returns a result set of
        # repositories in that namespace.
        namespace = self.getNamespace()
        repository_name = self.factory.getUniqueUnicode()
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED,
            removeSecurityProxy(namespace).owner,
            repository_name,
        )
        self.assertEqual([repository], list(namespace.getRepositories()))

    def test_getByName_default(self):
        # getByName returns the given default if there is no repository in
        # the namespace with that name.
        namespace = self.getNamespace()
        default = object()
        match = namespace.getByName(self.factory.getUniqueUnicode(), default)
        self.assertIs(default, match)

    def test_getByName_default_is_none(self):
        # The default 'default' return value is None.
        namespace = self.getNamespace()
        match = namespace.getByName(self.factory.getUniqueUnicode())
        self.assertIsNone(match)

    def test_getByName_matches(self):
        namespace = self.getNamespace()
        repository_name = self.factory.getUniqueUnicode()
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED,
            removeSecurityProxy(namespace).owner,
            repository_name,
        )
        match = namespace.getByName(repository_name)
        self.assertEqual(repository, match)

    def test_isNameUsed_not(self):
        namespace = self.getNamespace()
        name = self.factory.getUniqueUnicode()
        self.assertFalse(namespace.isNameUsed(name))

    def test_isNameUsed_yes(self):
        namespace = self.getNamespace()
        repository_name = self.factory.getUniqueUnicode()
        namespace.createRepository(
            GitRepositoryType.HOSTED,
            removeSecurityProxy(namespace).owner,
            repository_name,
        )
        self.assertTrue(namespace.isNameUsed(repository_name))

    def test_findUnusedName_unused(self):
        # findUnusedName returns the given name if that name is not used.
        namespace = self.getNamespace()
        name = self.factory.getUniqueUnicode()
        unused_name = namespace.findUnusedName(name)
        self.assertEqual(name, unused_name)

    def test_findUnusedName_used(self):
        # findUnusedName returns the given name with a numeric suffix if
        # it's already used.
        namespace = self.getNamespace()
        name = self.factory.getUniqueUnicode()
        namespace.createRepository(
            GitRepositoryType.HOSTED,
            removeSecurityProxy(namespace).owner,
            name,
        )
        unused_name = namespace.findUnusedName(name)
        self.assertEqual("%s-1" % name, unused_name)

    def test_findUnusedName_used_twice(self):
        # findUnusedName returns the given name with a numeric suffix if
        # it's already used.
        namespace = self.getNamespace()
        name = self.factory.getUniqueUnicode()
        namespace.createRepository(
            GitRepositoryType.HOSTED,
            removeSecurityProxy(namespace).owner,
            name,
        )
        namespace.createRepository(
            GitRepositoryType.HOSTED,
            removeSecurityProxy(namespace).owner,
            name + "-1",
        )
        unused_name = namespace.findUnusedName(name)
        self.assertEqual("%s-2" % name, unused_name)

    def test_validateMove(self):
        # If the mover is allowed to move the repository into the namespace,
        # if there are absolutely no problems at all, then validateMove
        # raises nothing and returns None.
        namespace = self.getNamespace()
        namespace_owner = removeSecurityProxy(namespace).owner
        repository = self.factory.makeGitRepository()
        # Doesn't raise an exception.
        namespace.validateMove(repository, namespace_owner)

    def test_validateMove_repository_with_name_exists(self):
        # If a repository with the same name as the given repository already
        # exists in the namespace, validateMove raises a GitRepositoryExists
        # error.
        namespace = self.getNamespace()
        namespace_owner = removeSecurityProxy(namespace).owner
        name = self.factory.getUniqueUnicode()
        namespace.createRepository(
            GitRepositoryType.HOSTED,
            removeSecurityProxy(namespace).owner,
            name,
        )
        repository = self.factory.makeGitRepository(name=name)
        self.assertRaises(
            GitRepositoryExists,
            namespace.validateMove,
            repository,
            namespace_owner,
        )

    def test_validateMove_forbidden_owner(self):
        # If the mover isn't allowed to create repositories in the
        # namespace, then they aren't allowed to move repositories in there
        # either, so validateMove will raise a GitRepositoryCreatorNotOwner
        # error.
        namespace = self.getNamespace()
        repository = self.factory.makeGitRepository()
        mover = self.factory.makePerson()
        self.assertRaises(
            GitRepositoryCreatorNotOwner,
            namespace.validateMove,
            repository,
            mover,
        )

    def test_validateMove_not_team_member(self):
        # If the mover isn't allowed to create repositories in the namespace
        # because they aren't a member of the team that owns the namespace,
        # validateMove raises a GitRepositoryCreatorNotMemberOfOwnerTeam
        # error.
        team = self.factory.makeTeam()
        namespace = self.getNamespace(person=team)
        repository = self.factory.makeGitRepository()
        mover = self.factory.makePerson()
        self.assertRaises(
            GitRepositoryCreatorNotMemberOfOwnerTeam,
            namespace.validateMove,
            repository,
            mover,
        )

    def test_validateMove_with_other_name(self):
        # If you pass a name to validateMove, that'll check to see whether
        # the repository could be safely moved given a rename.
        namespace = self.getNamespace()
        namespace_owner = removeSecurityProxy(namespace).owner
        name = self.factory.getUniqueUnicode()
        namespace.createRepository(
            GitRepositoryType.HOSTED,
            removeSecurityProxy(namespace).owner,
            name,
        )
        repository = self.factory.makeGitRepository()
        self.assertRaises(
            GitRepositoryExists,
            namespace.validateMove,
            repository,
            namespace_owner,
            name=name,
        )


class TestPersonalGitNamespace(TestCaseWithFactory, NamespaceMixin):
    """Tests for `PersonalGitNamespace`."""

    layer = DatabaseFunctionalLayer

    def getNamespace(self, person=None):
        if person is None:
            person = self.factory.makePerson()
        return get_git_namespace(person, person)

    def test_name(self):
        # A personal namespace has repositories with names starting with
        # ~foo.
        person = self.factory.makePerson()
        namespace = PersonalGitNamespace(person)
        self.assertEqual("~%s" % person.name, namespace.name)

    def test_owner(self):
        # The person passed to a personal namespace is the owner.
        person = self.factory.makePerson()
        namespace = PersonalGitNamespace(person)
        self.assertEqual(person, removeSecurityProxy(namespace).owner)

    def test_target(self):
        # The target of a personal namespace is the owner of that namespace.
        person = self.factory.makePerson()
        namespace = PersonalGitNamespace(person)
        self.assertEqual(person, namespace.target)

    def test_supports_merge_proposals(self):
        # Personal namespaces support merge proposals.
        self.assertTrue(self.getNamespace().supports_merge_proposals)

    def test_areRepositoriesMergeable_same_repository(self):
        # A personal repository is mergeable into itself.
        owner = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=owner, target=owner)
        self.assertTrue(
            repository.namespace.areRepositoriesMergeable(
                repository, repository
            )
        )

    def test_areRepositoriesMergeable_different_namespaces(self):
        # A personal repository is not mergeable if the origin namespace is
        # not the same as the namespacing checking the mergeability.
        owner = self.factory.makePerson()
        this = self.factory.makeGitRepository(owner=owner, target=owner)
        other = self.factory.makeGitRepository(owner=owner, target=owner)
        self.assertFalse(other.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_different_name(self):
        # A personal repository is not mergeable into another personal
        # repository if they do not have the same name.
        owner = self.factory.makePerson()
        this = self.factory.makeGitRepository(owner=owner, target=owner)
        other = self.factory.makeGitRepository(owner=owner, target=owner)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_same_name(self):
        # A personal repository is mergeable into another personal
        # repository if they have the same name, even if they target different
        # people.
        this_owner = self.factory.makePerson()
        repo_name = "my-personal-repository"
        this = self.factory.makeGitRepository(
            owner=this_owner, target=this_owner, name=repo_name
        )
        other_owner = self.factory.makePerson()
        other = self.factory.makeGitRepository(
            owner=other_owner, target=other_owner, name=repo_name
        )
        self.assertTrue(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_project(self):
        # Project repositories are not mergeable into personal repositories.
        owner = self.factory.makePerson()
        this = self.factory.makeGitRepository(owner=owner, target=owner)
        project = self.factory.makeProduct()
        other = self.factory.makeGitRepository(owner=owner, target=project)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_package(self):
        # Package repositories are not mergeable into personal repositories.
        owner = self.factory.makePerson()
        this = self.factory.makeGitRepository(owner=owner, target=owner)
        dsp = self.factory.makeDistributionSourcePackage()
        other = self.factory.makeGitRepository(owner=owner, target=dsp)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_oci_project(self):
        # OCI Project repositories are not mergeable into personal
        # repositories.
        owner = self.factory.makePerson()
        this = self.factory.makeGitRepository(owner=owner, target=owner)
        oci_project = self.factory.makeOCIProject()
        other = self.factory.makeGitRepository(owner=owner, target=oci_project)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_collection(self):
        # A personal namespace's collection is of personal repositories with
        # the same owner.
        owner = self.factory.makePerson()
        repositories = [
            self.factory.makeGitRepository(owner=owner, target=owner)
            for _ in range(3)
        ]
        other_owner = self.factory.makePerson()
        self.factory.makeGitRepository(owner=other_owner, target=other_owner)
        self.factory.makeGitRepository(
            owner=owner, target=self.factory.makeProduct()
        )
        self.factory.makeGitRepository(
            owner=owner, target=self.factory.makeDistributionSourcePackage()
        )
        self.factory.makeGitRepository(
            owner=owner, target=self.factory.makeOCIProject()
        )
        self.assertContentEqual(
            repositories,
            repositories[0].namespace.collection.getRepositories(),
        )


class TestProjectGitNamespace(TestCaseWithFactory, NamespaceMixin):
    """Tests for `ProjectGitNamespace`."""

    layer = DatabaseFunctionalLayer

    def getNamespace(self, person=None):
        if person is None:
            person = self.factory.makePerson()
        return get_git_namespace(self.factory.makeProduct(), person)

    def test_name(self):
        # A project namespace has repositories with names starting with
        # ~foo/bar.
        person = self.factory.makePerson()
        project = self.factory.makeProduct()
        namespace = ProjectGitNamespace(person, project)
        self.assertEqual(
            "~%s/%s" % (person.name, project.name), namespace.name
        )

    def test_owner(self):
        # The person passed to a project namespace is the owner.
        person = self.factory.makePerson()
        project = self.factory.makeProduct()
        namespace = ProjectGitNamespace(person, project)
        self.assertEqual(person, removeSecurityProxy(namespace).owner)

    def test_target(self):
        # The target for a project namespace is the project.
        person = self.factory.makePerson()
        project = self.factory.makeProduct()
        namespace = ProjectGitNamespace(person, project)
        self.assertEqual(project, namespace.target)

    def test_supports_merge_proposals(self):
        # Project namespaces support merge proposals.
        self.assertTrue(self.getNamespace().supports_merge_proposals)

    def test_areRepositoriesMergeable_same_repository(self):
        # A project repository is mergeable into itself.
        project = self.factory.makeProduct()
        repository = self.factory.makeGitRepository(target=project)
        self.assertTrue(
            repository.namespace.areRepositoriesMergeable(
                repository, repository
            )
        )

    def test_areRepositoriesMergeable_same_namespace(self):
        # Repositories of the same project are mergeable.
        project = self.factory.makeProduct()
        this = self.factory.makeGitRepository(target=project)
        other = self.factory.makeGitRepository(target=project)
        self.assertTrue(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_different_namespace(self):
        # Repositories of a different project are not mergeable.
        this_project = self.factory.makeProduct()
        this = self.factory.makeGitRepository(target=this_project)
        other_project = self.factory.makeProduct()
        other = self.factory.makeGitRepository(target=other_project)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_personal(self):
        # Personal repositories are not mergeable into project repositories.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        this = self.factory.makeGitRepository(owner=owner, target=project)
        other = self.factory.makeGitRepository(owner=owner, target=owner)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_package(self):
        # Package repositories are not mergeable into project repositories.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        this = self.factory.makeGitRepository(owner=owner, target=project)
        dsp = self.factory.makeDistributionSourcePackage()
        other = self.factory.makeGitRepository(owner=owner, target=dsp)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_oci_project(self):
        # OCI Project repositories are not mergeable into project repositories.
        owner = self.factory.makePerson()
        project = self.factory.makeProduct()
        this = self.factory.makeGitRepository(owner=owner, target=project)
        oci_project = self.factory.makeOCIProject()
        other = self.factory.makeGitRepository(owner=owner, target=oci_project)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_collection(self):
        # A project namespace's collection is of repositories for the same
        # project.
        project = self.factory.makeProduct()
        repositories = [
            self.factory.makeGitRepository(target=project) for _ in range(3)
        ]
        self.factory.makeGitRepository(target=self.factory.makeProduct())
        self.factory.makeGitRepository(
            owner=repositories[0].owner, target=repositories[0].owner
        )
        self.factory.makeGitRepository(
            target=self.factory.makeDistributionSourcePackage()
        )
        self.factory.makeGitRepository(target=self.factory.makeOCIProject())
        self.assertContentEqual(
            repositories,
            repositories[0].namespace.collection.getRepositories(),
        )


class TestOCIProjectGitNamespace(TestCaseWithFactory, NamespaceMixin):
    """Tests for `OCIProjectGitNamespace`."""

    layer = DatabaseFunctionalLayer

    def getNamespace(self, person=None):
        if person is None:
            person = self.factory.makePerson()
        return get_git_namespace(self.factory.makeOCIProject(), person)

    def test_name(self):
        person = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        namespace = OCIProjectGitNamespace(person, oci_project)
        self.assertEqual(
            "~%s/%s/+oci/%s"
            % (
                person.name,
                oci_project.distribution.name,
                oci_project.ociprojectname.name,
            ),
            namespace.name,
        )

    def test_owner(self):
        # The person passed to an oci project namespace is the owner.
        person = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        namespace = OCIProjectGitNamespace(person, oci_project)
        self.assertEqual(person, removeSecurityProxy(namespace).owner)

    def test_target(self):
        # The target for an oci project namespace is the oci project.
        person = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        namespace = OCIProjectGitNamespace(person, oci_project)
        self.assertEqual(oci_project, namespace.target)

    def test_supports_merge_proposals(self):
        # OCI Project namespaces support merge proposals.
        self.assertTrue(self.getNamespace().supports_merge_proposals)

    def test_areRepositoriesMergeable_same_repository(self):
        # An OCI Project repository is mergeable into itself.
        oci_project = self.factory.makeOCIProject()
        repository = self.factory.makeGitRepository(target=oci_project)
        self.assertTrue(
            repository.namespace.areRepositoriesMergeable(
                repository, repository
            )
        )

    def test_areRepositoriesMergeable_same_namespace(self):
        # Repositories of the same OCI Project are mergeable.
        oci_project = self.factory.makeOCIProject()
        this = self.factory.makeGitRepository(target=oci_project)
        other = self.factory.makeGitRepository(target=oci_project)
        self.assertTrue(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_different_namespace(self):
        # Repositories of a different OCI Project are not mergeable.
        this_oci_project = self.factory.makeOCIProject()
        this = self.factory.makeGitRepository(target=this_oci_project)
        other_oci_project = self.factory.makeOCIProject()
        other = self.factory.makeGitRepository(target=other_oci_project)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_personal(self):
        # Personal repositories are not mergeable into OCI Project
        # repositories.
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        this = self.factory.makeGitRepository(owner=owner, target=oci_project)
        other = self.factory.makeGitRepository(owner=owner, target=owner)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_project(self):
        # Project repositories are not mergeable into OCI Project repositories.
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        this = self.factory.makeGitRepository(owner=owner, target=oci_project)
        project = self.factory.makeProduct()
        other = self.factory.makeGitRepository(owner=owner, target=project)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_package(self):
        # Package repositories are not mergeable into OCI Project repositories.
        owner = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        this = self.factory.makeGitRepository(owner=owner, target=oci_project)
        package = self.factory.makeDistributionSourcePackage()
        other = self.factory.makeGitRepository(owner=owner, target=package)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_collection(self):
        # An OCI Project namespace's collection is of
        # repositories for the same oci project.
        oci_project = self.factory.makeOCIProject()
        repositories = [
            self.factory.makeGitRepository(target=oci_project)
            for _ in range(3)
        ]
        self.factory.makeGitRepository(target=self.factory.makeOCIProject())
        self.factory.makeGitRepository(target=self.factory.makeProduct())
        self.factory.makeGitRepository(
            target=self.factory.makeDistributionSourcePackage()
        )
        self.factory.makeGitRepository(
            owner=repositories[0].owner, target=repositories[0].owner
        )
        self.assertContentEqual(
            repositories,
            repositories[0].namespace.collection.getRepositories(),
        )


class TestProjectGitNamespacePrivacyWithInformationType(TestCaseWithFactory):
    """Tests for the privacy aspects of `ProjectGitNamespace`.

    This tests the behaviour for a project using the new
    branch_sharing_policy rules.
    """

    layer = DatabaseFunctionalLayer

    def makeProjectGitNamespace(self, sharing_policy, person=None):
        if person is None:
            person = self.factory.makePerson()
        project = self.factory.makeProduct()
        self.factory.makeCommercialSubscription(pillar=project)
        with person_logged_in(project.owner):
            project.setBranchSharingPolicy(sharing_policy)
        namespace = ProjectGitNamespace(person, project)
        return namespace

    def test_public_anyone(self):
        namespace = self.makeProjectGitNamespace(BranchSharingPolicy.PUBLIC)
        self.assertContentEqual(
            FREE_INFORMATION_TYPES, namespace.getAllowedInformationTypes()
        )
        self.assertEqual(
            InformationType.PUBLIC, namespace.getDefaultInformationType()
        )

    def test_forbidden_anyone(self):
        namespace = self.makeProjectGitNamespace(BranchSharingPolicy.FORBIDDEN)
        self.assertEqual([], namespace.getAllowedInformationTypes())
        self.assertIsNone(namespace.getDefaultInformationType())

    def test_public_or_proprietary_anyone(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.PUBLIC_OR_PROPRIETARY
        )
        self.assertContentEqual(
            NON_EMBARGOED_INFORMATION_TYPES,
            namespace.getAllowedInformationTypes(),
        )
        self.assertEqual(
            InformationType.PUBLIC, namespace.getDefaultInformationType()
        )

    def test_proprietary_or_public_anyone(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.PROPRIETARY_OR_PUBLIC
        )
        self.assertEqual([], namespace.getAllowedInformationTypes())
        self.assertIsNone(namespace.getDefaultInformationType())

    def test_proprietary_or_public_owner_grantee(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.PROPRIETARY_OR_PUBLIC
        )
        with person_logged_in(namespace.target.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                namespace.target,
                namespace.owner,
                namespace.target.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            NON_EMBARGOED_INFORMATION_TYPES,
            namespace.getAllowedInformationTypes(),
        )
        self.assertEqual(
            InformationType.PROPRIETARY, namespace.getDefaultInformationType()
        )

    def test_proprietary_or_public_caller_grantee(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.PROPRIETARY_OR_PUBLIC
        )
        grantee = self.factory.makePerson()
        with person_logged_in(namespace.target.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                namespace.target,
                grantee,
                namespace.target.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            NON_EMBARGOED_INFORMATION_TYPES,
            namespace.getAllowedInformationTypes(grantee),
        )
        self.assertEqual(
            InformationType.PROPRIETARY,
            namespace.getDefaultInformationType(grantee),
        )

    def test_proprietary_anyone(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.PROPRIETARY
        )
        self.assertEqual([], namespace.getAllowedInformationTypes())
        self.assertIsNone(namespace.getDefaultInformationType())

    def test_proprietary_repository_owner_grantee(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.PROPRIETARY
        )
        with person_logged_in(namespace.target.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                namespace.target,
                namespace.owner,
                namespace.target.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            [InformationType.PROPRIETARY],
            namespace.getAllowedInformationTypes(),
        )
        self.assertEqual(
            InformationType.PROPRIETARY, namespace.getDefaultInformationType()
        )

    def test_proprietary_caller_grantee(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.PROPRIETARY
        )
        grantee = self.factory.makePerson()
        with person_logged_in(namespace.target.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                namespace.target,
                grantee,
                namespace.target.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            [InformationType.PROPRIETARY],
            namespace.getAllowedInformationTypes(grantee),
        )
        self.assertEqual(
            InformationType.PROPRIETARY,
            namespace.getDefaultInformationType(grantee),
        )

    def test_embargoed_or_proprietary_anyone(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.EMBARGOED_OR_PROPRIETARY
        )
        self.assertEqual([], namespace.getAllowedInformationTypes())
        self.assertIsNone(namespace.getDefaultInformationType())

    def test_embargoed_or_proprietary_owner_grantee(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.EMBARGOED_OR_PROPRIETARY
        )
        with person_logged_in(namespace.target.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                namespace.target,
                namespace.owner,
                namespace.target.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            [InformationType.PROPRIETARY, InformationType.EMBARGOED],
            namespace.getAllowedInformationTypes(),
        )
        self.assertEqual(
            InformationType.EMBARGOED, namespace.getDefaultInformationType()
        )

    def test_embargoed_or_proprietary_caller_grantee(self):
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.EMBARGOED_OR_PROPRIETARY
        )
        grantee = self.factory.makePerson()
        with person_logged_in(namespace.target.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                namespace.target,
                grantee,
                namespace.target.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            [InformationType.PROPRIETARY, InformationType.EMBARGOED],
            namespace.getAllowedInformationTypes(grantee),
        )
        self.assertEqual(
            InformationType.EMBARGOED,
            namespace.getDefaultInformationType(grantee),
        )

    def test_grantee_has_no_artifact_grant(self):
        # The owner of a new repository in a project whose default
        # information type is non-public does not have an artifact grant
        # specifically for the new repository, because their existing policy
        # grant is sufficient.
        person = self.factory.makePerson()
        team = self.factory.makeTeam(members=[person])
        namespace = self.makeProjectGitNamespace(
            BranchSharingPolicy.PROPRIETARY, person=person
        )
        with person_logged_in(namespace.target.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                namespace.target,
                team,
                namespace.target.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED, person, self.factory.getUniqueUnicode()
        )
        [policy] = getUtility(IAccessPolicySource).find(
            [(namespace.target, InformationType.PROPRIETARY)]
        )
        apgfs = getUtility(IAccessPolicyGrantFlatSource)
        self.assertContentEqual(
            [
                (namespace.target.owner, {policy: SharingPermission.ALL}, []),
                (team, {policy: SharingPermission.ALL}, []),
            ],
            apgfs.findGranteePermissionsByPolicy([policy]),
        )
        self.assertTrue(removeSecurityProxy(repository).visibleByUser(person))


class TestPackageGitNamespace(TestCaseWithFactory, NamespaceMixin):
    """Tests for `PackageGitNamespace`."""

    layer = DatabaseFunctionalLayer

    def getNamespace(self, person=None):
        if person is None:
            person = self.factory.makePerson()
        return get_git_namespace(
            self.factory.makeDistributionSourcePackage(), person
        )

    def test_name(self):
        # A package namespace has repositories that start with
        # ~foo/distribution/+source/packagename.
        person = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        namespace = PackageGitNamespace(person, dsp)
        self.assertEqual(
            "~%s/%s/+source/%s"
            % (person.name, dsp.distribution.name, dsp.sourcepackagename.name),
            namespace.name,
        )

    def test_owner(self):
        # The person passed to a package namespace is the owner.
        person = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        namespace = PackageGitNamespace(person, dsp)
        self.assertEqual(person, removeSecurityProxy(namespace).owner)

    def test_target(self):
        # The target for a package namespace is the distribution source
        # package.
        person = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        namespace = PackageGitNamespace(person, dsp)
        self.assertEqual(dsp, namespace.target)

    def test_supports_merge_proposals(self):
        # Package namespaces support merge proposals.
        self.assertTrue(self.getNamespace().supports_merge_proposals)

    def test_areRepositoriesMergeable_same_repository(self):
        # A package repository is mergeable into itself.
        dsp = self.factory.makeDistributionSourcePackage()
        repository = self.factory.makeGitRepository(target=dsp)
        self.assertTrue(
            repository.namespace.areRepositoriesMergeable(
                repository, repository
            )
        )

    def test_areRepositoriesMergeable_same_namespace(self):
        # Repositories of the same package are mergeable.
        dsp = self.factory.makeDistributionSourcePackage()
        this = self.factory.makeGitRepository(target=dsp)
        other = self.factory.makeGitRepository(target=dsp)
        self.assertTrue(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_different_namespace(self):
        # Repositories of a different package are not mergeable.
        this_dsp = self.factory.makeDistributionSourcePackage()
        this = self.factory.makeGitRepository(target=this_dsp)
        other_dsp = self.factory.makeDistributionSourcePackage()
        other = self.factory.makeGitRepository(target=other_dsp)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_personal(self):
        # Personal repositories are not mergeable into package repositories.
        owner = self.factory.makePerson()
        dsp = self.factory.makeProduct()
        this = self.factory.makeGitRepository(owner=owner, target=dsp)
        other = self.factory.makeGitRepository(owner=owner, target=owner)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_project(self):
        # Project repositories are not mergeable into package repositories.
        owner = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        this = self.factory.makeGitRepository(owner=owner, target=dsp)
        project = self.factory.makeProduct()
        other = self.factory.makeGitRepository(owner=owner, target=project)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_areRepositoriesMergeable_oci_project(self):
        # OCI Project repositories are not mergeable into package repositories.
        owner = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        this = self.factory.makeGitRepository(owner=owner, target=dsp)
        oci_project = self.factory.makeOCIProject()
        other = self.factory.makeGitRepository(owner=owner, target=oci_project)
        self.assertFalse(this.namespace.areRepositoriesMergeable(this, other))

    def test_collection(self):
        # A package namespace's collection is of repositories for the same
        # package.
        dsp = self.factory.makeDistributionSourcePackage()
        repositories = [
            self.factory.makeGitRepository(target=dsp) for _ in range(3)
        ]
        self.factory.makeGitRepository(
            target=self.factory.makeDistributionSourcePackage()
        )
        self.factory.makeGitRepository(target=self.factory.makeProduct())
        self.factory.makeGitRepository(
            owner=repositories[0].owner, target=repositories[0].owner
        )
        self.factory.makeGitRepository(target=self.factory.makeOCIProject())
        self.assertContentEqual(
            repositories,
            repositories[0].namespace.collection.getRepositories(),
        )


class TestPackageGitNamespacePrivacyWithInformationType(TestCaseWithFactory):
    """Tests for the privacy aspects of `PackageGitNamespace`.

    This tests the behaviour for a package in a distribution using the new
    branch_sharing_policy rules.
    """

    layer = DatabaseFunctionalLayer

    def makePackageGitNamespace(self, sharing_policy, person=None):
        if person is None:
            person = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        self.factory.makeCommercialSubscription(pillar=dsp.distribution)
        with person_logged_in(dsp.distribution.owner):
            dsp.distribution.setBranchSharingPolicy(sharing_policy)
        namespace = PackageGitNamespace(person, dsp)
        return namespace

    def test_public_anyone(self):
        namespace = self.makePackageGitNamespace(BranchSharingPolicy.PUBLIC)
        self.assertContentEqual(
            FREE_INFORMATION_TYPES, namespace.getAllowedInformationTypes()
        )
        self.assertEqual(
            InformationType.PUBLIC, namespace.getDefaultInformationType()
        )

    def test_forbidden_anyone(self):
        namespace = self.makePackageGitNamespace(BranchSharingPolicy.FORBIDDEN)
        self.assertEqual([], namespace.getAllowedInformationTypes())
        self.assertIsNone(namespace.getDefaultInformationType())

    def test_public_or_proprietary_anyone(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.PUBLIC_OR_PROPRIETARY
        )
        self.assertContentEqual(
            NON_EMBARGOED_INFORMATION_TYPES,
            namespace.getAllowedInformationTypes(),
        )
        self.assertEqual(
            InformationType.PUBLIC, namespace.getDefaultInformationType()
        )

    def test_proprietary_or_public_anyone(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.PROPRIETARY_OR_PUBLIC
        )
        self.assertEqual([], namespace.getAllowedInformationTypes())
        self.assertIsNone(namespace.getDefaultInformationType())

    def test_proprietary_or_public_owner_grantee(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.PROPRIETARY_OR_PUBLIC
        )
        distribution = namespace.distro_source_package.distribution
        with person_logged_in(distribution.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                distribution,
                namespace.owner,
                distribution.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            NON_EMBARGOED_INFORMATION_TYPES,
            namespace.getAllowedInformationTypes(),
        )
        self.assertEqual(
            InformationType.PROPRIETARY, namespace.getDefaultInformationType()
        )

    def test_proprietary_or_public_caller_grantee(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.PROPRIETARY_OR_PUBLIC
        )
        distribution = namespace.distro_source_package.distribution
        grantee = self.factory.makePerson()
        with person_logged_in(distribution.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                distribution,
                grantee,
                distribution.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            NON_EMBARGOED_INFORMATION_TYPES,
            namespace.getAllowedInformationTypes(grantee),
        )
        self.assertEqual(
            InformationType.PROPRIETARY,
            namespace.getDefaultInformationType(grantee),
        )

    def test_proprietary_anyone(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.PROPRIETARY
        )
        self.assertEqual([], namespace.getAllowedInformationTypes())
        self.assertIsNone(namespace.getDefaultInformationType())

    def test_proprietary_repository_owner_grantee(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.PROPRIETARY
        )
        distribution = namespace.distro_source_package.distribution
        with person_logged_in(distribution.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                distribution,
                namespace.owner,
                distribution.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            [InformationType.PROPRIETARY],
            namespace.getAllowedInformationTypes(),
        )
        self.assertEqual(
            InformationType.PROPRIETARY, namespace.getDefaultInformationType()
        )

    def test_proprietary_caller_grantee(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.PROPRIETARY
        )
        distribution = namespace.distro_source_package.distribution
        grantee = self.factory.makePerson()
        with person_logged_in(distribution.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                distribution,
                grantee,
                distribution.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            [InformationType.PROPRIETARY],
            namespace.getAllowedInformationTypes(grantee),
        )
        self.assertEqual(
            InformationType.PROPRIETARY,
            namespace.getDefaultInformationType(grantee),
        )

    def test_embargoed_or_proprietary_anyone(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.EMBARGOED_OR_PROPRIETARY
        )
        self.assertEqual([], namespace.getAllowedInformationTypes())
        self.assertIsNone(namespace.getDefaultInformationType())

    def test_embargoed_or_proprietary_owner_grantee(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.EMBARGOED_OR_PROPRIETARY
        )
        distribution = namespace.distro_source_package.distribution
        with person_logged_in(distribution.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                distribution,
                namespace.owner,
                distribution.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            [InformationType.PROPRIETARY, InformationType.EMBARGOED],
            namespace.getAllowedInformationTypes(),
        )
        self.assertEqual(
            InformationType.EMBARGOED, namespace.getDefaultInformationType()
        )

    def test_embargoed_or_proprietary_caller_grantee(self):
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.EMBARGOED_OR_PROPRIETARY
        )
        distribution = namespace.distro_source_package.distribution
        grantee = self.factory.makePerson()
        with person_logged_in(distribution.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                distribution,
                grantee,
                distribution.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        self.assertContentEqual(
            [InformationType.PROPRIETARY, InformationType.EMBARGOED],
            namespace.getAllowedInformationTypes(grantee),
        )
        self.assertEqual(
            InformationType.EMBARGOED,
            namespace.getDefaultInformationType(grantee),
        )

    def test_grantee_has_no_artifact_grant(self):
        # The owner of a new repository in a distribution whose default
        # information type is non-public does not have an artifact grant
        # specifically for the new repository, because their existing policy
        # grant is sufficient.
        person = self.factory.makePerson()
        team = self.factory.makeTeam(members=[person])
        namespace = self.makePackageGitNamespace(
            BranchSharingPolicy.PROPRIETARY, person=person
        )
        distribution = namespace.distro_source_package.distribution
        with person_logged_in(distribution.owner):
            getUtility(IService, "sharing").sharePillarInformation(
                distribution,
                team,
                distribution.owner,
                {InformationType.PROPRIETARY: SharingPermission.ALL},
            )
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED, person, self.factory.getUniqueUnicode()
        )
        [policy] = getUtility(IAccessPolicySource).find(
            [(distribution, InformationType.PROPRIETARY)]
        )
        apgfs = getUtility(IAccessPolicyGrantFlatSource)
        self.assertContentEqual(
            [
                (distribution.owner, {policy: SharingPermission.ALL}, []),
                (team, {policy: SharingPermission.ALL}, []),
            ],
            apgfs.findGranteePermissionsByPolicy([policy]),
        )
        self.assertTrue(removeSecurityProxy(repository).visibleByUser(person))


class BaseCanCreateRepositoriesMixin:
    """Common tests for all namespaces."""

    layer = DatabaseFunctionalLayer

    def _getNamespace(self, owner):
        # Return a namespace appropriate for the owner specified.
        raise NotImplementedError(self._getNamespace)

    def test_individual(self):
        # For a GitNamespace for an individual, only the individual can own
        # repositories there.
        person = self.factory.makePerson()
        namespace = self._getNamespace(person)
        self.assertTrue(namespace.canCreateRepositories(person))

    def test_other_user(self):
        # Any other individual cannot own repositories targeted to the
        # person.
        person = self.factory.makePerson()
        namespace = self._getNamespace(person)
        self.assertFalse(
            namespace.canCreateRepositories(self.factory.makePerson())
        )

    def test_team_member(self):
        # A member of a team is able to create a repository in this
        # namespace.
        person = self.factory.makePerson()
        self.factory.makeTeam(owner=person)
        namespace = self._getNamespace(person)
        self.assertTrue(namespace.canCreateRepositories(person))

    def test_team_non_member(self):
        # A person who is not part of the team cannot create repositories
        # for the personal team target.
        person = self.factory.makePerson()
        self.factory.makeTeam(owner=person)
        namespace = self._getNamespace(person)
        self.assertFalse(
            namespace.canCreateRepositories(self.factory.makePerson())
        )


class TestPersonalGitNamespaceCanCreateRepositories(
    TestCaseWithFactory, BaseCanCreateRepositoriesMixin
):
    def _getNamespace(self, owner):
        return PersonalGitNamespace(owner)


class TestPackageGitNamespaceCanCreateBranches(
    TestCaseWithFactory, BaseCanCreateRepositoriesMixin
):
    def _getNamespace(self, owner):
        source_package = self.factory.makeSourcePackage()
        return PackageGitNamespace(owner, source_package)


class TestProjectGitNamespaceCanCreateBranches(
    TestCaseWithFactory, BaseCanCreateRepositoriesMixin
):
    def _getNamespace(
        self, owner, branch_sharing_policy=BranchSharingPolicy.PUBLIC
    ):
        project = self.factory.makeProduct(
            branch_sharing_policy=branch_sharing_policy
        )
        return ProjectGitNamespace(owner, project)

    def setUp(self):
        # Setting visibility policies is an admin-only task.
        super().setUp("admin@canonical.com")

    def test_any_person(self):
        # If there is no privacy set up, any person can create a personal
        # branch on the product.
        person = self.factory.makePerson()
        namespace = self._getNamespace(person, BranchSharingPolicy.PUBLIC)
        self.assertTrue(namespace.canCreateRepositories(person))

    def test_any_person_with_proprietary_repositories(self):
        # If the sharing policy defaults to PROPRIETARY, then non-privileged
        # users cannot create a repository.
        person = self.factory.makePerson()
        namespace = self._getNamespace(person, BranchSharingPolicy.PROPRIETARY)
        self.assertFalse(namespace.canCreateRepositories(person))

    def test_grantee_with_proprietary_repositories(self):
        # If the sharing policy defaults to PROPRIETARY, then non-privileged
        # users cannot create a repository.
        person = self.factory.makePerson()
        other_person = self.factory.makePerson()
        team = self.factory.makeTeam(members=[person])
        namespace = self._getNamespace(team, BranchSharingPolicy.PROPRIETARY)
        getUtility(IService, "sharing").sharePillarInformation(
            namespace.target,
            team,
            namespace.target.owner,
            {InformationType.PROPRIETARY: SharingPermission.ALL},
        )
        self.assertTrue(namespace.canCreateRepositories(person))
        self.assertFalse(namespace.canCreateRepositories(other_person))


class TestNamespaceSet(TestCaseWithFactory):
    """Tests for `get_namespace`."""

    layer = DatabaseFunctionalLayer

    def test_get_personal(self):
        person = self.factory.makePerson()
        namespace = get_git_namespace(person, person)
        self.assertIsInstance(namespace, PersonalGitNamespace)

    def test_get_project(self):
        person = self.factory.makePerson()
        project = self.factory.makeProduct()
        namespace = get_git_namespace(project, person)
        self.assertIsInstance(namespace, ProjectGitNamespace)

    def test_get_package(self):
        person = self.factory.makePerson()
        dsp = self.factory.makeDistributionSourcePackage()
        namespace = get_git_namespace(dsp, person)
        self.assertIsInstance(namespace, PackageGitNamespace)

    def test_get_oci_project(self):
        person = self.factory.makePerson()
        oci_project = self.factory.makeOCIProject()
        namespace = get_git_namespace(oci_project, person)
        self.assertIsInstance(namespace, OCIProjectGitNamespace)


class TestPersonalGitNamespaceAllowedInformationTypes(TestCaseWithFactory):
    """Tests for PersonalGitNamespace.getAllowedInformationTypes."""

    layer = DatabaseFunctionalLayer

    def test_anyone(self):
        # Personal repositories are not private for individuals.
        person = self.factory.makePerson()
        namespace = PersonalGitNamespace(person)
        self.assertContentEqual(
            FREE_INFORMATION_TYPES, namespace.getAllowedInformationTypes()
        )

    def test_public_team(self):
        # Personal repositories for public teams cannot be private.
        team = self.factory.makeTeam()
        namespace = PersonalGitNamespace(team)
        self.assertContentEqual(
            FREE_INFORMATION_TYPES, namespace.getAllowedInformationTypes()
        )

    def test_private_team(self):
        # Personal repositories can be private or public for private teams.
        team = self.factory.makeTeam(visibility=PersonVisibility.PRIVATE)
        namespace = PersonalGitNamespace(team)
        self.assertContentEqual(
            NON_EMBARGOED_INFORMATION_TYPES,
            namespace.getAllowedInformationTypes(),
        )


class TestOCIProjectGitNamespaceAllowedInformationTypes(TestCaseWithFactory):
    """Tests for OCIProjectGitNamespace.getAllowedInformationTypes."""

    layer = DatabaseFunctionalLayer

    def test_anyone(self):
        # OCI project repositories are always public (for now).
        oci_project = self.factory.makeOCIProject()
        person = self.factory.makePerson()
        namespace = OCIProjectGitNamespace(person, oci_project)
        self.assertContentEqual(
            PUBLIC_INFORMATION_TYPES, namespace.getAllowedInformationTypes()
        )


class BaseValidateNewRepositoryMixin:
    layer = DatabaseFunctionalLayer

    def _getNamespace(self, owner):
        # Return a namespace appropriate for the owner specified.
        raise NotImplementedError(self._getNamespace)

    def test_registrant_not_owner(self):
        # If the namespace owner is an individual, and the registrant is not
        # the owner, GitRepositoryCreatorNotOwner is raised.
        namespace = self._getNamespace(self.factory.makePerson())
        self.assertRaises(
            GitRepositoryCreatorNotOwner,
            namespace.validateRegistrant,
            self.factory.makePerson(),
        )

    def test_registrant_not_in_owner_team(self):
        # If the namespace owner is a team, and the registrant is not in the
        # team, GitRepositoryCreatorNotMemberOfOwnerTeam is raised.
        namespace = self._getNamespace(self.factory.makeTeam())
        self.assertRaises(
            GitRepositoryCreatorNotMemberOfOwnerTeam,
            namespace.validateRegistrant,
            self.factory.makePerson(),
        )

    def test_existing_repository(self):
        # If a repository exists with the same name, then
        # GitRepositoryExists is raised.
        namespace = self._getNamespace(self.factory.makePerson())
        repository = namespace.createRepository(
            GitRepositoryType.HOSTED,
            namespace.owner,
            self.factory.getUniqueUnicode(),
        )
        self.assertRaises(
            GitRepositoryExists,
            namespace.validateRepositoryName,
            repository.name,
        )

    def test_invalid_name(self):
        # If the repository name is not valid, a LaunchpadValidationError is
        # raised.
        namespace = self._getNamespace(self.factory.makePerson())
        self.assertRaises(
            LaunchpadValidationError, namespace.validateRepositoryName, "+foo"
        )

    def test_permitted_first_character(self):
        # The first character of a repository name must be a letter or a
        # number.
        namespace = self._getNamespace(self.factory.makePerson())
        for c in [chr(i) for i in range(128)]:
            if c.isalnum():
                namespace.validateRepositoryName(c)
            else:
                self.assertRaises(
                    LaunchpadValidationError,
                    namespace.validateRepositoryName,
                    c,
                )

    def test_permitted_subsequent_character(self):
        # After the first character, letters, numbers and certain
        # punctuation is permitted.
        namespace = self._getNamespace(self.factory.makePerson())
        for c in [chr(i) for i in range(128)]:
            if c.isalnum() or c in "+-_@.":
                namespace.validateRepositoryName("a" + c)
            else:
                self.assertRaises(
                    LaunchpadValidationError,
                    namespace.validateRepositoryName,
                    "a" + c,
                )


class TestPersonalGitNamespaceValidateNewRepository(
    TestCaseWithFactory, BaseValidateNewRepositoryMixin
):
    def _getNamespace(self, owner):
        return PersonalGitNamespace(owner)


class TestPackageGitNamespaceValidateNewRepository(
    TestCaseWithFactory, BaseValidateNewRepositoryMixin
):
    def _getNamespace(self, owner):
        dsp = self.factory.makeDistributionSourcePackage()
        return PackageGitNamespace(owner, dsp)


class TestOCIProjectGitNamespaceValidateNewRepository(
    TestCaseWithFactory, BaseValidateNewRepositoryMixin
):
    def _getNamespace(self, owner):
        oci_project = self.factory.makeOCIProject()
        return OCIProjectGitNamespace(owner, oci_project)


class TestProjectGitNamespaceValidateNewRepository(
    TestCaseWithFactory, BaseValidateNewRepositoryMixin
):
    def _getNamespace(self, owner):
        project = self.factory.makeProduct()
        return ProjectGitNamespace(owner, project)


class TestPersonalGitRepositories(TestCaseWithFactory):
    """Personal repositories have no branch visibility policy."""

    layer = DatabaseFunctionalLayer

    def assertPublic(self, creator, owner):
        """Assert that the policy check would result in a public repository.

        :param creator: The user creating the repository.
        :param owner: The person or team that will be the owner of the
            repository.
        """
        namespace = get_git_namespace(owner, owner)
        self.assertNotIn(
            InformationType.PROPRIETARY, namespace.getAllowedInformationTypes()
        )

    def assertPolicyCheckRaises(self, error, creator, owner):
        """Assert that the policy check raises an exception.

        :param error: The exception class that should be raised.
        :param creator: The user creating the repository.
        :param owner: The person or team that will be the owner of the
            repository.
        """
        policy = IGitNamespacePolicy(get_git_namespace(owner, owner))
        self.assertRaises(error, policy.validateRegistrant, registrant=creator)

    def test_personal_repositories_public(self):
        # Personal repositories created by anyone are public.
        person = self.factory.makePerson()
        self.assertPublic(person, person)

    def test_team_personal_repositories(self):
        # Team-owned personal repositories are allowed, and are public.
        person = self.factory.makePerson()
        team = self.factory.makeTeam(members=[person])
        self.assertPublic(person, team)

    def test_no_create_personal_repository_for_other_user(self):
        # One user can't create personal repositories owned by another.
        self.assertPolicyCheckRaises(
            GitRepositoryCreatorNotOwner,
            self.factory.makePerson(),
            self.factory.makePerson(),
        )


class TestGitNamespaceMoveRepository(TestCaseWithFactory):
    """Test the IGitNamespace.moveRepository method."""

    layer = DatabaseFunctionalLayer

    def assertNamespacesEqual(self, expected, result):
        """Assert that the namespaces refer to the same thing.

        The name of the namespace contains the user name and the context
        parts, so is the easiest thing to check.
        """
        self.assertEqual(expected.name, result.name)

    def test_move_to_same_namespace(self):
        # Moving to the same namespace is effectively a no-op.  No
        # exceptions about matching repository names should be raised.
        repository = self.factory.makeGitRepository()
        namespace = repository.namespace
        namespace.moveRepository(repository, repository.owner)
        self.assertNamespacesEqual(namespace, repository.namespace)

    def test_name_clash_raises(self):
        # A name clash will raise an exception.
        repository = self.factory.makeGitRepository(name="test")
        another = self.factory.makeGitRepository(
            owner=repository.owner, name="test"
        )
        namespace = another.namespace
        self.assertRaises(
            GitRepositoryExists,
            namespace.moveRepository,
            repository,
            repository.owner,
        )

    def test_move_with_rename(self):
        # A name clash with 'rename_if_necessary' set to True will cause the
        # repository to be renamed instead of raising an error.
        repository = self.factory.makeGitRepository(name="test")
        another = self.factory.makeGitRepository(
            owner=repository.owner, name="test"
        )
        namespace = another.namespace
        namespace.moveRepository(
            repository, repository.owner, rename_if_necessary=True
        )
        self.assertEqual("test-1", repository.name)
        self.assertNamespacesEqual(namespace, repository.namespace)

    def test_move_with_new_name(self):
        # A new name for the repository can be specified as part of the move.
        repository = self.factory.makeGitRepository(name="test")
        another = self.factory.makeGitRepository(
            owner=repository.owner, name="test"
        )
        namespace = another.namespace
        namespace.moveRepository(repository, repository.owner, new_name="foo")
        self.assertEqual("foo", repository.name)
        self.assertNamespacesEqual(namespace, repository.namespace)

    def test_sets_repository_owner(self):
        # Moving to a new namespace may change the owner of the repository
        # if the owner of the namespace is different.
        repository = self.factory.makeGitRepository(name="test")
        team = self.factory.makeTeam(repository.owner)
        project = self.factory.makeProduct()
        namespace = ProjectGitNamespace(team, project)
        namespace.moveRepository(repository, repository.owner)
        self.assertEqual(team, repository.owner)
        # And for paranoia.
        self.assertNamespacesEqual(namespace, repository.namespace)

    def test_target_default_clash_raises(self):
        # A clash between target_default repositories will raise an exception.
        repository = self.factory.makeGitRepository()
        repository.setTargetDefault(True)
        another = self.factory.makeGitRepository()
        another.setTargetDefault(True)
        self.assertRaisesWithContent(
            GitDefaultConflict,
            "The default repository for '%s' is already set to %s."
            % (another.target.displayname, another.unique_name),
            another.namespace.moveRepository,
            repository,
            getUtility(ILaunchpadCelebrities).admin.teamowner,
        )

    def test_owner_default_clash_raises(self):
        # A clash between owner_default repositories will raise an exception.
        repository = self.factory.makeGitRepository()
        repository.setOwnerDefault(True)
        another = self.factory.makeGitRepository()
        another.setOwnerDefault(True)
        self.assertRaisesWithContent(
            GitDefaultConflict,
            "%s's default repository for '%s' is already set to %s."
            % (
                another.owner.displayname,
                another.target.displayname,
                another.unique_name,
            ),
            another.namespace.moveRepository,
            repository,
            getUtility(ILaunchpadCelebrities).admin.teamowner,
        )

    def test_preserves_target_default(self):
        # If there is no clash, target_default is preserved.
        repository = self.factory.makeGitRepository()
        repository.setTargetDefault(True)
        another = self.factory.makeGitRepository()
        namespace = another.namespace
        namespace.moveRepository(
            repository, getUtility(ILaunchpadCelebrities).admin.teamowner
        )
        self.assertNamespacesEqual(namespace, repository.namespace)
        repository_set = getUtility(IGitRepositorySet)
        self.assertEqual(
            repository, repository_set.getDefaultRepository(another.target)
        )

    def test_preserves_owner_default(self):
        # If there is no clash, owner_default is preserved.
        repository = self.factory.makeGitRepository()
        repository.setOwnerDefault(True)
        another = self.factory.makeGitRepository()
        namespace = another.namespace
        namespace.moveRepository(
            repository, getUtility(ILaunchpadCelebrities).admin.teamowner
        )
        self.assertNamespacesEqual(namespace, repository.namespace)
        repository_set = getUtility(IGitRepositorySet)
        self.assertEqual(
            repository,
            repository_set.getDefaultRepositoryForOwner(
                another.owner, another.target
            ),
        )

    def test_target_default_to_personal(self):
        # Moving a target_default repository to a personal namespace is
        # permitted, and the flag is cleared.
        repository = self.factory.makeGitRepository()
        repository.setTargetDefault(True)
        namespace = get_git_namespace(repository.owner, repository.owner)
        namespace.moveRepository(
            repository, getUtility(ILaunchpadCelebrities).admin.teamowner
        )
        self.assertNamespacesEqual(namespace, repository.namespace)
        self.assertFalse(repository.target_default)

    def test_owner_default_to_personal(self):
        # Moving an owner_default repository to a personal namespace is
        # permitted, and the flag is cleared.
        repository = self.factory.makeGitRepository()
        repository.setOwnerDefault(True)
        namespace = get_git_namespace(repository.owner, repository.owner)
        namespace.moveRepository(
            repository, getUtility(ILaunchpadCelebrities).admin.teamowner
        )
        self.assertNamespacesEqual(namespace, repository.namespace)
        self.assertFalse(repository.owner_default)
