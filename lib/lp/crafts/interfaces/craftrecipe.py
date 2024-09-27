# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Craft recipe interfaces."""

__all__ = [
    "BadCraftRecipeSource",
    "BadCraftRecipeSearchContext",
    "CRAFT_RECIPE_ALLOW_CREATE",
    "CRAFT_RECIPE_PRIVATE_FEATURE_FLAG",
    "CraftRecipeBuildRequestStatus",
    "CraftRecipeFeatureDisabled",
    "CraftRecipeNotOwner",
    "CraftRecipePrivacyMismatch",
    "CraftRecipePrivateFeatureDisabled",
    "DuplicateCraftRecipeName",
    "ICraftRecipe",
    "ICraftRecipeBuildRequest",
    "ICraftRecipeSet",
    "NoSourceForCraftRecipe",
    "NoSuchCraftRecipe",
]

import http.client

from lazr.enum import EnumeratedType, Item
from lazr.restful.declarations import error_status, exported
from lazr.restful.fields import CollectionField, Reference, ReferenceChoice
from zope.interface import Interface
from zope.schema import (
    Bool,
    Choice,
    Datetime,
    Dict,
    Int,
    List,
    Set,
    Text,
    TextLine,
)
from zope.security.interfaces import Unauthorized

from lp import _
from lp.app.enums import InformationType
from lp.app.errors import NameLookupFailed
from lp.app.interfaces.informationtype import IInformationType
from lp.app.validators.name import name_validator
from lp.app.validators.path import path_does_not_escape
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import IProduct
from lp.services.fields import PersonChoice, PublicPersonChoice
from lp.snappy.validators.channels import channels_validator

CRAFT_RECIPE_ALLOW_CREATE = "craft.recipe.create.enabled"
CRAFT_RECIPE_PRIVATE_FEATURE_FLAG = "craft.recipe.allow_private"


@error_status(http.client.UNAUTHORIZED)
class CraftRecipeFeatureDisabled(Unauthorized):
    """Only certain users can create new craft recipes."""

    def __init__(self):
        super().__init__(
            "You do not have permission to create new craft recipes."
        )


@error_status(http.client.UNAUTHORIZED)
class CraftRecipePrivateFeatureDisabled(Unauthorized):
    """Only certain users can create private craft recipes."""

    def __init__(self):
        super().__init__(
            "You do not have permission to create private craft recipes."
        )


@error_status(http.client.BAD_REQUEST)
class DuplicateCraftRecipeName(Exception):
    """Raised for craft recipes with duplicate project/owner/name."""

    def __init__(self):
        super().__init__(
            "There is already a craft recipe with the same project, owner, "
            "and name."
        )


@error_status(http.client.UNAUTHORIZED)
class CraftRecipeNotOwner(Unauthorized):
    """The registrant/requester is not the owner or a member of its team."""


class NoSuchCraftRecipe(NameLookupFailed):
    """The requested craft recipe does not exist."""

    _message_prefix = "No such craft recipe with this owner and project"


@error_status(http.client.BAD_REQUEST)
class NoSourceForCraftRecipe(Exception):
    """Craft recipes must have a source (Git branch)."""

    def __init__(self):
        super().__init__("New craft recipes must have a Git branch.")


@error_status(http.client.BAD_REQUEST)
class BadCraftRecipeSource(Exception):
    """The elements of the source for a craft recipe are inconsistent."""


@error_status(http.client.BAD_REQUEST)
class CraftRecipePrivacyMismatch(Exception):
    """Craft recipe privacy does not match its content."""

    def __init__(self, message=None):
        super().__init__(
            message
            or "Craft recipe contains private information and cannot be "
            "public."
        )


class BadCraftRecipeSearchContext(Exception):
    """The context is not valid for a craft recipe search."""


class CraftRecipeBuildRequestStatus(EnumeratedType):
    """The status of a request to build a craft recipe."""

    PENDING = Item(
        """
        Pending

        This craft recipe build request is pending.
        """
    )

    FAILED = Item(
        """
        Failed

        This craft recipe build request failed.
        """
    )

    COMPLETED = Item(
        """
        Completed

        This craft recipe build request completed successfully.
        """
    )


class ICraftRecipeBuildRequest(Interface):
    """A request to build a craft recipe."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_requested = Datetime(
        title=_("The time when this request was made"),
        required=True,
        readonly=True,
    )

    date_finished = Datetime(
        title=_("The time when this request finished"),
        required=False,
        readonly=True,
    )

    recipe = Reference(
        # Really ICraftRecipe.
        Interface,
        title=_("Craft recipe"),
        required=True,
        readonly=True,
    )

    status = Choice(
        title=_("Status"),
        vocabulary=CraftRecipeBuildRequestStatus,
        required=True,
        readonly=True,
    )

    error_message = TextLine(
        title=_("Error message"), required=True, readonly=True
    )

    channels = Dict(
        title=_("Source snap channels for builds produced by this request"),
        key_type=TextLine(),
        required=False,
        readonly=True,
    )

    architectures = Set(
        title=_("If set, this request is limited to these architecture tags"),
        value_type=TextLine(),
        required=False,
        readonly=True,
    )

    builds = CollectionField(
        title=_("Builds produced by this request"),
        # Really ICraftRecipeBuild.
        value_type=Reference(schema=Interface),
        required=True,
        readonly=True,
    )

    requester = Reference(
        title=_("The person requesting the builds."),
        schema=IPerson,
        required=True,
        readonly=True,
    )


class ICraftRecipeView(Interface):
    """`ICraftRecipe` attributes that require launchpad.View permission."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_created = Datetime(
        title=_("Date created"), required=True, readonly=True
    )
    date_last_modified = Datetime(
        title=_("Date last modified"), required=True, readonly=True
    )

    registrant = PublicPersonChoice(
        title=_("Registrant"),
        required=True,
        readonly=True,
        vocabulary="ValidPersonOrTeam",
        description=_("The person who registered this craft recipe."),
    )

    private = Bool(
        title=_("Private"),
        required=False,
        readonly=False,
        description=_("Whether this craft recipe is private."),
    )

    def getAllowedInformationTypes(user):
        """Get a list of acceptable `InformationType`s for this craft recipe.

        If the user is a Launchpad admin, any type is acceptable.
        """

    def visibleByUser(user):
        """Can the specified user see this craft recipe?"""

    def requestBuilds(requester, channels=None, architectures=None):
        """Request that the craft recipe be built.

        This is an asynchronous operation; once the operation has finished,
        the resulting build request's C{status} will be "Completed" and its
        C{builds} collection will return the resulting builds.

        :param requester: The person requesting the builds.
        :param channels: A dictionary mapping snap names to channels to use
            for these builds.
        :param architectures: If not None, limit builds to architectures
            with these architecture tags (in addition to any other
            applicable constraints).
        :return: An `ICraftRecipeBuildRequest`.
        """

    def getBuildRequest(job_id):
        """Get an asynchronous build request by ID.

        :param job_id: The ID of the build request.
        :return: `ICraftRecipeBuildRequest`.
        """


class ICraftRecipeEdit(Interface):
    """`ICraftRecipe` methods that require launchpad.Edit permission."""

    def destroySelf():
        """Delete this craft recipe, provided that it has no builds."""


class ICraftRecipeEditableAttributes(Interface):
    """`ICraftRecipe` attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    owner = exported(
        PersonChoice(
            title=_("Owner"),
            required=True,
            readonly=False,
            vocabulary="AllUserTeamsParticipationPlusSelf",
            description=_("The owner of this craft recipe."),
        )
    )

    project = ReferenceChoice(
        title=_("The project that this craft recipe is associated with"),
        schema=IProduct,
        vocabulary="Product",
        required=True,
        readonly=False,
    )

    name = TextLine(
        title=_("Craft recipe name"),
        required=True,
        readonly=False,
        constraint=name_validator,
        description=_("The name of the craft recipe."),
    )

    description = Text(
        title=_("Description"),
        required=False,
        readonly=False,
        description=_("A description of the craft recipe."),
    )

    git_repository = ReferenceChoice(
        title=_("Git repository"),
        schema=IGitRepository,
        vocabulary="GitRepository",
        required=False,
        readonly=True,
        description=_(
            "A Git repository with a branch containing a craft.yaml recipe."
        ),
    )

    git_path = TextLine(
        title=_("Git branch path"),
        required=False,
        readonly=False,
        description=_(
            "The path of the Git branch containing a craft.yaml recipe."
        ),
    )

    git_ref = Reference(
        IGitRef,
        title=_("Git branch"),
        required=False,
        readonly=False,
        description=_("The Git branch containing a craft.yaml recipe."),
    )

    build_path = TextLine(
        title=_("Build path"),
        description=_("Subdirectory within the branch containing craft.yaml."),
        constraint=path_does_not_escape,
        required=False,
        readonly=False,
    )
    information_type = Choice(
        title=_("Information type"),
        vocabulary=InformationType,
        required=True,
        readonly=False,
        default=InformationType.PUBLIC,
        description=_(
            "The type of information contained in this craft recipe."
        ),
    )

    auto_build = Bool(
        title=_("Automatically build when branch changes"),
        required=True,
        readonly=False,
        description=_(
            "Whether this craft recipe is built automatically when the branch "
            "containing its craft.yaml recipe changes."
        ),
    )

    auto_build_channels = Dict(
        title=_("Source snap channels for automatic builds"),
        key_type=TextLine(),
        required=False,
        readonly=False,
        description=_(
            "A dictionary mapping snap names to channels to use when building "
            "this craft recipe.  Currently only 'core', 'core18', 'core20', "
            "and 'craft' keys are supported."
        ),
    )

    is_stale = Bool(
        title=_("Craft recipe is stale and is due to be rebuilt."),
        required=True,
        readonly=True,
    )

    store_upload = Bool(
        title=_("Automatically upload to store"),
        required=True,
        readonly=False,
        description=_(
            "Whether builds of this craft recipe are automatically uploaded "
            "to the store."
        ),
    )

    store_name = TextLine(
        title=_("Registered store name"),
        required=False,
        readonly=False,
        description=_("The registered name of this craft in the store."),
    )

    store_secrets = List(
        value_type=TextLine(),
        title=_("Store upload tokens"),
        required=False,
        readonly=False,
        description=_(
            "Serialized secrets issued by the store and the login service to "
            "authorize uploads of this craft recipe."
        ),
    )

    store_channels = List(
        title=_("Store channels"),
        required=False,
        readonly=False,
        constraint=channels_validator,
        description=_(
            "Channels to release this craft to after uploading it to the "
            "store. A channel is defined by a combination of an optional "
            "track, a risk, and an optional branch, e.g. "
            "'2.1/stable/fix-123', '2.1/stable', 'stable/fix-123', or "
            "'stable'."
        ),
    )


class ICraftRecipeAdminAttributes(Interface):
    """`ICraftRecipe` attributes that can be edited by admins.

    These attributes need launchpad.View to see, and launchpad.Admin to change.
    """

    require_virtualized = Bool(
        title=_("Require virtualized builders"),
        required=True,
        readonly=False,
        description=_("Only build this craft recipe on virtual builders."),
    )


class ICraftRecipe(
    ICraftRecipeView,
    ICraftRecipeEdit,
    ICraftRecipeEditableAttributes,
    ICraftRecipeAdminAttributes,
    IInformationType,
):
    """A buildable craft recipe."""


class ICraftRecipeSet(Interface):
    """A utility to create and access craft recipes."""

    def new(
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
        date_created=None,
    ):
        """Create an `ICraftRecipe`."""

    def getByName(owner, project, name):
        """Returns the appropriate `ICraftRecipe` for the given objects."""

    def isValidInformationType(information_type, owner, git_ref=None):
        """Whether the information type context is valid."""

    def findByGitRepository(repository, paths=None):
        """Return all craft recipes for the given Git repository.

        :param repository: An `IGitRepository`.
        :param paths: If not None, only return craft recipes for one of
            these Git reference paths.
        """

    def detachFromGitRepository(repository):
        """Detach all craft recipes from the given Git repository.

        After this, any craft recipes that previously used this repository
        will have no source and so cannot dispatch new builds.
        """

    def preloadDataForRecipes(recipes, user):
        """Load the data related to a list of craft recipes."""
