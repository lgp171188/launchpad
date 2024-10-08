# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Rock recipe interfaces."""

__all__ = [
    "BadRockRecipeSource",
    "BadRockRecipeSearchContext",
    "CannotFetchRockcraftYaml",
    "CannotParseRockcraftYaml",
    "ROCK_RECIPE_ALLOW_CREATE",
    "ROCK_RECIPE_PRIVATE_FEATURE_FLAG",
    "RockRecipeBuildAlreadyPending",
    "RockRecipeBuildDisallowedArchitecture",
    "RockRecipeBuildRequestStatus",
    "RockRecipeFeatureDisabled",
    "RockRecipeNotOwner",
    "RockRecipePrivacyMismatch",
    "RockRecipePrivateFeatureDisabled",
    "DuplicateRockRecipeName",
    "IRockRecipe",
    "IRockRecipeBuildRequest",
    "IRockRecipeSet",
    "IRockRecipeView",
    "MissingRockcraftYaml",
    "NoSourceForRockRecipe",
    "NoSuchRockRecipe",
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
from lp.buildmaster.builderproxy import FetchServicePolicy
from lp.buildmaster.interfaces.processor import IProcessor
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import IProduct
from lp.services.fields import PersonChoice, PublicPersonChoice, URIField
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


class MissingRockcraftYaml(Exception):
    """The repository for this rock recipe does not have a rockcraft.yaml."""

    def __init__(self, branch_name):
        super().__init__("Cannot find rockcraft.yaml in %s" % branch_name)


class CannotFetchRockcraftYaml(Exception):
    """Launchpad cannot fetch this rock recipe's rockcraft.yaml."""


class CannotParseRockcraftYaml(Exception):
    """Launchpad cannot parse this rock recipe's rockcraft.yaml."""


@error_status(http.client.BAD_REQUEST)
class RockRecipeBuildAlreadyPending(Exception):
    """A build was requested when an identical build was already pending."""

    def __init__(self):
        super().__init__(
            "An identical build of this rock recipe is already pending."
        )


@error_status(http.client.BAD_REQUEST)
class RockRecipeBuildDisallowedArchitecture(Exception):
    """A build was requested for a disallowed architecture."""

    def __init__(self, das):
        super().__init__(
            "This rock recipe is not allowed to build for %s/%s."
            % (das.distroseries.name, das.architecturetag)
        )


class RockRecipeBuildRequestStatus(EnumeratedType):
    """The status of a request to build a rock recipe."""

    PENDING = Item(
        """
        Pending

        This rock recipe build request is pending.
        """
    )

    FAILED = Item(
        """
        Failed

        This rock recipe build request failed.
        """
    )

    COMPLETED = Item(
        """
        Completed

        This rock recipe build request completed successfully.
        """
    )


# XXX jugmac00 2024-09-16 https://bugs.launchpad.net/lazr.restful/+bug/760849:
# "beta" is a lie to get WADL generation working.
# Individual attributes must set their version to "devel".
@exported_as_webservice_entry(as_of="beta")
class IRockRecipeBuildRequest(Interface):
    """A request to build a rock recipe."""

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
            # Really IRockRecipe, patched in lp.rocks.interfaces.webservice
            Interface,
            title=_("Rock recipe"),
            required=True,
            readonly=True,
        )
    )

    status = exported(
        Choice(
            title=_("Status"),
            vocabulary=RockRecipeBuildRequestStatus,
            required=True,
            readonly=True,
        )
    )

    error_message = exported(
        TextLine(title=_("Error message"), required=True, readonly=True)
    )

    builds = exported(
        CollectionField(
            title=_("Builds produced by this request"),
            # Really IRockRecipeBuild, patched in
            # lp.rocks.interfaces.webservice
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


class IRockRecipeView(Interface):
    """`IRockRecipe` attributes that require launchpad.View permission."""

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
            description=_("The person who registered this rock recipe."),
        )
    )

    source = Attribute("The source branch for this rock recipe.")

    private = exported(
        Bool(
            title=_("Private"),
            required=False,
            readonly=False,
            description=_("Whether this rock recipe is private."),
        )
    )

    can_upload_to_store = exported(
        Bool(
            title=_("Can upload to the RockStore"),
            required=True,
            readonly=True,
            description=_(
                "Whether everything is set up to allow uploading builds of "
                "this rockrecipe to the RockStore."
            ),
        )
    )

    def getAllowedInformationTypes(user):
        """Get a list of acceptable `InformationType`s for this rock recipe.

        If the user is a Launchpad admin, any type is acceptable.
        """

    def visibleByUser(user):
        """Can the specified user see this rock recipe?"""

    def requestBuild(
        build_request, distro_arch_series, rock_base=None, channels=None
    ):
        """Request a single build of this rock recipe.

        This method is for internal use; external callers should use
        `requestBuilds` instead.

        :param build_request: The `IRockRecipeBuildRequest` job being
            processed.
        :param distro_arch_series: The architecture to build for.
        :param rock_base: The `IRockBase` to use for this build.
        :param channels: A dictionary mapping snap names to channels to use
            for this build.
        :return: `IRockRecipeBuild`.
        """

    @call_with(requester=REQUEST_USER)
    @operation_parameters(
        channels=Dict(
            title=_("Source snap channels to use for these builds."),
            description=_(
                "A dictionary mapping snap names to channels to use for these "
                "builds.  Currently only 'rockcraft', 'core', 'core18', "
                "'core20', and 'core22' keys are supported."
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
    @export_factory_operation(IRockRecipeBuildRequest, [])
    @operation_for_version("devel")
    def requestBuilds(requester, channels=None, architectures=None):
        """Request that the rock recipe be built.

        This is an asynchronous operation; once the operation has finished,
        the resulting build request's C{status} will be "Completed" and its
        C{builds} collection will return the resulting builds.

        :param requester: The person requesting the builds.
        :param channels: A dictionary mapping snap names to channels to use
            for these builds.
        :param architectures: If not None, limit builds to architectures
            with these architecture tags (in addition to any other
            applicable constraints).
        :return: An `IRockRecipeBuildRequest`.
        """

    def requestBuildsFromJob(
        build_request,
        channels=None,
        architectures=None,
        allow_failures=False,
        logger=None,
    ):
        """Synchronous part of `RockRecipe.requestBuilds`.

        Request that the rock recipe be built for relevant architectures.

        :param build_request: The `IRockRecipeBuildRequest` job being
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
        :return: A sequence of `IRockRecipeBuild` instances.
        """

    def getBuildRequest(job_id):
        """Get an asynchronous build request by ID.

        :param job_id: The ID of the build request.
        :return: `IRockRecipeBuildRequest`.
        """

    pending_build_requests = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Pending build requests for this rock recipe."),
                value_type=Reference(IRockRecipeBuildRequest),
                required=True,
                readonly=True,
            )
        )
    )

    failed_build_requests = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Failed build requests for this rock recipe."),
                value_type=Reference(IRockRecipeBuildRequest),
                required=True,
                readonly=True,
            )
        )
    )

    builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("All builds of this rock recipe."),
                description=_(
                    "All builds of this rock recipe, sorted in descending "
                    "order of finishing (or starting if not completed "
                    "successfully)."
                ),
                # Really IRockRecipeBuild.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        )
    )

    completed_builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Completed builds of this rock recipe."),
                description=_(
                    "Completed builds of this rock recipe, sorted in "
                    "descending order of finishing."
                ),
                # Really IRockRecipeBuild.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        )
    )

    pending_builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Pending builds of this rock recipe."),
                description=_(
                    "Pending builds of this rock recipe, sorted in descending "
                    "order of creation."
                ),
                # Really IRockRecipeBuild.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        )
    )


class IRockRecipeEdit(Interface):
    """`IRockRecipe` methods that require launchpad.Edit permission."""

    @export_destructor_operation()
    @operation_for_version("devel")
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

    project = exported(
        ReferenceChoice(
            title=_("The project that this rock recipe is associated with"),
            schema=IProduct,
            vocabulary="Product",
            required=True,
            readonly=False,
        )
    )

    name = exported(
        TextLine(
            title=_("Rock recipe name"),
            required=True,
            readonly=False,
            constraint=name_validator,
            description=_("The name of the rock recipe."),
        )
    )

    description = exported(
        Text(
            title=_("Description"),
            required=False,
            readonly=False,
            description=_("A description of the rock recipe."),
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
                "A Git repository with a branch containing a rockcraft.yaml "
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
                "The path of the Git branch containing a rockcraft.yaml "
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
                "rockcraft.yaml at the top level."
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
            description=_(
                "The Git branch containing a rockcraft.yaml recipe."
            ),
        )
    )

    build_path = exported(
        TextLine(
            title=_("Build path"),
            description=_(
                "Subdirectory within the branch containing rockcraft.yaml."
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
                "The type of information contained in this rock recipe."
            ),
        )
    )

    auto_build = exported(
        Bool(
            title=_("Automatically build when branch changes"),
            required=True,
            readonly=False,
            description=_(
                "Whether this rock recipe is built automatically when the "
                "branch containing its rockcraft.yaml recipe changes."
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
                "A dictionary mapping snap names to channels to use when"
                " building this rock recipe. Currently only 'core', 'core18', "
                "'core20', and 'rockcraft' keys are supported."
            ),
        )
    )

    is_stale = exported(
        Bool(
            title=_("Rock recipe is stale and is due to be rebuilt."),
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
                "Whether builds of this rock recipe are automatically "
                "uploaded to the store."
            ),
        )
    )

    store_name = exported(
        TextLine(
            title=_("Registered store name"),
            required=False,
            readonly=False,
            description=_("The registered name of this rock in the store."),
        )
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

    store_channels = exported(
        List(
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
    )


class IRockRecipeAdminAttributes(Interface):
    """`IRockRecipe` attributes that can be edited by admins.

    These attributes need launchpad.View to see, and launchpad.Admin to change.
    """

    require_virtualized = exported(
        Bool(
            title=_("Require virtualized builders"),
            required=True,
            readonly=False,
            description=_("Only build this rock recipe on virtual builders."),
        )
    )

    use_fetch_service = exported(
        Bool(
            title=_("Use fetch service"),
            required=True,
            readonly=False,
            description=_(
                "If set, Rock builds will use the fetch-service instead "
                "of the builder-proxy to access external resources."
            ),
        )
    )

    fetch_service_policy = exported(
        Choice(
            title=_("Fetch service policy"),
            vocabulary=FetchServicePolicy,
            required=False,
            readonly=False,
            default=FetchServicePolicy.STRICT,
            description=_(
                "Which policy to use when using the fetch service. Ignored if "
                "`use_fetch_service` flag is False."
            ),
        )
    )


# XXX jugmac00 2024-09-16 https://bugs.launchpad.net/lazr.restful/+bug/760849:
# "beta" is a lie to get WADL generation working.
# Individual attributes must set their version to "devel".
@exported_as_webservice_entry(as_of="beta")
class IRockRecipe(
    IRockRecipeView,
    IRockRecipeEdit,
    IRockRecipeEditableAttributes,
    IRockRecipeAdminAttributes,
    IInformationType,
):
    """A buildable rock recipe."""


@exported_as_webservice_collection(IRockRecipe)
class IRockRecipeSet(Interface):
    """A utility to create and access rock recipes."""

    @call_with(registrant=REQUEST_USER)
    @operation_parameters(
        information_type=copy_field(
            IRockRecipe["information_type"], required=False
        )
    )
    @export_factory_operation(
        IRockRecipe,
        [
            "owner",
            "project",
            "name",
            "description",
            "git_repository",
            "git_repository_url",
            "git_path",
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
        fetch_service_policy=FetchServicePolicy.STRICT,
    ):
        """Create an `IRockRecipe`."""

    @operation_parameters(
        owner=Reference(IPerson, title=_("Owner"), required=True),
        project=Reference(IProduct, title=_("Project"), required=True),
        name=TextLine(title=_("Recipe name"), required=True),
    )
    @operation_returns_entry(IRockRecipe)
    @export_read_operation()
    @operation_for_version("devel")
    def getByName(owner, project, name):
        """Returns the appropriate `IRockRecipe` for the given objects."""

    def findByPerson(person, visible_by_user=None):
        """Return all rock recipes relevant to `person`.

        This returns rock recipes for Git branches owned by `person`, or
        where `person` is the owner of the rock recipe.

        :param person: An `IPerson`.
        :param visible_by_user: If not None, only return recipes visible by
            this user; otherwise, only return publicly-visible recipes.
        """

    def findByProject(project, visible_by_user=None):
        """Return all rock recipes for the given project.

        :param project: An `IProduct`.
        :param visible_by_user: If not None, only return recipes visible by
            this user; otherwise, only return publicly-visible recipes.
        """

    def findByGitRepository(repository, paths=None, check_permissions=True):
        """Return all rock recipes for the given Git repository.

        :param repository: An `IGitRepository`.
        :param paths: If not None, only return rock recipes for one of
            these Git reference paths.
        """

    def findByGitRef(ref):
        """Return all rock recipes for the given Git reference."""

    def findByContext(context, visible_by_user=None, order_by_date=True):
        """Return all rock recipes for the given context.

        :param context: An `IPerson`, `IProduct`, `IGitRepository`, or
            `IGitRef`.
        :param visible_by_user: If not None, only return recipes visible by
            this user; otherwise, only return publicly-visible recipes.
        :param order_by_date: If True, order recipes by descending
            modification date.
        :raises BadRockRecipeSearchContext: if the context is not
            understood.
        """

    def exists(owner, project, name):
        """Check to see if a matching rock recipe exists."""

    def isValidInformationType(information_type, owner, git_ref=None):
        """Whether the information type context is valid."""

    def preloadDataForRecipes(recipes, user):
        """Load the data related to a list of rock recipes."""

    def getRockcraftYaml(context, logger=None):
        """Fetch a recipe's rockcraft.yaml from code hosting, if possible.

        :param context: Either an `IRockRecipe` or the source branch for a
            rock recipe.
        :param logger: An optional logger.

        :return: The recipe's parsed rockcraft.yaml.
        :raises MissingRockcraftYaml: if this recipe has no
            rockcraft.yaml.
        :raises CannotFetchRockcraftYaml: if it was not possible to fetch
            rockcraft.yaml from the code hosting backend for some other
            reason.
        :raises CannotParseRockcraftYaml: if the fetched rockcraft.yaml
            cannot be parsed.
        """

    @operation_parameters(
        owner=Reference(IPerson, title=_("Owner"), required=True)
    )
    @operation_returns_collection_of(IRockRecipe)
    @export_read_operation()
    @operation_for_version("devel")
    def findByOwner(owner):
        """Return all rock recipes with the given `owner`."""

    def detachFromGitRepository(repository):
        """Detach all rock recipes from the given Git repository.

        After this, any rock recipes that previously used this repository
        will have no source and so cannot dispatch new builds.
        """

    @collection_default_content()
    def empty_list():
        """Return an empty collection of rock recipes.

        This only exists to keep lazr.restful happy.
        """
