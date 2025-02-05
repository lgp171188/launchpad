# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementations of `IGitNamespace`."""

__all__ = [
    "GitNamespaceSet",
    "OCIProjectGitNamespace",
    "PackageGitNamespace",
    "PersonalGitNamespace",
    "ProjectGitNamespace",
]

import six
import transaction
from lazr.lifecycle.event import ObjectCreatedEvent
from storm.locals import And
from zope.component import getUtility
from zope.event import notify
from zope.interface import implementer
from zope.security.proxy import isinstance as zope_isinstance
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import (
    FREE_INFORMATION_TYPES,
    NON_EMBARGOED_INFORMATION_TYPES,
    PUBLIC_INFORMATION_TYPES,
    InformationType,
)
from lp.app.interfaces.services import IService
from lp.code.enums import (
    BranchSubscriptionDiffSize,
    BranchSubscriptionNotificationLevel,
    CodeReviewNotificationLevel,
    GitRepositoryStatus,
)
from lp.code.errors import (
    GitDefaultConflict,
    GitRepositoryCreationForbidden,
    GitRepositoryCreatorNotMemberOfOwnerTeam,
    GitRepositoryCreatorNotOwner,
    GitRepositoryExists,
)
from lp.code.interfaces.gitcollection import IAllGitRepositories
from lp.code.interfaces.gitnamespace import (
    IGitNamespace,
    IGitNamespacePolicy,
    IGitNamespaceSet,
)
from lp.code.interfaces.gitrepository import (
    IGitRepository,
    IGitRepositorySet,
    user_has_special_git_repository_access,
)
from lp.code.interfaces.hasgitrepositories import IHasGitRepositories
from lp.code.model.branchnamespace import (
    BRANCH_POLICY_ALLOWED_TYPES,
    BRANCH_POLICY_DEFAULT_TYPES,
    BRANCH_POLICY_REQUIRED_GRANTS,
)
from lp.code.model.gitrepository import GitRepository
from lp.registry.enums import PersonVisibility
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.services.database.constants import DEFAULT
from lp.services.database.interfaces import IStore
from lp.services.propertycache import get_property_cache


class _BaseGitNamespace:
    """Common code for Git repository namespaces."""

    def createRepository(
        self,
        repository_type,
        registrant,
        name,
        reviewer=None,
        information_type=None,
        date_created=DEFAULT,
        description=None,
        target_default=False,
        owner_default=False,
        with_hosting=False,
        async_hosting=False,
        status=GitRepositoryStatus.AVAILABLE,
        clone_from_repository=None,
        builder_constraints=None,
    ):
        """See `IGitNamespace`."""
        repository_set = getUtility(IGitRepositorySet)

        self.validateRegistrant(registrant)
        self.validateRepositoryName(name)

        if information_type is None:
            information_type = self.getDefaultInformationType(registrant)
            if information_type is None:
                raise GitRepositoryCreationForbidden()

        repository = GitRepository(
            repository_type,
            registrant,
            self.owner,
            self.target,
            name,
            information_type,
            date_created,
            reviewer=reviewer,
            description=description,
            status=status,
            builder_constraints=builder_constraints,
        )
        repository._reconcileAccess()

        # The owner of the repository should also be automatically subscribed
        # in order for them to get code review notifications.  The default
        # owner subscription does not cause email to be sent about attribute
        # changes, just merge proposals and code review comments.
        repository.subscribe(
            self.owner,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            BranchSubscriptionDiffSize.NODIFF,
            CodeReviewNotificationLevel.FULL,
            registrant,
        )

        notify(ObjectCreatedEvent(repository))

        if target_default:
            repository_set.setDefaultRepository(self.target, repository)
        if owner_default:
            repository_set.setDefaultRepositoryForOwner(
                self.owner, self.target, repository, registrant
            )

        if with_hosting:
            # Ask the hosting service to create the repository on disk.  Do
            # this as late as possible, since if this succeeds it can't
            # easily be rolled back with the rest of the transaction.

            # Flush to make sure that repository.id is populated.
            IStore(repository).flush()
            if async_hosting:
                # If we are going to run async creation, we need to be sure
                # the transaction is committed.
                # Async creation will run a callback on Launchpad, and if
                # the creation is quick enough, it might try to confirm on
                # Launchpad (in another transaction) the creation of this
                # repo before this transaction is actually committed.
                transaction.commit()
            assert repository.id is not None

            if clone_from_repository is None:
                clone_from_repository = repository.getClonedFrom()
            repository._createOnHostingService(
                clone_from_repository=clone_from_repository,
                async_create=async_hosting,
            )

        return repository

    def isNameUsed(self, repository_name):
        """See `IGitNamespace`."""
        return self.getByName(repository_name) is not None

    def findUnusedName(self, prefix):
        """See `IGitNamespace`."""
        name = prefix
        count = 0
        while self.isNameUsed(name):
            count += 1
            name = "%s-%s" % (prefix, count)
        return name

    def validateRegistrant(self, registrant, repository=None):
        """See `IGitNamespace`."""
        if user_has_special_git_repository_access(registrant, repository):
            return
        owner = self.owner
        if not registrant.inTeam(owner):
            if owner.is_team:
                raise GitRepositoryCreatorNotMemberOfOwnerTeam(
                    registrant, owner
                )
            else:
                raise GitRepositoryCreatorNotOwner(registrant, owner)

        if not self.getAllowedInformationTypes(registrant):
            raise GitRepositoryCreationForbidden(
                'You cannot create Git repositories in "%s" (context: %s)'
                % (self.name, self.__class__.__name__)
            )

    def validateRepositoryName(self, name):
        """See `IGitNamespace`."""
        # Not all code paths that lead to Git repository creation go via a
        # schema-validated form, so we validate the repository name here to
        # give a nicer error message than 'ERROR: new row for relation
        # "gitrepository" violates check constraint "valid_name"...'.
        IGitRepository["name"].validate(six.ensure_text(name))

        existing_repository = self.getByName(name)
        if existing_repository is not None:
            raise GitRepositoryExists(existing_repository)

    def validateDefaultFlags(self, repository):
        """See `IGitNamespace`."""
        repository_set = getUtility(IGitRepositorySet)
        if (
            repository.target_default
            and self.has_defaults
            and self.target != repository.target
        ):
            existing = repository_set.getDefaultRepository(self.target)
            if existing is not None:
                raise GitDefaultConflict(existing, self.target)
        if (
            repository.owner_default
            and self.has_defaults
            and (
                self.owner != repository.owner
                or self.target != repository.target
            )
        ):
            existing = repository_set.getDefaultRepositoryForOwner(
                self.owner, self.target
            )
            if existing is not None:
                raise GitDefaultConflict(
                    existing, self.target, owner=self.owner
                )

    def validateMove(self, repository, mover, name=None):
        """See `IGitNamespace`."""
        if name is None:
            name = repository.name
        self.validateRepositoryName(name)
        self.validateRegistrant(mover, repository)
        self.validateDefaultFlags(repository)

    def moveRepository(
        self, repository, mover, new_name=None, rename_if_necessary=False
    ):
        """See `IGitNamespace`."""
        # Check to see if the repository is already in this namespace with
        # this name.
        old_namespace = repository.namespace
        if self.name == old_namespace.name and new_name is None:
            return
        if new_name is None:
            new_name = repository.name
        if rename_if_necessary:
            new_name = self.findUnusedName(new_name)
        self.validateMove(repository, mover, new_name)
        # Remove the security proxy of the repository as the owner and
        # target attributes are read-only through the interface.
        naked_repository = removeSecurityProxy(repository)
        if self.owner != repository.owner:
            naked_repository.owner = self.owner
        if self.target != repository.target:
            self._retargetRepository(naked_repository)
            del get_property_cache(naked_repository).target
        if new_name != repository.name:
            naked_repository.name = new_name

    def getRepositories(self):
        """See `IGitNamespace`."""
        return IStore(GitRepository).find(
            GitRepository, self._getRepositoriesClause()
        )

    def getByName(self, repository_name, default=None):
        """See `IGitNamespace`."""
        match = (
            IStore(GitRepository)
            .find(
                GitRepository,
                self._getRepositoriesClause(),
                GitRepository.name == repository_name,
            )
            .one()
        )
        if match is None:
            match = default
        return match

    def canCreateRepositories(self, user):
        """See `IGitNamespacePolicy`."""
        try:
            self.validateRegistrant(user)
        except GitRepositoryCreatorNotMemberOfOwnerTeam:
            return False
        except GitRepositoryCreatorNotOwner:
            return False
        except GitRepositoryCreationForbidden:
            return False
        else:
            return True

    def getAllowedInformationTypes(self, who=None):
        """See `IGitNamespace`."""
        raise NotImplementedError

    def getDefaultInformationType(self, who=None):
        """See `IGitNamespace`."""
        raise NotImplementedError

    def __eq__(self, other):
        """See `IGitNamespace`."""
        return self.target == other.target

    def __ne__(self, other):
        """See `IGitNamespace`."""
        return not self == other


@implementer(IGitNamespace, IGitNamespacePolicy)
class PersonalGitNamespace(_BaseGitNamespace):
    """A namespace for personal repositories.

    Repositories in this namespace have names like "~foo/+git/bar".
    """

    has_defaults = False
    allow_push_to_set_default = False
    default_owner = None
    supports_merge_proposals = True
    supports_code_imports = False
    allow_recipe_name_from_target = False
    supports_repository_forking = False

    def __init__(self, person):
        self.owner = person

    def _getRepositoriesClause(self):
        return And(
            GitRepository.owner == self.owner,
            GitRepository.project == None,
            GitRepository.distribution == None,
            GitRepository.sourcepackagename == None,
            GitRepository.oci_project == None,
        )

    # Marker for references to Git URL layouts: ##GITNAMESPACE##
    @property
    def name(self):
        """See `IGitNamespace`."""
        return "~%s" % self.owner.name

    @property
    def target(self):
        """See `IGitNamespace`."""
        return IHasGitRepositories(self.owner)

    def _retargetRepository(self, repository):
        repository.project = None
        repository.distribution = None
        repository.sourcepackagename = None
        repository.oci_project = None
        repository.target_default = False
        repository.owner_default = False

    @property
    def _is_private_team(self):
        return (
            self.owner.is_team
            and self.owner.visibility == PersonVisibility.PRIVATE
        )

    def getAllowedInformationTypes(self, who=None):
        """See `IGitNamespace`."""
        # Private teams get private branches, everyone else gets public ones.
        if self._is_private_team:
            return NON_EMBARGOED_INFORMATION_TYPES
        else:
            return FREE_INFORMATION_TYPES

    def getDefaultInformationType(self, who=None):
        """See `IGitNamespace`."""
        if self._is_private_team:
            return InformationType.PROPRIETARY
        else:
            return InformationType.PUBLIC

    def areRepositoriesMergeable(self, this, other):
        """See `IGitNamespacePolicy`."""
        if this.namespace != self:
            raise AssertionError(
                "Namespace of %s is not %s." % (this.unique_name, self.name)
            )
        return this.name == other.name

    @property
    def collection(self):
        """See `IGitNamespacePolicy`."""
        return getUtility(IAllGitRepositories).ownedBy(self.owner).isPersonal()

    def assignKarma(self, person, action_name, date_created=None):
        """See `IGitNamespacePolicy`."""
        # Does nothing.  No karma for personal repositories.
        return None


@implementer(IGitNamespace, IGitNamespacePolicy)
class ProjectGitNamespace(_BaseGitNamespace):
    """A namespace for project repositories.

    This namespace is for all the repositories owned by a particular person
    in a particular project.
    """

    has_defaults = True
    allow_push_to_set_default = True
    supports_merge_proposals = True
    supports_code_imports = True
    allow_recipe_name_from_target = True
    supports_repository_forking = True

    def __init__(self, person, project):
        self.owner = person
        self.project = project

    def _getRepositoriesClause(self):
        return And(
            GitRepository.owner == self.owner,
            GitRepository.project == self.project,
        )

    # Marker for references to Git URL layouts: ##GITNAMESPACE##
    @property
    def name(self):
        """See `IGitNamespace`."""
        return "~%s/%s" % (self.owner.name, self.project.name)

    @property
    def target(self):
        """See `IGitNamespace`."""
        return IHasGitRepositories(self.project)

    def _retargetRepository(self, repository):
        repository.project = self.project
        repository.distribution = None
        repository.sourcepackagename = None
        repository.oci_project = None

    @property
    def default_owner(self):
        """See `IGitNamespacePolicy`."""
        return self.target.owner

    def getAllowedInformationTypes(self, who=None):
        """See `IGitNamespace`."""
        # Some policies require that the repository owner or current user
        # have full access to an information type.  If it's required and the
        # user doesn't hold it, no information types are legal.
        required_grant = BRANCH_POLICY_REQUIRED_GRANTS[
            self.project.branch_sharing_policy
        ]
        if (
            required_grant is not None
            and not getUtility(IService, "sharing").checkPillarAccess(
                [self.project], required_grant, self.owner
            )
            and (
                who is None
                or not getUtility(IService, "sharing").checkPillarAccess(
                    [self.project], required_grant, who
                )
            )
        ):
            return []

        return BRANCH_POLICY_ALLOWED_TYPES[self.project.branch_sharing_policy]

    def getDefaultInformationType(self, who=None):
        """See `IGitNamespace`."""
        default_type = BRANCH_POLICY_DEFAULT_TYPES[
            self.project.branch_sharing_policy
        ]
        if default_type not in self.getAllowedInformationTypes(who):
            return None
        return default_type

    def areRepositoriesMergeable(self, this, other):
        """See `IGitNamespacePolicy`."""
        # Repositories are mergeable into a project repository if the
        # project is the same.
        # XXX cjwatson 2015-04-18: Allow merging from a package repository
        # if any (active?) series is linked to this project.
        if this.namespace != self:
            raise AssertionError(
                "Namespace of %s is not %s." % (this.unique_name, self.name)
            )
        other_namespace = other.namespace
        if zope_isinstance(other_namespace, ProjectGitNamespace):
            return self.target == other_namespace.target
        else:
            return False

    @property
    def collection(self):
        """See `IGitNamespacePolicy`."""
        return getUtility(IAllGitRepositories).inProject(self.project)

    def assignKarma(self, person, action_name, date_created=None):
        """See `IGitNamespacePolicy`."""
        return person.assignKarma(
            action_name, product=self.project, datecreated=date_created
        )


@implementer(IGitNamespace, IGitNamespacePolicy)
class PackageGitNamespace(_BaseGitNamespace):
    """A namespace for distribution source package repositories.

    This namespace is for all the repositories owned by a particular person
    in a particular source package in a particular distribution.
    """

    has_defaults = True
    allow_push_to_set_default = False
    supports_merge_proposals = True
    supports_code_imports = True
    allow_recipe_name_from_target = True
    supports_repository_forking = True

    def __init__(self, person, distro_source_package):
        self.owner = person
        self.distro_source_package = distro_source_package

    def _getRepositoriesClause(self):
        dsp = self.distro_source_package
        return And(
            GitRepository.owner == self.owner,
            GitRepository.distribution == dsp.distribution,
            GitRepository.sourcepackagename == dsp.sourcepackagename,
        )

    # Marker for references to Git URL layouts: ##GITNAMESPACE##
    @property
    def name(self):
        """See `IGitNamespace`."""
        dsp = self.distro_source_package
        return "~%s/%s/+source/%s" % (
            self.owner.name,
            dsp.distribution.name,
            dsp.sourcepackagename.name,
        )

    @property
    def target(self):
        """See `IGitNamespace`."""
        return IHasGitRepositories(self.distro_source_package)

    def _retargetRepository(self, repository):
        dsp = self.distro_source_package
        repository.project = None
        repository.distribution = dsp.distribution
        repository.sourcepackagename = dsp.sourcepackagename
        repository.oci_project = None

    @property
    def default_owner(self):
        """See `IGitNamespacePolicy`."""
        return self.target.owner

    def getAllowedInformationTypes(self, who=None):
        """See `IGitNamespace`."""
        # Some policies require that the repository owner or current user
        # have full access to an information type.  If it's required and the
        # user doesn't hold it, no information types are legal.
        distribution = self.distro_source_package.distribution
        required_grant = BRANCH_POLICY_REQUIRED_GRANTS[
            distribution.branch_sharing_policy
        ]
        if (
            required_grant is not None
            and not getUtility(IService, "sharing").checkPillarAccess(
                [distribution], required_grant, self.owner
            )
            and (
                who is None
                or not getUtility(IService, "sharing").checkPillarAccess(
                    [distribution], required_grant, who
                )
            )
        ):
            return []

        return BRANCH_POLICY_ALLOWED_TYPES[distribution.branch_sharing_policy]

    def getDefaultInformationType(self, who=None):
        """See `IGitNamespace`."""
        default_type = BRANCH_POLICY_DEFAULT_TYPES[
            self.distro_source_package.distribution.branch_sharing_policy
        ]
        if default_type not in self.getAllowedInformationTypes(who):
            return None
        return default_type

    def areRepositoriesMergeable(self, this, other):
        """See `IGitNamespacePolicy`."""
        # Repositories are mergeable into a package repository if the
        # package is the same.
        # XXX cjwatson 2015-04-18: Allow merging from a project repository
        # if any (active?) series links this package to that project.
        if this.namespace != self:
            raise AssertionError(
                "Namespace of %s is not %s." % (this.unique_name, self.name)
            )
        other_namespace = other.namespace
        if zope_isinstance(other_namespace, PackageGitNamespace):
            return self.target == other_namespace.target
        else:
            return False

    @property
    def collection(self):
        """See `IGitNamespacePolicy`."""
        return getUtility(IAllGitRepositories).inDistributionSourcePackage(
            self.distro_source_package
        )

    def assignKarma(self, person, action_name, date_created=None):
        """See `IGitNamespacePolicy`."""
        dsp = self.distro_source_package
        return person.assignKarma(
            action_name,
            distribution=dsp.distribution,
            sourcepackagename=dsp.sourcepackagename,
            datecreated=date_created,
        )

    def __eq__(self, other):
        """See `IGitNamespace`."""
        # We may have different DSP objects that are functionally the same.
        self_dsp = self.distro_source_package
        other_dsp = IDistributionSourcePackage(other.target)
        return (
            self_dsp.distribution == other_dsp.distribution
            and self_dsp.sourcepackagename == other_dsp.sourcepackagename
        )


@implementer(IGitNamespace, IGitNamespacePolicy)
class OCIProjectGitNamespace(_BaseGitNamespace):
    """A namespace for OCI Project repositories.

    This namespace is for all the repositories owned by a particular person
    in a particular OCI Project in a particular pillar.
    """

    has_defaults = True
    allow_push_to_set_default = True
    supports_merge_proposals = True
    supports_code_imports = True
    allow_recipe_name_from_target = True
    supports_repository_forking = False

    def __init__(self, person, oci_project):
        self.owner = person
        self.oci_project = oci_project

    def _getRepositoriesClause(self):
        return And(
            GitRepository.owner == self.owner,
            GitRepository.oci_project == self.oci_project,
        )

    # Marker for references to Git URL layouts: ##GITNAMESPACE##
    @property
    def name(self):
        """See `IGitNamespace`."""
        ocip = self.oci_project
        return "~%s/%s/+oci/%s" % (
            self.owner.name,
            ocip.pillar.name,
            ocip.name,
        )

    @property
    def target(self):
        """See `IGitNamespace`."""
        return IHasGitRepositories(self.oci_project)

    def _retargetRepository(self, repository):
        repository.project = None
        repository.distribution = None
        repository.sourcepackagename = None
        repository.oci_project = self.oci_project

    @property
    def default_owner(self):
        """See `IGitNamespacePolicy`."""
        # XXX cjwatson 2021-04-26: This may be a bit too restrictive, since
        # other users may be able to edit the OCI project.  If this becomes
        # a problem, it will probably be best to fix it by extending the set
        # of people who have launchpad.Edit on repositories in OCI project
        # namespaces.
        if IDistribution.providedBy(self.target.pillar):
            return self.target.pillar.oci_project_admin
        else:
            return self.target.pillar.owner

    def getAllowedInformationTypes(self, who=None):
        """See `IGitNamespace`."""
        return PUBLIC_INFORMATION_TYPES

    def getDefaultInformationType(self, who=None):
        """See `IGitNamespace`."""
        return InformationType.PUBLIC

    def areRepositoriesMergeable(self, this, other):
        """See `IGitNamespacePolicy`."""
        # Repositories are mergeable into an OCI Project repository if the
        # OCI Project is the same.
        # XXX cjwatson 2015-04-18: Allow merging from a project repository
        # if any (active?) series links this OCI Project to that project.
        if this.namespace != self:
            raise AssertionError(
                "Namespace of %s is not %s." % (this.unique_name, self.name)
            )
        other_namespace = other.namespace
        if zope_isinstance(other_namespace, OCIProjectGitNamespace):
            return self.target == other_namespace.target
        else:
            return False

    @property
    def collection(self):
        """See `IGitNamespacePolicy`."""
        return getUtility(IAllGitRepositories).inOCIProject(self.oci_project)

    def assignKarma(self, person, action_name, date_created=None):
        """See `IGitNamespacePolicy`."""
        # Does nothing. Currently no karma for OCI Project Namespaces.
        return None


@implementer(IGitNamespaceSet)
class GitNamespaceSet:
    """Only implementation of `IGitNamespaceSet`."""

    def get(
        self,
        person,
        project=None,
        distribution=None,
        sourcepackagename=None,
        oci_project=None,
    ):
        """See `IGitNamespaceSet`."""
        # XXX cjwatson 2019-11-25: This will eventually need project-based
        # OCIProject support.
        if project is not None:
            assert (
                distribution is None
                and sourcepackagename is None
                and oci_project is None
            ), (
                "project implies no distribution, sourcepackagename"
                " or oci_project. "
                "Got %r, %r, %r, %r."
                % (project, distribution, sourcepackagename, oci_project)
            )
            return ProjectGitNamespace(person, project)
        elif distribution is not None:
            assert (
                sourcepackagename is not None
            ), "sourcepackagename must be set. Got %r." % (sourcepackagename)
            return PackageGitNamespace(
                person, distribution.getSourcePackage(sourcepackagename)
            )
        elif oci_project is not None:
            return OCIProjectGitNamespace(person, oci_project)
        else:
            return PersonalGitNamespace(person)
