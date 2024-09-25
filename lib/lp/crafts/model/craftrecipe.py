# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Craft recipes."""

__all__ = [
    "CraftRecipe",
]

from datetime import timezone

from storm.databases.postgres import JSON
from storm.locals import Bool, DateTime, Int, Reference, Unicode
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import (
    FREE_INFORMATION_TYPES,
    PUBLIC_INFORMATION_TYPES,
    InformationType,
)
from lp.code.model.gitrepository import GitRepository
from lp.code.model.reciperegistry import recipe_registry
from lp.crafts.interfaces.craftrecipe import (
    CRAFT_RECIPE_ALLOW_CREATE,
    CRAFT_RECIPE_PRIVATE_FEATURE_FLAG,
    CraftRecipeBuildRequestStatus,
    CraftRecipeFeatureDisabled,
    CraftRecipeNotOwner,
    CraftRecipePrivacyMismatch,
    CraftRecipePrivateFeatureDisabled,
    DuplicateCraftRecipeName,
    ICraftRecipe,
    ICraftRecipeBuildRequest,
    ICraftRecipeSet,
    NoSourceForCraftRecipe,
)
from lp.crafts.interfaces.craftrecipejob import (
    ICraftRecipeRequestBuildsJobSource,
)
from lp.registry.errors import PrivatePersonLinkageError
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.features import getFeatureFlag
from lp.services.job.interfaces.job import JobStatus
from lp.services.propertycache import cachedproperty, get_property_cache


def craft_recipe_modified(recipe, event):
    """Update the date_last_modified property when a craft recipe is modified.

    This method is registered as a subscriber to `IObjectModifiedEvent`
    events on craft recipes.
    """
    removeSecurityProxy(recipe).date_last_modified = UTC_NOW


@implementer(ICraftRecipe)
class CraftRecipe(StormBase):
    """See `ICraftRecipe`."""

    __storm_table__ = "CraftRecipe"

    id = Int(primary=True)

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )
    date_last_modified = DateTime(
        name="date_last_modified", tzinfo=timezone.utc, allow_none=False
    )

    registrant_id = Int(name="registrant", allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    def _validate_owner(self, attr, value):
        if not self.private:
            try:
                validate_public_person(self, attr, value)
            except PrivatePersonLinkageError:
                raise CraftRecipePrivacyMismatch(
                    "A public craft recipe cannot have a private owner."
                )
        return value

    owner_id = Int(name="owner", allow_none=False, validator=_validate_owner)
    owner = Reference(owner_id, "Person.id")

    project_id = Int(name="project", allow_none=False)
    project = Reference(project_id, "Product.id")

    name = Unicode(name="name", allow_none=False)

    description = Unicode(name="description", allow_none=True)

    def _validate_git_repository(self, attr, value):
        if not self.private and value is not None:
            if IStore(GitRepository).get(GitRepository, value).private:
                raise CraftRecipePrivacyMismatch(
                    "A public craft recipe cannot have a private repository."
                )
        return value

    git_repository_id = Int(
        name="git_repository",
        allow_none=True,
        validator=_validate_git_repository,
    )
    git_repository = Reference(git_repository_id, "GitRepository.id")

    git_path = Unicode(name="git_path", allow_none=True)

    build_path = Unicode(name="build_path", allow_none=True)

    require_virtualized = Bool(name="require_virtualized")

    def _valid_information_type(self, attr, value):
        if not getUtility(ICraftRecipeSet).isValidInformationType(
            value, self.owner, self.git_ref
        ):
            raise CraftRecipePrivacyMismatch
        return value

    information_type = DBEnum(
        enum=InformationType,
        default=InformationType.PUBLIC,
        name="information_type",
        validator=_valid_information_type,
        allow_none=False,
    )

    auto_build = Bool(name="auto_build", allow_none=False)

    auto_build_channels = JSON("auto_build_channels", allow_none=True)

    is_stale = Bool(name="is_stale", allow_none=False)

    store_upload = Bool(name="store_upload", allow_none=False)

    store_name = Unicode(name="store_name", allow_none=True)

    store_secrets = JSON("store_secrets", allow_none=True)

    _store_channels = JSON("store_channels", allow_none=True)

    def __init__(
        self,
        registrant,
        owner,
        project,
        name,
        description=None,
        git_ref=None,
        build_path=None,
        require_virtualized=True,
        information_type=InformationType.PUBLIC,
        auto_build=False,
        auto_build_channels=None,
        store_upload=False,
        store_name=None,
        store_secrets=None,
        store_channels=None,
        date_created=DEFAULT,
    ):
        """Construct a `CraftRecipe`."""
        if not getFeatureFlag(CRAFT_RECIPE_ALLOW_CREATE):
            raise CraftRecipeFeatureDisabled()
        super().__init__()

        # Set this first for use by other validators.
        self.information_type = information_type

        self.date_created = date_created
        self.date_last_modified = date_created
        self.registrant = registrant
        self.owner = owner
        self.project = project
        self.name = name
        self.description = description
        self.git_ref = git_ref
        self.build_path = build_path
        self.require_virtualized = require_virtualized
        self.auto_build = auto_build
        self.auto_build_channels = auto_build_channels
        self.store_upload = store_upload
        self.store_name = store_name
        self.store_secrets = store_secrets
        self.store_channels = store_channels

    def __repr__(self):
        return "<CraftRecipe ~%s/%s/+craft/%s>" % (
            self.owner.name,
            self.project.name,
            self.name,
        )

    @property
    def private(self):
        """See `ICraftRecipe`."""
        return self.information_type not in PUBLIC_INFORMATION_TYPES

    @property
    def git_ref(self):
        """See `ICraftRecipe`."""
        if self.git_repository is not None:
            return self.git_repository.getRefByPath(self.git_path)
        else:
            return None

    @git_ref.setter
    def git_ref(self, value):
        """See `ICraftRecipe`."""
        if value is not None:
            self.git_repository = value.repository
            self.git_path = value.path
        else:
            self.git_repository = None
            self.git_path = None

    @property
    def store_channels(self):
        """See `ICraftRecipe`."""
        return self._store_channels or []

    @store_channels.setter
    def store_channels(self, value):
        """See `ICraftRecipe`."""
        self._store_channels = value or None

    def getAllowedInformationTypes(self, user):
        """See `ICraftRecipe`."""
        # XXX ruinedyourlife 2024-09-24: Only allow free information types
        # until we have more privacy infrastructure in place.
        return FREE_INFORMATION_TYPES

    def visibleByUser(self, user):
        """See `ICraftRecipe`."""
        if self.information_type in PUBLIC_INFORMATION_TYPES:
            return True
        # XXX ruinedyourlife 2024-09-24: Finish implementing this once we have
        # more privacy infrastructure.
        return False

    def destroySelf(self):
        """See `ICraftRecipe`."""
        IStore(CraftRecipe).remove(self)

    def _checkRequestBuild(self, requester):
        """May `requester` request builds of this craft recipe?"""
        if not requester.inTeam(self.owner):
            raise CraftRecipeNotOwner(
                "%s cannot create craft recipe builds owned by %s."
                % (requester.display_name, self.owner.display_name)
            )

    def requestBuilds(self, requester, channels=None, architectures=None):
        """See `ICraftRecipe`."""
        self._checkRequestBuild(requester)
        job = getUtility(ICraftRecipeRequestBuildsJobSource).create(
            self, requester, channels=channels, architectures=architectures
        )
        return self.getBuildRequest(job.job_id)

    def getBuildRequest(self, job_id):
        """See `ICraftRecipe`."""
        return CraftRecipeBuildRequest(self, job_id)


@recipe_registry.register_recipe_type(
    ICraftRecipeSet, "Some craft recipes build from this repository."
)
@implementer(ICraftRecipeSet)
class CraftRecipeSet:
    """See `ICraftRecipeSet`."""

    def new(
        self,
        registrant,
        owner,
        project,
        name,
        description=None,
        git_ref=None,
        build_path=None,
        require_virtualized=True,
        information_type=InformationType.PUBLIC,
        auto_build=False,
        auto_build_channels=None,
        store_upload=False,
        store_name=None,
        store_secrets=None,
        store_channels=None,
        date_created=DEFAULT,
    ):
        """See `ICraftRecipeSet`."""
        if not registrant.inTeam(owner):
            if owner.is_team:
                raise CraftRecipeNotOwner(
                    "%s is not a member of %s."
                    % (registrant.displayname, owner.displayname)
                )
            else:
                raise CraftRecipeNotOwner(
                    "%s cannot create craft recipes owned by %s."
                    % (registrant.displayname, owner.displayname)
                )

        if git_ref is None:
            raise NoSourceForCraftRecipe
        if self.getByName(owner, project, name) is not None:
            raise DuplicateCraftRecipeName

        # The relevant validators will do their own checks as well, but we
        # do a single up-front check here in order to avoid an
        # IntegrityError due to exceptions being raised during object
        # creation and to ensure that everything relevant is in the Storm
        # cache.
        if not self.isValidInformationType(information_type, owner, git_ref):
            raise CraftRecipePrivacyMismatch
        store = IPrimaryStore(CraftRecipe)
        recipe = CraftRecipe(
            registrant,
            owner,
            project,
            name,
            description=description,
            git_ref=git_ref,
            build_path=build_path,
            require_virtualized=require_virtualized,
            information_type=information_type,
            auto_build=auto_build,
            auto_build_channels=auto_build_channels,
            store_upload=store_upload,
            store_name=store_name,
            store_secrets=store_secrets,
            store_channels=store_channels,
            date_created=date_created,
        )
        store.add(recipe)

        return recipe

    def getByName(self, owner, project, name):
        """See `ICraftRecipeSet`."""
        return (
            IStore(CraftRecipe)
            .find(CraftRecipe, owner=owner, project=project, name=name)
            .one()
        )

    def isValidInformationType(self, information_type, owner, git_ref=None):
        """See `ICraftRecipeSet`."""
        private = information_type not in PUBLIC_INFORMATION_TYPES
        if private:
            # If appropriately enabled via feature flag.
            if not getFeatureFlag(CRAFT_RECIPE_PRIVATE_FEATURE_FLAG):
                raise CraftRecipePrivateFeatureDisabled
            return True

        # Public craft recipes with private sources are not allowed.
        if git_ref is not None and git_ref.private:
            return False

        # Public craft recipes owned by private teams are not allowed.
        if owner is not None and owner.private:
            return False

        return True

    def findByGitRepository(self, repository, paths=None):
        """See `ICraftRecipeSet`."""
        clauses = [CraftRecipe.git_repository == repository]
        if paths is not None:
            clauses.append(CraftRecipe.git_path.is_in(paths))
        # XXX ruinedyourlife 2024-09-24: Check permissions once we have some
        # privacy infrastructure.
        return IStore(CraftRecipe).find(CraftRecipe, *clauses)

    def detachFromGitRepository(self, repository):
        """See `ICraftRecipeSet`."""
        self.findByGitRepository(repository).set(
            git_repository_id=None, git_path=None, date_last_modified=UTC_NOW
        )


@implementer(ICraftRecipeBuildRequest)
class CraftRecipeBuildRequest:
    """See `ICraftRecipeBuildRequest`.

    This is not directly backed by a database table; instead, it is a
    webservice-friendly view of an asynchronous build request.
    """

    def __init__(self, recipe, id):
        self.recipe = recipe
        self.id = id

    @classmethod
    def fromJob(cls, job):
        """See `ICraftRecipeBuildRequest`."""
        request = cls(job.recipe, job.job_id)
        get_property_cache(request)._job = job
        return request

    @cachedproperty
    def _job(self):
        job_source = getUtility(ICraftRecipeRequestBuildsJobSource)
        return job_source.getByRecipeAndID(self.recipe, self.id)

    @property
    def date_requested(self):
        """See `ICraftRecipeBuildRequest`."""
        return self._job.date_created

    @property
    def date_finished(self):
        """See `ICraftRecipeBuildRequest`."""
        return self._job.date_finished

    @property
    def status(self):
        """See `ICraftRecipeBuildRequest`."""
        status_map = {
            JobStatus.WAITING: CraftRecipeBuildRequestStatus.PENDING,
            JobStatus.RUNNING: CraftRecipeBuildRequestStatus.PENDING,
            JobStatus.COMPLETED: CraftRecipeBuildRequestStatus.COMPLETED,
            JobStatus.FAILED: CraftRecipeBuildRequestStatus.FAILED,
            JobStatus.SUSPENDED: CraftRecipeBuildRequestStatus.PENDING,
        }
        return status_map[self._job.job.status]

    @property
    def error_message(self):
        """See `ICraftRecipeBuildRequest`."""
        return self._job.error_message

    @property
    def channels(self):
        """See `ICraftRecipeBuildRequest`."""
        return self._job.channels

    @property
    def architectures(self):
        """See `ICraftRecipeBuildRequest`."""
        return self._job.architectures
