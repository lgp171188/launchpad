# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces related to recipes for OCI Images."""

__all__ = [
    "CannotModifyOCIRecipeProcessor",
    "DuplicateOCIRecipeName",
    "IOCIRecipe",
    "IOCIRecipeBuildRequest",
    "IOCIRecipeEdit",
    "IOCIRecipeEditableAttributes",
    "IOCIRecipeSet",
    "IOCIRecipeView",
    "NoSourceForOCIRecipe",
    "NoSuchOCIRecipe",
    "OCIRecipeBuildAlreadyPending",
    "OCIRecipeFeatureDisabled",
    "OCIRecipeBranchHasInvalidFormat",
    "OCIRecipeNotOwner",
    "OCIRecipePrivacyMismatch",
    "OCI_RECIPE_ALLOW_CREATE",
    "OCI_RECIPE_BUILD_DISTRIBUTION",
    "UsingDistributionCredentials",
]

import http.client

from lazr.lifecycle.snapshot import doNotSnapshot
from lazr.restful.declarations import (
    REQUEST_USER,
    call_with,
    error_status,
    export_factory_operation,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
    operation_parameters,
)
from lazr.restful.fields import CollectionField, Reference, ReferenceChoice
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
from lp.app.validators.name import name_validator
from lp.app.validators.path import path_does_not_escape
from lp.buildmaster.interfaces.processor import IProcessor
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepository
from lp.oci.enums import OCIRecipeBuildRequestStatus
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.role import IHasOwner
from lp.services.database.constants import DEFAULT
from lp.services.fields import PersonChoice, PublicPersonChoice
from lp.services.webhooks.interfaces import IWebhookTarget

OCI_RECIPE_ALLOW_CREATE = "oci.recipe.create.enabled"
OCI_RECIPE_BUILD_DISTRIBUTION = "oci.default_build_distribution"
OCI_RECIPE_PRIVATE_FEATURE_FLAG = "oci.recipe.allow_private"


@error_status(http.client.UNAUTHORIZED)
class OCIRecipeFeatureDisabled(Unauthorized):
    """Only certain users can create new OCI recipes."""

    def __init__(self):
        super().__init__(
            "You do not have permission to create new OCI recipes."
        )


@error_status(http.client.UNAUTHORIZED)
class OCIRecipeNotOwner(Unauthorized):
    """The registrant/requester is not the owner or a member of its team."""


@error_status(http.client.BAD_REQUEST)
class OCIRecipeBuildAlreadyPending(Exception):
    """A build was requested when an identical build was already pending."""

    def __init__(self):
        super().__init__(
            "An identical build of this OCI recipe is already pending."
        )


@error_status(http.client.BAD_REQUEST)
class DuplicateOCIRecipeName(Exception):
    """An OCI Recipe already exists with the same name."""


class NoSuchOCIRecipe(NameLookupFailed):
    """The requested OCI Recipe does not exist."""

    _message_prefix = "No such OCI recipe exists for this OCI project"


@error_status(http.client.BAD_REQUEST)
class UsingDistributionCredentials(Exception):
    """The OCI Recipe is in a Distribution that has credentials set."""

    def __init__(self):
        super().__init__(
            "The OCI recipe is in a distribution that has credentials set."
        )


@error_status(http.client.BAD_REQUEST)
class NoSourceForOCIRecipe(Exception):
    """OCI Recipes must have a source and build file."""

    def __init__(self):
        super().__init__(
            "New OCI recipes must have a git branch and build file."
        )


@error_status(http.client.FORBIDDEN)
class CannotModifyOCIRecipeProcessor(Exception):
    """Tried to enable or disable a restricted processor on an OCI recipe."""

    _fmt = (
        "%(processor)s is restricted, and may only be enabled or disabled "
        "by administrators."
    )

    def __init__(self, processor):
        super().__init__(self._fmt % {"processor": processor.name})


@error_status(http.client.BAD_REQUEST)
class OCIRecipePrivacyMismatch(Exception):
    """OCI recipe privacy does not match its content."""

    def __init__(self, message=None):
        super().__init__(
            message
            or "OCI recipe contains private information and cannot be public."
        )


@error_status(http.client.BAD_REQUEST)
class OCIRecipeBranchHasInvalidFormat(Exception):
    """The branch name for the OCI recipe does not match the correct format."""

    def __init__(self):
        super().__init__(
            "The branch name for the OCI recipe does not "
            "match the APPVERSION-UBUNTUVERSION format (ex. v1.0-20.04)"
        )


@exported_as_webservice_entry(
    publish_web_link=True,
    as_of="devel",
    singular_name="oci_recipe_build_request",
)
class IOCIRecipeBuildRequest(Interface):
    """A request to build an OCI Recipe."""

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
            # Really IOCIRecipe, patched in lp.oci.interfaces.webservice.
            Interface,
            title=_("OCI Recipe"),
            required=True,
            readonly=True,
        )
    )

    status = exported(
        Choice(
            title=_("Status"),
            vocabulary=OCIRecipeBuildRequestStatus,
            required=True,
            readonly=True,
        )
    )

    error_message = exported(
        TextLine(title=_("Error message"), required=False, readonly=True)
    )

    builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Builds produced by this request"),
                # Really IOCIRecipeBuild, patched in
                # lp.oci.interfaces.webservice.
                value_type=Reference(schema=Interface),
                required=True,
                readonly=True,
            )
        )
    )

    architectures = Set(
        title=_("If set, limit builds to these architecture tags."),
        value_type=TextLine(),
        required=False,
        readonly=True,
    )

    uploaded_manifests = Dict(
        title=_("A dict of manifest information per build."),
        key_type=Int(),
        value_type=Dict(),
        required=False,
        readonly=True,
    )

    def addUploadedManifest(build_id, manifest_info):
        """Add the manifest information for one of the builds in this
        BuildRequest.
        """


class IOCIRecipeView(Interface):
    """`IOCIRecipe` attributes that require launchpad.View permission."""

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
            description=_("The user who registered this recipe."),
            vocabulary="ValidPersonOrTeam",
            required=True,
            readonly=True,
        )
    )

    distribution = Reference(
        IDistribution,
        title=_("Distribution"),
        required=True,
        readonly=True,
        description=_("The distribution that this recipe is associated with."),
    )

    distro_series = Reference(
        IDistroSeries,
        title=_("Distro series"),
        required=True,
        readonly=True,
        description=_("The series for which the recipe should be built."),
    )

    available_processors = Attribute(
        "The architectures that are available to be enabled or disabled for "
        "this OCI recipe."
    )

    pending_build_requests = Attribute(
        "The list of build requests that didn't trigger builds yet."
    )

    # This should only be set by using IOCIProject.setOfficialRecipe
    official = Bool(
        title=_("OCI project official"),
        required=False,
        description=_("True if this recipe is official for its OCI project."),
        readonly=True,
    )

    private = Bool(
        title=_("Is this OCI recipe private?"),
        required=True,
        readonly=True,
        description=_("True if this recipe is private. False otherwise."),
    )

    pillar = Attribute("The pillar of this OCI recipe.")

    @call_with(check_permissions=True, user=REQUEST_USER)
    @operation_parameters(
        processors=List(value_type=Reference(schema=IProcessor), required=True)
    )
    @export_write_operation()
    @operation_for_version("devel")
    def setProcessors(processors, check_permissions=False, user=None):
        """Set the architectures for which the recipe should be built."""

    def getAllowedArchitectures():
        """Return all distroarchseries that this recipe can build for.

        :return: Sequence of `IDistroArchSeries` instances.
        """

    builds = doNotSnapshot(
        CollectionField(
            title=_("Completed builds of this OCI recipe."),
            description=_(
                "Completed builds of this OCI recipe, sorted in descending "
                "order of finishing."
            ),
            # Really IOCIRecipeBuild, patched in _schema_circular_imports.
            value_type=Reference(schema=Interface),
            required=True,
            readonly=True,
        )
    )

    completed_builds = doNotSnapshot(
        CollectionField(
            title=_("Completed builds of this OCI recipe."),
            description=_(
                "Completed builds of this OCI recipe, sorted in descending "
                "order of finishing."
            ),
            # Really IOCIRecipeBuild, patched in _schema_circular_imports.
            value_type=Reference(schema=Interface),
            readonly=True,
        )
    )

    completed_builds_without_build_request = doNotSnapshot(
        CollectionField(
            title=_("Completed builds of this OCI recipe."),
            description=_(
                "Completed builds of this OCI recipe, sorted in descending "
                "order of finishing that do no have a corresponding "
                "build request"
            ),
            # Really IOCIRecipeBuild, patched in _schema_circular_imports.
            value_type=Reference(schema=Interface),
            readonly=True,
        )
    )

    pending_builds = doNotSnapshot(
        CollectionField(
            title=_("Pending builds of this OCI recipe."),
            description=_(
                "Pending builds of this OCI recipe, sorted in descending "
                "order of creation."
            ),
            # Really IOCIRecipeBuild, patched in _schema_circular_imports.
            value_type=Reference(schema=Interface),
            readonly=True,
        )
    )

    push_rules = exported(
        CollectionField(
            title=_("Push rules for this OCI recipe."),
            description=_(
                "All of the push rules for registry upload "
                "that apply to this recipe."
            ),
            # Really IOCIPushRule, patched in _schema_cirular_imports.
            value_type=Reference(schema=Interface),
            readonly=True,
        )
    )

    can_upload_to_registry = Bool(
        title=_("Can upload to registry"),
        required=True,
        readonly=True,
        description=_(
            "Whether everything is set up to allow uploading builds of "
            "this OCI recipe to a registry."
        ),
    )

    is_valid_branch_format = Bool(
        title=_("Is valid branch format"),
        required=True,
        readonly=True,
        description=_(
            "Whether the git branch name is the correct "
            "format for using as a tag name."
        ),
    )

    use_distribution_credentials = Bool(
        title=_("Use Distribution credentials"),
        required=True,
        readonly=True,
        description=_(
            "Use the credentials on a Distribution for " "registry upload"
        ),
    )

    subscriptions = CollectionField(
        title=_("OCIRecipeSubscriptions associated with this OCI recipe."),
        readonly=True,
        value_type=Reference(Interface),
    )

    subscribers = CollectionField(
        title=_("Persons subscribed to this snap recipe."),
        readonly=True,
        value_type=Reference(IPerson),
    )

    def requestBuild(requester, architecture):
        """Request that the OCI recipe is built.

        Please, note that this method does not associate the created build
        with an OCIRecipeBuildRequest. So, prefer using the
        OCIRecipe.requestBuilds (plural).

        :param requester: The person requesting the build.
        :param architecture: The architecture to build for.
        :return: `IOCIRecipeBuild`.
        """

    @call_with(requester=REQUEST_USER)
    @export_factory_operation(IOCIRecipeBuildRequest, [])
    @operation_for_version("devel")
    def requestBuilds(requester, architectures=None):
        """Request that the OCI recipe is built for all available
        architectures.

        :param requester: The person requesting the build.
        :return: A `IOCIRecipeBuildRequest` instance.
        """

    def requestBuildsFromJob(requester, architectures=None):
        """Synchronous part of requesting builds, that should be called as a
        Celery task.

        :param requester: The person requesting the build.
        :return: A list of created IOCIRecipeBuild objects.
        """

    def getBuildRequest(job_id):
        """Get an OCIRecipeBuildRequest object for the given job_id."""

    def getAllowedInformationTypes(user):
        """Get a list of acceptable `InformationType`s for this OCI recipe.

        If the user is a Launchpad admin, any type is acceptable.
        """

    def userCanBeSubscribed(user):
        """Checks if a user can be subscribed to the current OCI recipe."""

    def visibleByUser(user):
        """Can the specified user see this snap recipe?"""

    def getSubscription(person):
        """Returns the OCIRecipeSubscription for the given user."""

    def subscribe(person, subscribed_by):
        """Subscribe a person to this snap recipe."""

    def unsubscribe(person, unsubscribed_by):
        """Unsubscribe a person to this snap recipe."""


class IOCIRecipeEdit(IWebhookTarget):
    """`IOCIRecipe` methods that require launchpad.Edit permission."""

    def destroySelf():
        """Delete this OCI recipe, provided that it has no builds."""

    @call_with(registrant=REQUEST_USER)
    @operation_parameters(
        registry_url=TextLine(
            title=_("Registry URL"),
            description=_("URL for the target registry"),
            required=True,
        ),
        image_name=TextLine(
            title=_("Image name"),
            description=_("Name of the image to push to on the registry"),
            required=True,
        ),
        credentials=Dict(
            title=_("Registry credentials"),
            description=_(
                "The credentials to use in pushing the image to the registry"
            ),
            required=True,
        ),
        credentials_owner=PersonChoice(
            title=_("Registry credentials owner"),
            required=False,
            vocabulary="AllUserTeamsParticipationPlusSelf",
        ),
    )
    # Really IOCIPushRule, patched in lp.oci.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("devel")
    def newPushRule(
        registrant,
        registry_url,
        image_name,
        credentials,
        credentials_owner=None,
    ):
        """Add a new rule for pushing builds of this recipe to a registry."""


class IOCIRecipeEditableAttributes(IHasOwner):
    """`IOCIRecipe` attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    name = exported(
        TextLine(
            title=_("Name"),
            description=_("The name of this recipe."),
            constraint=name_validator,
            required=True,
            readonly=False,
        )
    )

    owner = exported(
        PersonChoice(
            title=_("Owner"),
            required=True,
            vocabulary="AllUserTeamsParticipationPlusSelf",
            description=_("The owner of this OCI recipe."),
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
                "The type of information contained in this OCI recipe."
            ),
        )
    )

    oci_project = exported(
        Reference(
            IOCIProject,
            title=_("OCI project"),
            description=_("The OCI project that this recipe is for."),
            required=True,
            readonly=True,
        )
    )

    git_ref = exported(
        Reference(
            IGitRef,
            title=_("Git branch"),
            required=True,
            readonly=False,
            description=_(
                "The Git branch containing a Dockerfile at the location "
                "defined by the build_file attribute."
            ),
        )
    )

    git_repository = ReferenceChoice(
        title=_("Git repository"),
        schema=IGitRepository,
        vocabulary="GitRepository",
        required=False,
        readonly=False,
        description=_(
            "A Git repository with a branch containing a Dockerfile "
            "at the location defined by the build_file attribute."
        ),
    )

    git_path = TextLine(
        title=_("Git branch path"),
        required=True,
        readonly=False,
        description=_(
            "The path of the Git branch containing a Dockerfile "
            "at the location defined by the build_file attribute."
        ),
    )

    description = exported(
        Text(
            title=_("Description"),
            description=_("A short description of this recipe."),
            required=False,
            readonly=False,
        )
    )

    build_file = exported(
        TextLine(
            title=_("Build file path"),
            description=_(
                "The relative path to the file within this recipe's "
                "branch that defines how to build the recipe."
            ),
            constraint=path_does_not_escape,
            required=True,
            readonly=False,
        )
    )

    build_args = exported(
        Dict(
            title=_("Build ARG variables"),
            description=_(
                "The dictionary of ARG variables to be used when "
                "building this recipe."
            ),
            key_type=TextLine(title=_("ARG name")),
            value_type=TextLine(title=_("ARG value")),
            required=False,
            readonly=False,
        )
    )

    build_path = exported(
        TextLine(
            title=_("Build directory context"),
            description=_(
                "Directory to use for build context "
                "and OCIRecipe.build_file location."
            ),
            constraint=path_does_not_escape,
            required=True,
            readonly=False,
        )
    )

    build_daily = exported(
        Bool(
            title=_("Build daily"),
            required=True,
            default=False,
            description=_("If True, this recipe should be built daily."),
            readonly=False,
        )
    )

    image_name = exported(
        TextLine(
            title=_("Image name"),
            description=_(
                "Image name to use on upload to registry. "
                "Defaults to recipe name if not set. "
                "Only used when Distribution credentials are set."
            ),
            required=False,
            readonly=False,
        )
    )


class IOCIRecipeAdminAttributes(Interface):
    """`IOCIRecipe` attributes that can be edited by admins.

    These attributes need launchpad.View to see, and launchpad.Admin to change.
    """

    require_virtualized = Bool(
        title=_("Require virtualized builders"),
        required=True,
        readonly=False,
        description=_("Only build this OCI recipe on virtual builders."),
    )

    processors = exported(
        CollectionField(
            title=_("Processors"),
            description=_(
                "The architectures for which the OCI recipe should be built."
            ),
            value_type=Reference(schema=IProcessor),
            readonly=False,
        )
    )

    allow_internet = exported(
        Bool(
            title=_("Allow external network access"),
            required=True,
            readonly=False,
            description=_(
                "Allow access to external network resources via a proxy.  "
                "Resources hosted on Launchpad itself are always allowed."
            ),
        )
    )


@exported_as_webservice_entry(
    publish_web_link=True, as_of="devel", singular_name="oci_recipe"
)
class IOCIRecipe(
    IOCIRecipeView,
    IOCIRecipeEdit,
    IOCIRecipeEditableAttributes,
    IOCIRecipeAdminAttributes,
):
    """A recipe for building Open Container Initiative images."""


class IOCIRecipeSet(Interface):
    """A utility to create and access OCI Recipes."""

    def new(
        name,
        registrant,
        owner,
        oci_project,
        git_ref,
        build_file,
        description=None,
        official=False,
        require_virtualized=True,
        build_daily=False,
        processors=None,
        date_created=DEFAULT,
        allow_internet=True,
        build_args=None,
        information_type=InformationType.PUBLIC,
    ):
        """Create an IOCIRecipe."""

    def exists(owner, oci_project, name):
        """Check to see if an existing OCI Recipe exists."""

    def findByIds(ocirecipe_ids, visible_by_user=None):
        """Returns the OCI recipes with the given IDs."""

    def getByName(owner, oci_project, name):
        """Return the appropriate `OCIRecipe` for the given objects."""

    def findByOwner(owner):
        """Return all OCI Recipes with the given `owner`."""

    def findByOCIProject(oci_project, visible_by_user=None):
        """Return all OCI recipes with the given `oci_project`."""

    def findByContext(context, visible_by_user=None):
        """Returns all OCI recipes for a given context."""

    def preloadDataForOCIRecipes(recipes, user):
        """Load the data related to a list of OCI Recipes."""

    def findByGitRepository(repository, paths=None):
        """Return all OCI recipes for the given Git repository.

        :param repository: An `IGitRepository`.
        :param paths: If not None, only return OCI recipes for one of
            these Git reference paths.
        """

    def detachFromGitRepository(repository):
        """Detach all OCI recipes from the given Git repository.

        After this, any OCI recipes that previously used this repository
        will have no source and so cannot dispatch new builds.
        """

    def getStatusSummaryForBuilds(builds):
        """Return a summary of the build status for the given builds.

        The returned summary includes a status, a description of
        that status and the builds related to the status.

        :param builds: A list of build records.
        :type builds: ``list``
        :return: A dict consisting of the build status summary for the
            given builds. For example:
                {
                    'status': BuildSetStatus.FULLYBUILT,
                    'builds': [build1, build2]
                }
            or, an example where there are currently some builds building:
                {
                    'status': BuildSetStatus.BUILDING,
                    'builds':[build3]
                }
        :rtype: ``dict``.
        """
