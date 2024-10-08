# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Craft recipe interfaces."""

__all__ = [
    "BadCraftRecipeSource",
    "BadCraftRecipeSearchContext",
    "CannotFetchSourcecraftYaml",
    "CannotParseSourcecraftYaml",
    "CRAFT_RECIPE_ALLOW_CREATE",
    "CRAFT_RECIPE_PRIVATE_FEATURE_FLAG",
    "CraftRecipeBuildAlreadyPending",
    "CraftRecipeBuildDisallowedArchitecture",
    "CraftRecipeBuildRequestStatus",
    "CraftRecipeFeatureDisabled",
    "CraftRecipeNotOwner",
    "CraftRecipePrivacyMismatch",
    "CraftRecipePrivateFeatureDisabled",
    "DuplicateCraftRecipeName",
    "ICraftRecipe",
    "ICraftRecipeBuildRequest",
    "ICraftRecipeSet",
    "ICraftRecipeView",
    "MissingSourcecraftYaml",
    "NoSourceForCraftRecipe",
    "NoSuchCraftRecipe",
]

import http.client

from lazr.enum import EnumeratedType, Item
from lazr.lifecycle.snapshot import doNotSnapshot
from lazr.restful.declarations import (
    REQUEST_USER,
    call_with,
    collection_default_content,
    error_status,
    export_destructor_operation,
    export_factory_operation,
    export_read_operation,
    exported,
    exported_as_webservice_collection,
    exported_as_webservice_entry,
    operation_for_version,
    operation_parameters,
    operation_returns_collection_of,
    operation_returns_entry,
)
from lazr.restful.fields import CollectionField, Reference, ReferenceChoice
from lazr.restful.interface import copy_field
from zope.interface import Attribute, Interface
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
from lp.buildmaster.interfaces.processor import IProcessor
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import IProduct
from lp.services.fields import PersonChoice, PublicPersonChoice, URIField
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


class MissingSourcecraftYaml(Exception):
    """The repository for this craft recipe does not have a
    sourcecraft.yaml.
    """

    def __init__(self, branch_name):
        super().__init__("Cannot find sourcecraft.yaml in %s" % branch_name)


class CannotFetchSourcecraftYaml(Exception):
    """Launchpad cannot fetch this craft recipe's sourcecraft.yaml."""


class CannotParseSourcecraftYaml(Exception):
    """Launchpad cannot parse this craft recipe's sourcecraft.yaml."""


@error_status(http.client.BAD_REQUEST)
class CraftRecipeBuildAlreadyPending(Exception):
    """A build was requested when an identical build was already pending."""

    def __init__(self):
        super().__init__(
            "An identical build of this craft recipe is already pending."
        )


@error_status(http.client.BAD_REQUEST)
class CraftRecipeBuildDisallowedArchitecture(Exception):
    """A build was requested for a disallowed architecture."""

    def __init__(self, das):
        super().__init__(
            "This craft recipe is not allowed to build for %s/%s."
            % (das.distroseries.name, das.architecturetag)
        )


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


# XXX ruinedyourlife 2024-10-02
# https://bugs.launchpad.net/lazr.restful/+bug/760849:
# "beta" is a lie to get WADL generation working.
# Individual attributes must set their version to "devel".
@exported_as_webservice_entry(as_of="beta")
class ICraftRecipeBuildRequest(Interface):
    """A request to build a craft recipe."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_requested = exported(
        Datetime(
            title=_("The time when this request was made"),
            required=True,
            readonly=True,
        )
    )

    date_finished = exported(
        Datetime(
            title=_("The time when this request finished"),
            required=False,
            readonly=True,
        )
    )

    recipe = exported(
        Reference(
            # Really ICraftRecipe.
            Interface,
            title=_("Craft recipe"),
            required=True,
            readonly=True,
        )
    )

    status = exported(
        Choice(
            title=_("Status"),
            vocabulary=CraftRecipeBuildRequestStatus,
            required=True,
            readonly=True,
        )
    )

    error_message = exported(
        TextLine(title=_("Error message"), required=True, readonly=True)
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

    builds = exported(
        CollectionField(
            title=_("Builds produced by this request"),
            # Really ICraftRecipeBuild.
            value_type=Reference(schema=Interface),
            required=True,
            readonly=True,
        )
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

    date_created = exported(
        Datetime(title=_("Date created"), required=True, readonly=True)
    )
    date_last_modified = exported(
        Datetime(title=_("Date last modified"), required=True, readonly=True)
    )

    registrant = exported(
        PublicPersonChoice(
            title=_("Registrant"),
            required=True,
            readonly=True,
            vocabulary="ValidPersonOrTeam",
            description=_("The person who registered this craft recipe."),
        )
    )

    source = Attribute("The source branch for this craft recipe.")

    private = exported(
        Bool(
            title=_("Private"),
            required=False,
            readonly=False,
            description=_("Whether this craft recipe is private."),
        )
    )

    can_upload_to_store = exported(
        Bool(
            title=_("Can upload to the CraftStore"),
            required=True,
            readonly=True,
            description=_(
                "Whether everything is set up to allow uploading builds of "
                "this craftrecipe to the CraftStore."
            ),
        )
    )

    def getAllowedInformationTypes(user):
        """Get a list of acceptable `InformationType`s for this craft recipe.

        If the user is a Launchpad admin, any type is acceptable.
        """

    def visibleByUser(user):
        """Can the specified user see this craft recipe?"""

    def requestBuild(build_request, distro_arch_series, channels=None):
        """Request a single build of this craft recipe.

        This method is for internal use; external callers should use
        `requestBuilds` instead.

        :param build_request: The `ICraftRecipeBuildRequest` job being
            processed.
        :param distro_arch_series: The architecture to build for.
        :param channels: A dictionary mapping snap names to channels to use
            for this build.
        :return: `ICraftRecipeBuild`.
        """

    @call_with(requester=REQUEST_USER)
    @operation_parameters(
        channels=Dict(
            title=_("Source snap channels to use for these builds."),
            description=_(
                "A dictionary mapping snap names to channels to use for "
                "these builds. Currently only 'sourcecraft', "
                "'core', 'core18', 'core20', and 'core22' keys are "
                "supported."
            ),
            key_type=TextLine(),
            required=False,
        ),
        architectures=List(
            title=_("The list of architectures to build for this recipe."),
            value_type=Reference(schema=IProcessor),
            required=False,
        ),
    )
    @export_factory_operation(ICraftRecipeBuildRequest, [])
    @operation_for_version("devel")
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

    def requestBuildsFromJob(
        build_request,
        channels=None,
        architectures=None,
        allow_failures=False,
        logger=None,
    ):
        """Synchronous part of `CraftRecipe.requestBuilds`.

        Request that the craft recipe be built for relevant architectures.

        :param build_request: The `ICraftRecipeBuildRequest` job being
            processed.
        :param channels: A dictionary mapping snap names to channels to use
            for these builds.
        :param architectures: If not None, limit builds to architectures
            with these architecture tags (in addition to any other
            applicable constraints).
        :param allow_failures: If True, log exceptions other than "already
            pending" from individual build requests; if False, raise them to
            the caller.
        :param logger: An optional logger.
        :return: A sequence of `ICraftRecipeBuild` instances.
        """

    def getBuildRequest(job_id):
        """Get an asynchronous build request by ID.

        :param job_id: The ID of the build request.
        :return: `ICraftRecipeBuildRequest`.
        """

    pending_build_requests = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Pending build requests for this craft recipe."),
                value_type=Reference(ICraftRecipeBuildRequest),
                required=True,
                readonly=True,
            )
        )
    )

    failed_build_requests = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Failed build requests for this craft recipe."),
                value_type=Reference(ICraftRecipeBuildRequest),
                required=True,
                readonly=True,
            )
        )
    )

    builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("All builds of this craft recipe."),
                description=_(
                    "All builds of this craft recipe, sorted in descending "
                    "order of finishing (or starting if not completed "
                    "successfully)."
                ),
                # Really ICraftRecipeBuild.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        )
    )

    completed_builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Completed builds of this craft recipe."),
                description=_(
                    "Completed builds of this craft recipe, sorted in "
                    "descending order of finishing."
                ),
                # Really ICraftRecipeBuild.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        )
    )

    pending_builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Pending builds of this craft recipe."),
                description=_(
                    "Pending builds of this craft recipe, sorted in "
                    "descending order of creation."
                ),
                # Really ICraftRecipeBuild.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        )
    )


class ICraftRecipeEdit(Interface):
    """`ICraftRecipe` methods that require launchpad.Edit permission."""

    @export_destructor_operation()
    @operation_for_version("devel")
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

    project = exported(
        ReferenceChoice(
            title=_("The project that this craft recipe is associated with"),
            schema=IProduct,
            vocabulary="Product",
            required=True,
            readonly=False,
        )
    )

    name = exported(
        TextLine(
            title=_("Craft recipe name"),
            required=True,
            readonly=False,
            constraint=name_validator,
            description=_("The name of the craft recipe."),
        )
    )

    description = exported(
        Text(
            title=_("Description"),
            required=False,
            readonly=False,
            description=_("A description of the craft recipe."),
        )
    )

    git_repository = exported(
        ReferenceChoice(
            title=_("Git repository"),
            schema=IGitRepository,
            vocabulary="GitRepository",
            required=False,
            readonly=True,
            description=_(
                "A Git repository with a branch containing a sourcecraft.yaml "
                "recipe."
            ),
        )
    )

    git_path = exported(
        TextLine(
            title=_("Git branch path"),
            required=False,
            readonly=True,
            description=_(
                "The path of the Git branch containing a sourcecraft.yaml "
                "recipe."
            ),
        )
    )

    git_repository_url = exported(
        URIField(
            title=_("Git repository URL"),
            required=False,
            readonly=True,
            description=_(
                "The URL of a Git repository with a branch containing a "
                "sourcecraft.yaml at the top level."
            ),
            allowed_schemes=["git", "http", "https"],
            allow_userinfo=True,
            allow_port=True,
            allow_query=False,
            allow_fragment=False,
            trailing_slash=False,
        )
    )

    git_ref = exported(
        Reference(
            IGitRef,
            title=_("Git branch"),
            required=False,
            readonly=False,
            description=_("The Git branch containing a craft.yaml recipe."),
        )
    )

    build_path = exported(
        TextLine(
            title=_("Build path"),
            description=_(
                "Subdirectory within the branch containing craft.yaml."
            ),
            constraint=path_does_not_escape,
            required=False,
            readonly=False,
        )
    )
    information_type = exported(
        Choice(
            title=_("Information type"),
            vocabulary=InformationType,
            required=True,
            readonly=False,
            default=InformationType.PUBLIC,
            description=_(
                "The type of information contained in this craft recipe."
            ),
        )
    )

    auto_build = exported(
        Bool(
            title=_("Automatically build when branch changes"),
            required=True,
            readonly=False,
            description=_(
                "Whether this craft recipe is built automatically when the "
                "branch containing its craft.yaml recipe changes."
            ),
        )
    )

    auto_build_channels = exported(
        Dict(
            title=_("Source snap channels for automatic builds"),
            key_type=TextLine(),
            required=False,
            readonly=False,
            description=_(
                "A dictionary mapping snap names to channels to use when "
                "building this craft recipe.  Currently only 'core', "
                "'core18', 'core20', and 'sourcecraft' keys are supported."
            ),
        )
    )

    is_stale = exported(
        Bool(
            title=_("Craft recipe is stale and is due to be rebuilt."),
            required=True,
            readonly=True,
        )
    )

    store_upload = exported(
        Bool(
            title=_("Automatically upload to store"),
            required=True,
            readonly=False,
            description=_(
                "Whether builds of this craft recipe are automatically "
                "uploaded to the store."
            ),
        )
    )

    store_name = exported(
        TextLine(
            title=_("Registered store name"),
            required=False,
            readonly=False,
            description=_("The registered name of this craft in the store."),
        )
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

    store_channels = exported(
        List(
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
    )


class ICraftRecipeAdminAttributes(Interface):
    """`ICraftRecipe` attributes that can be edited by admins.

    These attributes need launchpad.View to see, and launchpad.Admin to change.
    """

    require_virtualized = exported(
        Bool(
            title=_("Require virtualized builders"),
            required=True,
            readonly=False,
            description=_("Only build this craft recipe on virtual builders."),
        )
    )

    use_fetch_service = exported(
        Bool(
            title=_("Use fetch service"),
            required=True,
            readonly=False,
            description=_(
                "If set, Craft builds will use the fetch-service instead "
                "of the builder-proxy to access external resources."
            ),
        )
    )


# XXX ruinedyourlife 2024-10-02
# https://bugs.launchpad.net/lazr.restful/+bug/760849:
# "beta" is a lie to get WADL generation working.
# Individual attributes must set their version to "devel".
@exported_as_webservice_entry(as_of="beta")
class ICraftRecipe(
    ICraftRecipeView,
    ICraftRecipeEdit,
    ICraftRecipeEditableAttributes,
    ICraftRecipeAdminAttributes,
    IInformationType,
):
    """A buildable craft recipe."""


# XXX ruinedyourlife 2024-10-02
# https://bugs.launchpad.net/lazr.restful/+bug/760849:
# "beta" is a lie to get WADL generation working.
# Individual attributes must set their version to "devel".
@exported_as_webservice_collection(ICraftRecipe)
class ICraftRecipeSet(Interface):
    """A utility to create and access craft recipes."""

    @call_with(registrant=REQUEST_USER)
    @operation_parameters(
        information_type=copy_field(
            ICraftRecipe["information_type"], required=False
        )
    )
    @export_factory_operation(
        ICraftRecipe,
        [
            "owner",
            "project",
            "name",
            "description",
            "git_ref",
            "build_path",
            "auto_build",
            "auto_build_channels",
            "store_upload",
            "store_name",
            "store_channels",
        ],
    )
    @operation_for_version("devel")
    def new(
        registrant,
        owner,
        project,
        name,
        description=None,
        git_repository=None,
        git_repository_url=None,
        git_path=None,
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
        use_fetch_service=False,
    ):
        """Create an `ICraftRecipe`."""

    @operation_parameters(
        owner=Reference(IPerson, title=_("Owner"), required=True),
        project=Reference(IProduct, title=_("Project"), required=True),
        name=TextLine(title=_("Recipe name"), required=True),
    )
    @operation_returns_entry(ICraftRecipe)
    @export_read_operation()
    @operation_for_version("devel")
    def getByName(owner, project, name):
        """Returns the appropriate `ICraftRecipe` for the given objects."""

    def exists(owner, project, name):
        """Check to see if a matching craft recipe exists."""

    def isValidInformationType(information_type, owner, git_ref=None):
        """Whether the information type context is valid."""

    def findByGitRepository(repository, paths=None, check_permissions=True):
        """Return all craft recipes for the given Git repository.

        :param repository: An `IGitRepository`.
        :param paths: If not None, only return craft recipes for one of
            these Git reference paths.
        :param check_permissions: If True, check the user's permissions.
        """

    @operation_parameters(
        owner=Reference(IPerson, title=_("Owner"), required=True)
    )
    @operation_returns_collection_of(ICraftRecipe)
    @export_read_operation()
    @operation_for_version("devel")
    def findByOwner(owner):
        """Return all craft recipes for the given owner."""

    def detachFromGitRepository(repository):
        """Detach all craft recipes from the given Git repository.

        After this, any craft recipes that previously used this repository
        will have no source and so cannot dispatch new builds.
        """

    @collection_default_content()
    def empty_list():
        """Return an empty collection of craft recipes.

        This only exists to keep lazr.restful happy.
        """

    def preloadDataForRecipes(recipes, user):
        """Load the data related to a list of craft recipes."""

    def getSourcecraftYaml(context, logger=None):
        """Fetch a recipe's sourcecraft.yaml from code hosting, if possible.

        :param context: Either an `ICraftRecipe` or the source branch for a
            craft recipe.
        :param logger: An optional logger.

        :return: The recipe's parsed sourcecraft.yaml.
        :raises MissingSourcecraftYaml: if this recipe has no
            sourcecraft.yaml.
        :raises CannotFetchSourcecraftYaml: if it was not possible to fetch
            sourcecraft.yaml from the code hosting backend for some other
            reason.
        :raises CannotParseSourcecraftYaml: if the fetched sourcecraft.yaml
            cannot be parsed.
        """

    def findByPerson(person, visible_by_user=None):
        """Return all craft recipes relevant to `person`.

        This returns craft recipes for Git branches owned by `person`, or
        where `person` is the owner of the craft recipe.

        :param person: An `IPerson`.
        :param visible_by_user: If not None, only return recipes visible by
            this user; otherwise, only return publicly-visible recipes.
        """

    def findByProject(project, visible_by_user=None):
        """Return all craft recipes for the given project.

        :param project: An `IProduct`.
        :param visible_by_user: If not None, only return recipes visible by
            this user; otherwise, only return publicly-visible recipes.
        """

    def findByGitRef(ref):
        """Return all craft recipes for the given Git reference."""

    def findByContext(context, visible_by_user=None, order_by_date=True):
        """Return all craft recipes for the given context.

        :param context: An `IPerson`, `IProduct`, `IGitRepository`, or
            `IGitRef`.
        :param visible_by_user: If not None, only return recipes visible by
            this user; otherwise, only return publicly-visible recipes.
        :param order_by_date: If True, order recipes by descending
            modification date.
        :raises BadCraftRecipeSearchContext: if the context is not
            understood.
        """
