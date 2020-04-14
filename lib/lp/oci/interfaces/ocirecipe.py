# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces related to recipes for OCI Images."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'CannotModifyOCIRecipeProcessor',
    'DuplicateOCIRecipeName',
    'IOCIRecipe',
    'IOCIRecipeBuildRequest',
    'IOCIRecipeEdit',
    'IOCIRecipeEditableAttributes',
    'IOCIRecipeSet',
    'IOCIRecipeView',
    'NoSourceForOCIRecipe',
    'NoSuchOCIRecipe',
    'OCIRecipeBuildAlreadyPending',
    'OCIRecipeFeatureDisabled',
    'OCIRecipeNotOwner',
    'OCI_RECIPE_ALLOW_CREATE',
    'OCI_RECIPE_WEBHOOKS_FEATURE_FLAG',
    ]

from lazr.restful.declarations import (
    call_with,
    error_status,
    export_as_webservice_entry,
    export_factory_operation,
    export_write_operation,
    exported,
    operation_for_version,
    operation_parameters,
    REQUEST_USER,
    )
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
    Int,
    List,
    Text,
    TextLine,
    )
from zope.security.interfaces import Unauthorized

from lp import _
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
from lp.services.fields import (
    PersonChoice,
    PublicPersonChoice,
    )
from lp.services.webhooks.interfaces import IWebhookTarget


OCI_RECIPE_WEBHOOKS_FEATURE_FLAG = "oci.recipe.webhooks.enabled"
OCI_RECIPE_ALLOW_CREATE = 'oci.recipe.create.enabled'


@error_status(http_client.UNAUTHORIZED)
class OCIRecipeFeatureDisabled(Unauthorized):
    """Only certain users can create new LiveFS-related objects."""

    def __init__(self):
        super(OCIRecipeFeatureDisabled, self).__init__(
            "You do not have permission to create new OCI recipe.")


@error_status(http_client.UNAUTHORIZED)
class OCIRecipeNotOwner(Unauthorized):
    """The registrant/requester is not the owner or a member of its team."""


@error_status(http_client.BAD_REQUEST)
class OCIRecipeBuildAlreadyPending(Exception):
    """A build was requested when an identical build was already pending."""

    def __init__(self):
        super(OCIRecipeBuildAlreadyPending, self).__init__(
            "An identical build of this OCI recipe is already pending.")


@error_status(http_client.BAD_REQUEST)
class DuplicateOCIRecipeName(Exception):
    """An OCI Recipe already exists with the same name."""


class NoSuchOCIRecipe(NameLookupFailed):
    """The requested OCI Recipe does not exist."""
    _message_prefix = "No such OCI recipe exists for this OCI project"


@error_status(http_client.BAD_REQUEST)
class NoSourceForOCIRecipe(Exception):
    """OCI Recipes must have a source and build file."""

    def __init__(self):
        super(NoSourceForOCIRecipe, self).__init__(
            "New OCI recipes must have a git branch and build file.")


@error_status(http_client.FORBIDDEN)
class CannotModifyOCIRecipeProcessor(Exception):
    """Tried to enable or disable a restricted processor on an OCI recipe."""

    _fmt = (
        '%(processor)s is restricted, and may only be enabled or disabled '
        'by administrators.')

    def __init__(self, processor):
        super(CannotModifyOCIRecipeProcessor, self).__init__(
            self._fmt % {'processor': processor.name})


class IOCIRecipeBuildRequest(Interface):
    """A request to build an OCI Recipe."""
    export_as_webservice_entry(
        publish_web_link=True, as_of="devel",
        singular_name="oci_recipe_build_request")

    id = Int(title=_("ID"), required=True, readonly=True)

    date_requested = exported(Datetime(
        title=_("The time when this request was made"),
        required=True, readonly=True))

    date_finished = exported(Datetime(
        title=_("The time when this request finished"),
        required=False, readonly=True))

    requester = exported(Reference(
        IPerson, title=_("The IPerson that requested this build"),
        required=True, readonly=True))

    oci_recipe = exported(Reference(
        # Really IOCIRecipe, patched in _schema_circular_imports.
        Interface,
        title=_("OCI Recipe"), required=True, readonly=True))

    status = exported(Choice(
        title=_("Status"), vocabulary=OCIRecipeBuildRequestStatus,
        required=True, readonly=True))

    error_message = exported(TextLine(
        title=_("Error message"), required=True, readonly=True))

    builds = exported(CollectionField(
        title=_("Builds produced by this request"),
        # Really IOCIRecipeBuild, patched in _schema_circular_imports.
        value_type=Reference(schema=Interface),
        required=True, readonly=True))


class IOCIRecipeView(Interface):
    """`IOCIRecipe` attributes that require launchpad.View permission."""

    id = Int(title=_("ID"), required=True, readonly=True)
    date_created = exported(Datetime(
        title=_("Date created"), required=True, readonly=True))
    date_last_modified = exported(Datetime(
        title=_("Date last modified"), required=True, readonly=True))

    registrant = exported(PublicPersonChoice(
        title=_("Registrant"),
        description=_("The user who registered this recipe."),
        vocabulary='ValidPersonOrTeam', required=True, readonly=True))

    distribution = Reference(
        IDistribution, title=_("Distribution"),
        required=True, readonly=True,
        description=_("The distribution that this recipe is associated with."))

    distro_series = Reference(
        IDistroSeries, title=_("Distro series"),
        required=True, readonly=True,
        description=_("The series for which the recipe should be built."))

    available_processors = Attribute(
        "The architectures that are available to be enabled or disabled for "
        "this OCI recipe.")

    @call_with(check_permissions=True, user=REQUEST_USER)
    @operation_parameters(
        processors=List(
            value_type=Reference(schema=IProcessor), required=True))
    @export_write_operation()
    @operation_for_version("devel")
    def setProcessors(processors, check_permissions=False, user=None):
        """Set the architectures for which the recipe should be built."""

    def getAllowedArchitectures():
        """Return all distroarchseries that this recipe can build for.

        :return: Sequence of `IDistroArchSeries` instances.
        """

    builds = CollectionField(
        title=_("Completed builds of this OCI recipe."),
        description=_(
            "Completed builds of this OCI recipe, sorted in descending "
            "order of finishing."),
        # Really IOCIRecipeBuild, patched in _schema_circular_imports.
        value_type=Reference(schema=Interface),
        required=True, readonly=True)

    completed_builds = CollectionField(
        title=_("Completed builds of this OCI recipe."),
        description=_(
            "Completed builds of this OCI recipe, sorted in descending "
            "order of finishing."),
        # Really IOCIRecipeBuild, patched in _schema_circular_imports.
        value_type=Reference(schema=Interface), readonly=True)

    pending_builds = CollectionField(
        title=_("Pending builds of this OCI recipe."),
        description=_(
            "Pending builds of this OCI recipe, sorted in descending "
            "order of creation."),
        # Really IOCIRecipeBuild, patched in _schema_circular_imports.
        value_type=Reference(schema=Interface), readonly=True)

    def requestBuild(requester, architecture):
        """Request that the OCI recipe is built.

        :param requester: The person requesting the build.
        :param architecture: The architecture to build for.
        :return: `IOCIRecipeBuild`.
        """

    @call_with(requester=REQUEST_USER)
    @export_factory_operation(IOCIRecipeBuildRequest, [])
    @operation_for_version("devel")
    def requestBuilds(requester):
        """Request that the OCI recipe is built for all available
        architectures.

        :param requester: The person requesting the build.
        :return: A `IOCIRecipeBuildRequest` instance.
        """

    def getBuildRequest(job_id):
        """Get a OCIRecipeBuildRequest object for the given job_id.
        """

    push_rules = CollectionField(
        title=_("Push rules for this OCI recipe."),
        description=_("All of the push rules for registry upload "
                      "that apply to this recipe."),
        # Really IOCIPushRule, patched in _schema_cirular_imports.
        value_type=Reference(schema=Interface), readonly=True)


class IOCIRecipeEdit(IWebhookTarget):
    """`IOCIRecipe` methods that require launchpad.Edit permission."""

    def destroySelf():
        """Delete this OCI recipe, provided that it has no builds."""


class IOCIRecipeEditableAttributes(IHasOwner):
    """`IOCIRecipe` attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    name = exported(TextLine(
        title=_("Name"),
        description=_("The name of this recipe."),
        constraint=name_validator,
        required=True,
        readonly=False))

    owner = exported(PersonChoice(
        title=_("Owner"),
        required=True,
        vocabulary="AllUserTeamsParticipationPlusSelf",
        description=_("The owner of this OCI recipe."),
        readonly=False))

    oci_project = exported(Reference(
        IOCIProject,
        title=_("OCI project"),
        description=_("The OCI project that this recipe is for."),
        required=True,
        readonly=True))

    official = Bool(
        title=_("OCI project official"),
        required=True,
        default=False,
        description=_("True if this recipe is official for its OCI project."),
        readonly=False)

    git_ref = exported(Reference(
        IGitRef, title=_("Git branch"), required=True, readonly=False,
        description=_(
            "The Git branch containing a Dockerfile at the location "
            "defined by the build_file attribute.")))

    git_repository = ReferenceChoice(
        title=_("Git repository"),
        schema=IGitRepository, vocabulary="GitRepository",
        required=False, readonly=False,
        description=_(
            "A Git repository with a branch containing a Dockerfile "
            "at the location defined by the build_file attribute."))

    git_path = TextLine(
        title=_("Git branch path"), required=True, readonly=False,
        description=_(
            "The path of the Git branch containing a Dockerfile "
            "at the location defined by the build_file attribute."))

    description = exported(Text(
        title=_("Description"),
        description=_("A short description of this recipe."),
        required=False,
        readonly=False))

    build_file = exported(TextLine(
        title=_("Build file path"),
        description=_("The relative path to the file within this recipe's "
                      "branch that defines how to build the recipe."),
        constraint=path_does_not_escape,
        required=True,
        readonly=False))

    build_daily = exported(Bool(
        title=_("Build daily"),
        required=True,
        default=False,
        description=_("If True, this recipe should be built daily."),
        readonly=False))


class IOCIRecipeAdminAttributes(Interface):
    """`IOCIRecipe` attributes that can be edited by admins.

    These attributes need launchpad.View to see, and launchpad.Admin to change.
    """

    require_virtualized = Bool(
        title=_("Require virtualized builders"), required=True, readonly=False,
        description=_("Only build this OCI recipe on virtual builders."))

    processors = exported(CollectionField(
        title=_("Processors"),
        description=_(
            "The architectures for which the OCI recipe should be built."),
        value_type=Reference(schema=IProcessor),
        readonly=False))


class IOCIRecipe(IOCIRecipeView, IOCIRecipeEdit, IOCIRecipeEditableAttributes,
                 IOCIRecipeAdminAttributes):
    """A recipe for building Open Container Initiative images."""

    export_as_webservice_entry(
        publish_web_link=True, as_of="devel", singular_name="oci_recipe")


class IOCIRecipeSet(Interface):
    """A utility to create and access OCI Recipes."""

    def new(name, registrant, owner, oci_project, git_ref, build_file,
            description=None, official=False, require_virtualized=True,
            build_daily=False, processors=None, date_created=DEFAULT):
        """Create an IOCIRecipe."""

    def exists(owner, oci_project, name):
        """Check to see if an existing OCI Recipe exists."""

    def getByName(owner, oci_project, name):
        """Return the appropriate `OCIRecipe` for the given objects."""

    def findByOwner(owner):
        """Return all OCI Recipes with the given `owner`."""

    def findByOCIProject(oci_project):
        """Return all OCI recipes with the given `oci_project`."""

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
