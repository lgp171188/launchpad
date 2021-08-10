# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe interfaces."""

__metaclass__ = type
__all__ = [
    "BadCharmRecipeSource",
    "BadCharmRecipeSearchContext",
    "CannotAuthorizeCharmhubUploads",
    "CannotFetchCharmcraftYaml",
    "CannotParseCharmcraftYaml",
    "CHARM_RECIPE_ALLOW_CREATE",
    "CHARM_RECIPE_BUILD_DISTRIBUTION",
    "CHARM_RECIPE_PRIVATE_FEATURE_FLAG",
    "CharmRecipeBuildAlreadyPending",
    "CharmRecipeBuildDisallowedArchitecture",
    "CharmRecipeBuildRequestStatus",
    "CharmRecipeFeatureDisabled",
    "CharmRecipeNotOwner",
    "CharmRecipePrivacyMismatch",
    "CharmRecipePrivateFeatureDisabled",
    "DuplicateCharmRecipeName",
    "ICharmRecipe",
    "ICharmRecipeBuildRequest",
    "ICharmRecipeSet",
    "MissingCharmcraftYaml",
    "NoSourceForCharmRecipe",
    "NoSuchCharmRecipe",
    ]

from lazr.enum import (
    EnumeratedType,
    Item,
    )
from lazr.restful.declarations import error_status
from lazr.restful.fields import (
    CollectionField,
    Reference,
    ReferenceChoice,
    )
from six.moves import http_client
from zope.interface import (
    Attribute,
    Interface,
    )
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
from lp.app.interfaces.launchpad import IPrivacy
from lp.app.validators.name import name_validator
from lp.app.validators.path import path_does_not_escape
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import IProduct
from lp.services.fields import (
    PersonChoice,
    PublicPersonChoice,
    )
from lp.snappy.validators.channels import channels_validator


CHARM_RECIPE_ALLOW_CREATE = "charm.recipe.create.enabled"
CHARM_RECIPE_PRIVATE_FEATURE_FLAG = "charm.recipe.allow_private"
CHARM_RECIPE_BUILD_DISTRIBUTION = "charm.default_build_distribution"


@error_status(http_client.UNAUTHORIZED)
class CharmRecipeFeatureDisabled(Unauthorized):
    """Only certain users can create new charm recipes."""

    def __init__(self):
        super(CharmRecipeFeatureDisabled, self).__init__(
            "You do not have permission to create new charm recipes.")


@error_status(http_client.UNAUTHORIZED)
class CharmRecipePrivateFeatureDisabled(Unauthorized):
    """Only certain users can create private charm recipes."""

    def __init__(self):
        super(CharmRecipePrivateFeatureDisabled, self).__init__(
            "You do not have permission to create private charm recipes.")


@error_status(http_client.BAD_REQUEST)
class DuplicateCharmRecipeName(Exception):
    """Raised for charm recipes with duplicate project/owner/name."""

    def __init__(self):
        super(DuplicateCharmRecipeName, self).__init__(
            "There is already a charm recipe with the same project, owner, "
            "and name.")


@error_status(http_client.UNAUTHORIZED)
class CharmRecipeNotOwner(Unauthorized):
    """The registrant/requester is not the owner or a member of its team."""


class NoSuchCharmRecipe(NameLookupFailed):
    """The requested charm recipe does not exist."""
    _message_prefix = "No such charm recipe with this owner and project"


@error_status(http_client.BAD_REQUEST)
class NoSourceForCharmRecipe(Exception):
    """Charm recipes must have a source (Git branch)."""

    def __init__(self):
        super(NoSourceForCharmRecipe, self).__init__(
            "New charm recipes must have a Git branch.")


@error_status(http_client.BAD_REQUEST)
class BadCharmRecipeSource(Exception):
    """The elements of the source for a charm recipe are inconsistent."""


@error_status(http_client.BAD_REQUEST)
class CharmRecipePrivacyMismatch(Exception):
    """Charm recipe privacy does not match its content."""

    def __init__(self, message=None):
        super(CharmRecipePrivacyMismatch, self).__init__(
            message or
            "Charm recipe contains private information and cannot be public.")


class BadCharmRecipeSearchContext(Exception):
    """The context is not valid for a charm recipe search."""


@error_status(http_client.BAD_REQUEST)
class CannotAuthorizeCharmhubUploads(Exception):
    """Cannot authorize uploads of a charm to Charmhub."""


class MissingCharmcraftYaml(Exception):
    """The repository for this charm recipe does not have a charmcraft.yaml."""

    def __init__(self, branch_name):
        super(MissingCharmcraftYaml, self).__init__(
            "Cannot find charmcraft.yaml in %s" % branch_name)


class CannotFetchCharmcraftYaml(Exception):
    """Launchpad cannot fetch this charm recipe's charmcraft.yaml."""


class CannotParseCharmcraftYaml(Exception):
    """Launchpad cannot parse this charm recipe's charmcraft.yaml."""


@error_status(http_client.BAD_REQUEST)
class CharmRecipeBuildAlreadyPending(Exception):
    """A build was requested when an identical build was already pending."""

    def __init__(self):
        super(CharmRecipeBuildAlreadyPending, self).__init__(
            "An identical build of this charm recipe is already pending.")


@error_status(http_client.BAD_REQUEST)
class CharmRecipeBuildDisallowedArchitecture(Exception):
    """A build was requested for a disallowed architecture."""

    def __init__(self, das):
        super(CharmRecipeBuildDisallowedArchitecture, self).__init__(
            "This charm recipe is not allowed to build for %s/%s." %
            (das.distroseries.name, das.architecturetag))


class CharmRecipeBuildRequestStatus(EnumeratedType):
    """The status of a request to build a charm recipe."""

    PENDING = Item("""
        Pending

        This charm recipe build request is pending.
        """)

    FAILED = Item("""
        Failed

        This charm recipe build request failed.
        """)

    COMPLETED = Item("""
        Completed

        This charm recipe build request completed successfully.
        """)


class ICharmRecipeBuildRequest(Interface):
    """A request to build a charm recipe."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_requested = Datetime(
        title=_("The time when this request was made"),
        required=True, readonly=True)

    date_finished = Datetime(
        title=_("The time when this request finished"),
        required=False, readonly=True)

    recipe = Reference(
        # Really ICharmRecipe.
        Interface,
        title=_("Charm recipe"), required=True, readonly=True)

    status = Choice(
        title=_("Status"), vocabulary=CharmRecipeBuildRequestStatus,
        required=True, readonly=True)

    error_message = TextLine(
        title=_("Error message"), required=True, readonly=True)

    builds = CollectionField(
        title=_("Builds produced by this request"),
        # Really ICharmRecipeBuild.
        value_type=Reference(schema=Interface),
        required=True, readonly=True)

    requester = Reference(
        title=_("The person requesting the builds."), schema=IPerson,
        required=True, readonly=True)

    channels = Dict(
        title=_("Source snap channels for builds produced by this request"),
        key_type=TextLine(), required=False, readonly=True)

    architectures = Set(
        title=_("If set, this request is limited to these architecture tags"),
        value_type=TextLine(), required=False, readonly=True)


class ICharmRecipeView(Interface):
    """`ICharmRecipe` attributes that require launchpad.View permission."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_created = Datetime(
        title=_("Date created"), required=True, readonly=True)
    date_last_modified = Datetime(
        title=_("Date last modified"), required=True, readonly=True)

    registrant = PublicPersonChoice(
        title=_("Registrant"), required=True, readonly=True,
        vocabulary="ValidPersonOrTeam",
        description=_("The person who registered this charm recipe."))

    source = Attribute(
        "The source branch for this charm recipe (VCS-agnostic).")

    private = Bool(
        title=_("Private"), required=False, readonly=False,
        description=_("Whether this charm recipe is private."))

    def getAllowedInformationTypes(user):
        """Get a list of acceptable `InformationType`s for this charm recipe.

        If the user is a Launchpad admin, any type is acceptable.
        """

    def visibleByUser(user):
        """Can the specified user see this charm recipe?"""

    def requestBuild(build_request, distro_arch_series, channels=None):
        """Request a single build of this charm recipe.

        This method is for internal use; external callers should use
        `requestBuilds` instead.

        :param build_request: The `ICharmRecipeBuildRequest` job being
            processed.
        :param distro_arch_series: The architecture to build for.
        :param channels: A dictionary mapping snap names to channels to use
            for this build.
        :return: `ICharmRecipeBuild`.
        """

    def requestBuilds(requester, channels=None, architectures=None):
        """Request that the charm recipe be built.

        This is an asynchronous operation; once the operation has finished,
        the resulting build request's C{status} will be "Completed" and its
        C{builds} collection will return the resulting builds.

        :param requester: The person requesting the builds.
        :param channels: A dictionary mapping snap names to channels to use
            for these builds.
        :param architectures: If not None, limit builds to architectures
            with these architecture tags (in addition to any other
            applicable constraints).
        :return: An `ICharmRecipeBuildRequest`.
        """

    def requestBuildsFromJob(build_request, channels=None, architectures=None,
                             allow_failures=False, logger=None):
        """Synchronous part of `CharmRecipe.requestBuilds`.

        Request that the charm recipe be built for relevant architectures.

        :param build_request: The `ICharmRecipeBuildRequest` job being
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
        :return: A sequence of `ICharmRecipeBuild` instances.
        """

    def getBuildRequest(job_id):
        """Get an asynchronous build request by ID.

        :param job_id: The ID of the build request.
        :return: `ICharmRecipeBuildRequest`.
        """

    pending_build_requests = CollectionField(
        title=_("Pending build requests for this charm recipe."),
        value_type=Reference(ICharmRecipeBuildRequest),
        required=True, readonly=True)

    failed_build_requests = CollectionField(
        title=_("Failed build requests for this charm recipe."),
        value_type=Reference(ICharmRecipeBuildRequest),
        required=True, readonly=True)

    builds = CollectionField(
        title=_("All builds of this charm recipe."),
        description=_(
            "All builds of this charm recipe, sorted in descending order "
            "of finishing (or starting if not completed successfully)."),
        # Really ICharmRecipeBuild.
        value_type=Reference(schema=Interface), readonly=True)

    completed_builds = CollectionField(
        title=_("Completed builds of this charm recipe."),
        description=_(
            "Completed builds of this charm recipe, sorted in descending "
            "order of finishing."),
        # Really ICharmRecipeBuild.
        value_type=Reference(schema=Interface), readonly=True)

    pending_builds = CollectionField(
        title=_("Pending builds of this charm recipe."),
        description=_(
            "Pending builds of this charm recipe, sorted in descending "
            "order of creation."),
        # Really ICharmRecipeBuild.
        value_type=Reference(schema=Interface), readonly=True)


class ICharmRecipeEdit(Interface):
    """`ICharmRecipe` methods that require launchpad.Edit permission."""

    def beginAuthorization():
        """Begin authorizing uploads of this charm recipe to Charmhub.

        :raises CannotAuthorizeCharmhubUploads: if the charm recipe is not
            properly configured for Charmhub uploads.
        :raises BadRequestPackageUploadResponse: if Charmhub returns an
            error or a response without a macaroon when asked to issue a
            macaroon.
        :raises BadCandidMacaroon: if the macaroon returned by Charmhub has
            unsuitable Candid caveats.
        :return: The serialized macaroon returned by the store.  The caller
            should acquire a discharge macaroon for this caveat from Candid
            and then call `completeAuthorization`.
        """

    def completeAuthorization(unbound_discharge_macaroon_raw):
        """Complete authorizing uploads of this charm recipe to Charmhub.

        :param unbound_discharge_macaroon_raw: The serialized unbound
            discharge macaroon returned by Candid.
        :raises CannotAuthorizeCharmhubUploads: if the charm recipe is not
            properly configured for Charmhub uploads.
        """

    def destroySelf():
        """Delete this charm recipe, provided that it has no builds."""


class ICharmRecipeEditableAttributes(Interface):
    """`ICharmRecipe` attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    owner = PersonChoice(
        title=_("Owner"), required=True, readonly=False,
        vocabulary="AllUserTeamsParticipationPlusSelf",
        description=_("The owner of this charm recipe."))

    project = ReferenceChoice(
        title=_("The project that this charm recipe is associated with"),
        schema=IProduct, vocabulary="Product",
        required=True, readonly=False)

    name = TextLine(
        title=_("Charm recipe name"), required=True, readonly=False,
        constraint=name_validator,
        description=_("The name of the charm recipe."))

    description = Text(
        title=_("Description"), required=False, readonly=False,
        description=_("A description of the charm recipe."))

    git_repository = ReferenceChoice(
        title=_("Git repository"),
        schema=IGitRepository, vocabulary="GitRepository",
        required=False, readonly=True,
        description=_(
            "A Git repository with a branch containing a charm recipe."))

    git_path = TextLine(
        title=_("Git branch path"), required=False, readonly=True,
        description=_("The path of the Git branch containing a charm recipe."))

    git_ref = Reference(
        IGitRef, title=_("Git branch"), required=False, readonly=False,
        description=_("The Git branch containing a charm recipe."))

    build_path = TextLine(
        title=_("Build path"),
        description=_(
            "Subdirectory within the branch containing metadata.yaml."),
        constraint=path_does_not_escape, required=False, readonly=False)

    information_type = Choice(
        title=_("Information type"), vocabulary=InformationType,
        required=True, readonly=False, default=InformationType.PUBLIC,
        description=_(
            "The type of information contained in this charm recipe."))

    auto_build = Bool(
        title=_("Automatically build when branch changes"),
        required=True, readonly=False,
        description=_(
            "Whether this charm recipe is built automatically when its branch "
            "changes."))

    auto_build_channels = Dict(
        title=_("Source snap channels for automatic builds"),
        key_type=TextLine(), required=False, readonly=False,
        description=_(
            "A dictionary mapping snap names to channels to use when building "
            "this charm recipe.  Currently only 'charmcraft', 'core', "
            "'core18', and 'core20' keys are supported."))

    is_stale = Bool(
        title=_("Charm recipe is stale and is due to be rebuilt."),
        required=True, readonly=True)

    store_upload = Bool(
        title=_("Automatically upload to store"),
        required=True, readonly=False,
        description=_(
            "Whether builds of this charm recipe are automatically uploaded "
            "to the store."))

    store_name = TextLine(
        title=_("Registered store name"),
        required=False, readonly=False,
        description=_(
            "The registered name of this charm in the store."))

    store_secrets = List(
        value_type=TextLine(), title=_("Store upload tokens"),
        required=False, readonly=False,
        description=_(
            "Serialized secrets issued by the store and the login service to "
            "authorize uploads of this charm recipe."))

    store_channels = List(
        title=_("Store channels"),
        required=False, readonly=False, constraint=channels_validator,
        description=_(
            "Channels to release this charm to after uploading it to the "
            "store. A channel is defined by a combination of an optional "
            "track, a risk, and an optional branch, e.g. "
            "'2.1/stable/fix-123', '2.1/stable', 'stable/fix-123', or "
            "'stable'."))


class ICharmRecipeAdminAttributes(Interface):
    """`ICharmRecipe` attributes that can be edited by admins.

    These attributes need launchpad.View to see, and launchpad.Admin to change.
    """

    require_virtualized = Bool(
        title=_("Require virtualized builders"), required=True, readonly=False,
        description=_("Only build this charm recipe on virtual builders."))


class ICharmRecipe(
        ICharmRecipeView, ICharmRecipeEdit, ICharmRecipeEditableAttributes,
        ICharmRecipeAdminAttributes, IPrivacy, IInformationType):
    """A buildable charm recipe."""


class ICharmRecipeSet(Interface):
    """A utility to create and access charm recipes."""

    def new(registrant, owner, project, name, description=None, git_ref=None,
            build_path=None, require_virtualized=True,
            information_type=InformationType.PUBLIC, auto_build=False,
            auto_build_channels=None, store_upload=False, store_name=None,
            store_secrets=None, store_channels=None, date_created=None):
        """Create an `ICharmRecipe`."""

    def getByName(owner, project, name):
        """Returns the appropriate `ICharmRecipe` for the given objects."""

    def exists(owner, project, name):
        """Check to see if a matching charm recipe exists."""

    def findByPerson(person, visible_by_user=None):
        """Return all charm recipes relevant to `person`.

        This returns charm recipes for Git branches owned by `person`, or
        where `person` is the owner of the charm recipe.

        :param person: An `IPerson`.
        :param visible_by_user: If not None, only return recipes visible by
            this user; otherwise, only return publicly-visible recipes.
        """

    def findByProject(project, visible_by_user=None):
        """Return all charm recipes for the given project.

        :param project: An `IProduct`.
        :param visible_by_user: If not None, only return recipes visible by
            this user; otherwise, only return publicly-visible recipes.
        """

    def findByGitRepository(repository, paths=None, check_permissions=True):
        """Return all charm recipes for the given Git repository.

        :param repository: An `IGitRepository`.
        :param paths: If not None, only return charm recipes for one of
            these Git reference paths.
        """

    def findByGitRef(ref):
        """Return all charm recipes for the given Git reference."""

    def findByContext(context, visible_by_user=None, order_by_date=True):
        """Return all charm recipes for the given context.

        :param context: An `IPerson`, `IProduct`, `IGitRepository`, or
            `IGitRef`.
        :param visible_by_user: If not None, only return recipes visible by
            this user; otherwise, only return publicly-visible recipes.
        :param order_by_date: If True, order recipes by descending
            modification date.
        :raises BadCharmRecipeSearchContext: if the context is not
            understood.
        """

    def isValidInformationType(information_type, owner, git_ref=None):
        """Whether the information type context is valid."""

    def preloadDataForRecipes(recipes, user):
        """Load the data related to a list of charm recipes."""

    def getCharmcraftYaml(context, logger=None):
        """Fetch a recipe's charmcraft.yaml from code hosting, if possible.

        :param context: Either an `ICharmRecipe` or the source branch for a
            charm recipe.
        :param logger: An optional logger.

        :return: The recipe's parsed charmcraft.yaml.
        :raises MissingCharmcraftYaml: if this recipe has no
            charmcraft.yaml.
        :raises CannotFetchCharmcraftYaml: if it was not possible to fetch
            charmcraft.yaml from the code hosting backend for some other
            reason.
        :raises CannotParseCharmcraftYaml: if the fetched charmcraft.yaml
            cannot be parsed.
        """

    def detachFromGitRepository(repository):
        """Detach all charm recipes from the given Git repository.

        After this, any charm recipes that previously used this repository
        will have no source and so cannot dispatch new builds.
        """
