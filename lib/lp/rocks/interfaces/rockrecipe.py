# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Rock recipe interfaces."""

__all__ = [
    "BadRockRecipeSource",
    "BadRockRecipeSearchContext",
    "ROCK_RECIPE_ALLOW_CREATE",
    "ROCK_RECIPE_PRIVATE_FEATURE_FLAG",
    "RockRecipeFeatureDisabled",
    "RockRecipeNotOwner",
    "RockRecipePrivacyMismatch",
    "RockRecipePrivateFeatureDisabled",
    "DuplicateRockRecipeName",
    "IRockRecipe",
    "IRockRecipeSet",
    "NoSourceForRockRecipe",
    "NoSuchRockRecipe",
]

import http.client

from lazr.restful.declarations import error_status, exported
from lazr.restful.fields import Reference, ReferenceChoice
from zope.interface import Interface
from zope.schema import Bool, Choice, Datetime, Dict, Int, List, Text, TextLine
from zope.security.interfaces import Unauthorized

from lp import _
from lp.app.enums import InformationType
from lp.app.errors import NameLookupFailed
from lp.app.interfaces.informationtype import IInformationType
from lp.app.validators.name import name_validator
from lp.app.validators.path import path_does_not_escape
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.product import IProduct
from lp.services.fields import PersonChoice, PublicPersonChoice
from lp.snappy.validators.channels import channels_validator

ROCK_RECIPE_ALLOW_CREATE = "rock.recipe.create.enabled"
ROCK_RECIPE_PRIVATE_FEATURE_FLAG = "rock.recipe.allow_private"


@error_status(http.client.UNAUTHORIZED)
class RockRecipeFeatureDisabled(Unauthorized):
    """Only certain users can create new rock recipes."""

    def __init__(self):
        super().__init__(
            "You do not have permission to create new rock recipes."
        )


@error_status(http.client.UNAUTHORIZED)
class RockRecipePrivateFeatureDisabled(Unauthorized):
    """Only certain users can create private rock recipes."""

    def __init__(self):
        super().__init__(
            "You do not have permission to create private rock recipes."
        )


@error_status(http.client.BAD_REQUEST)
class DuplicateRockRecipeName(Exception):
    """Raised for rock recipes with duplicate project/owner/name."""

    def __init__(self):
        super().__init__(
            "There is already a rock recipe with the same project, owner, "
            "and name."
        )


@error_status(http.client.UNAUTHORIZED)
class RockRecipeNotOwner(Unauthorized):
    """The registrant/requester is not the owner or a member of its team."""


class NoSuchRockRecipe(NameLookupFailed):
    """The requested rock recipe does not exist."""

    _message_prefix = "No such rock recipe with this owner and project"


@error_status(http.client.BAD_REQUEST)
class NoSourceForRockRecipe(Exception):
    """Rock recipes must have a source (Git branch)."""

    def __init__(self):
        super().__init__("New rock recipes must have a Git branch.")


@error_status(http.client.BAD_REQUEST)
class BadRockRecipeSource(Exception):
    """The elements of the source for a rock recipe are inconsistent."""


@error_status(http.client.BAD_REQUEST)
class RockRecipePrivacyMismatch(Exception):
    """Rock recipe privacy does not match its content."""

    def __init__(self, message=None):
        super().__init__(
            message
            or "Rock recipe contains private information and cannot be public."
        )


class BadRockRecipeSearchContext(Exception):
    """The context is not valid for a rock recipe search."""


class IRockRecipeView(Interface):
    """`IRockRecipe` attributes that require launchpad.View permission."""

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
        description=_("The person who registered this rock recipe."),
    )

    private = Bool(
        title=_("Private"),
        required=False,
        readonly=False,
        description=_("Whether this rock recipe is private."),
    )

    def getAllowedInformationTypes(user):
        """Get a list of acceptable `InformationType`s for this rock recipe.

        If the user is a Launchpad admin, any type is acceptable.
        """

    def visibleByUser(user):
        """Can the specified user see this rock recipe?"""


class IRockRecipeEdit(Interface):
    """`IRockRecipe` methods that require launchpad.Edit permission."""

    def destroySelf():
        """Delete this rock recipe, provided that it has no builds."""


class IRockRecipeEditableAttributes(Interface):
    """`IRockRecipe` attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    owner = exported(
        PersonChoice(
            title=_("Owner"),
            required=True,
            readonly=False,
            vocabulary="AllUserTeamsParticipationPlusSelf",
            description=_("The owner of this rock recipe."),
        )
    )

    project = ReferenceChoice(
        title=_("The project that this rock recipe is associated with"),
        schema=IProduct,
        vocabulary="Product",
        required=True,
        readonly=False,
    )

    name = TextLine(
        title=_("Rock recipe name"),
        required=True,
        readonly=False,
        constraint=name_validator,
        description=_("The name of the rock recipe."),
    )

    description = Text(
        title=_("Description"),
        required=False,
        readonly=False,
        description=_("A description of the rock recipe."),
    )

    git_repository = ReferenceChoice(
        title=_("Git repository"),
        schema=IGitRepository,
        vocabulary="GitRepository",
        required=False,
        readonly=True,
        description=_(
            "A Git repository with a branch containing a rockcraft.yaml "
            "recipe."
        ),
    )

    git_path = TextLine(
        title=_("Git branch path"),
        required=False,
        readonly=False,
        description=_(
            "The path of the Git branch containing a rockcraft.yaml recipe."
        ),
    )

    git_ref = Reference(
        IGitRef,
        title=_("Git branch"),
        required=False,
        readonly=False,
        description=_("The Git branch containing a rockcraft.yaml recipe."),
    )

    build_path = TextLine(
        title=_("Build path"),
        description=_(
            "Subdirectory within the branch containing rockcraft.yaml."
        ),
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
            "The type of information contained in this rock recipe."
        ),
    )

    auto_build = Bool(
        title=_("Automatically build when branch changes"),
        required=True,
        readonly=False,
        description=_(
            "Whether this rock recipe is built automatically when the branch "
            "containing its rockcraft.yaml recipe changes."
        ),
    )

    auto_build_channels = Dict(
        title=_("Source snap channels for automatic builds"),
        key_type=TextLine(),
        required=False,
        readonly=False,
        description=_(
            "A dictionary mapping snap names to channels to use when building "
            "this rock recipe.  Currently only 'core', 'core18', 'core20', "
            "and 'rockcraft' keys are supported."
        ),
    )

    is_stale = Bool(
        title=_("Rock recipe is stale and is due to be rebuilt."),
        required=True,
        readonly=True,
    )

    store_upload = Bool(
        title=_("Automatically upload to store"),
        required=True,
        readonly=False,
        description=_(
            "Whether builds of this rock recipe are automatically uploaded "
            "to the store."
        ),
    )

    store_name = TextLine(
        title=_("Registered store name"),
        required=False,
        readonly=False,
        description=_("The registered name of this rock in the store."),
    )

    store_secrets = List(
        value_type=TextLine(),
        title=_("Store upload tokens"),
        required=False,
        readonly=False,
        description=_(
            "Serialized secrets issued by the store and the login service to "
            "authorize uploads of this rock recipe."
        ),
    )

    store_channels = List(
        title=_("Store channels"),
        required=False,
        readonly=False,
        constraint=channels_validator,
        description=_(
            "Channels to release this rock to after uploading it to the "
            "store. A channel is defined by a combination of an optional "
            "track, a risk, and an optional branch, e.g. "
            "'2.1/stable/fix-123', '2.1/stable', 'stable/fix-123', or "
            "'stable'."
        ),
    )


class IRockRecipeAdminAttributes(Interface):
    """`IRockRecipe` attributes that can be edited by admins.

    These attributes need launchpad.View to see, and launchpad.Admin to change.
    """

    require_virtualized = Bool(
        title=_("Require virtualized builders"),
        required=True,
        readonly=False,
        description=_("Only build this rock recipe on virtual builders."),
    )


class IRockRecipe(
    IRockRecipeView,
    IRockRecipeEdit,
    IRockRecipeEditableAttributes,
    IRockRecipeAdminAttributes,
    IInformationType,
):
    """A buildable rock recipe."""


class IRockRecipeSet(Interface):
    """A utility to create and access rock recipes."""

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
        """Create an `IRockRecipe`."""

    def getByName(owner, project, name):
        """Returns the appropriate `IRockRecipe` for the given objects."""

    def isValidInformationType(information_type, owner, git_ref=None):
        """Whether the information type context is valid."""

    def findByGitRepository(repository, paths=None):
        """Return all rock recipes for the given Git repository.

        :param repository: An `IGitRepository`.
        :param paths: If not None, only return rock recipes for one of
            these Git reference paths.
        """

    def detachFromGitRepository(repository):
        """Detach all rock recipes from the given Git repository.

        After this, any rock recipes that previously used this repository
        will have no source and so cannot dispatch new builds.
        """
