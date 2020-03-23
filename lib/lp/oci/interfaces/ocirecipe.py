# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces related to recipes for OCI Images."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'DuplicateOCIRecipeName',
    'IOCIRecipe',
    'IOCIRecipeEdit',
    'IOCIRecipeEditableAttributes',
    'IOCIRecipeSet',
    'IOCIRecipeView',
    'NoSourceForOCIRecipe',
    'NoSuchOCIRecipe',
    'OCI_RECIPE_WEBHOOKS_FEATURE_FLAG',
    'OCIRecipeBuildAlreadyPending',
    'OCIRecipeNotOwner',
    ]

from lazr.restful.declarations import (
    error_status,
    export_as_webservice_entry,
    exported,
    )
from lazr.restful.fields import (
    CollectionField,
    Reference,
    ReferenceChoice,
    )
from six.moves import http_client
from zope.interface import Interface
from zope.schema import (
    Bool,
    Datetime,
    Int,
    Text,
    TextLine,
    )
from zope.security.interfaces import Unauthorized

from lp import _
from lp.app.errors import NameLookupFailed
from lp.app.validators.name import name_validator
from lp.app.validators.path import path_does_not_escape
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.role import IHasOwner
from lp.services.database.constants import DEFAULT
from lp.services.fields import (
    PersonChoice,
    PublicPersonChoice,
    )
from lp.services.webhooks.interfaces import IWebhookTarget


OCI_RECIPE_WEBHOOKS_FEATURE_FLAG = "oci.recipe.webhooks.enabled"


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

    push_rules = CollectionField(
        title=_("Push Rules for this OCI recipe."),
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


class IOCIRecipe(IOCIRecipeView, IOCIRecipeEdit, IOCIRecipeEditableAttributes,
                 IOCIRecipeAdminAttributes):
    """A recipe for building Open Container Initiative images."""

    export_as_webservice_entry(
        publish_web_link=True, as_of="devel", singular_name="oci_recipe")


class IOCIRecipeSet(Interface):
    """A utility to create and access OCI Recipes."""

    def new(name, registrant, owner, oci_project, git_ref, build_file,
            description=None, official=False, require_virtualized=True,
            date_created=DEFAULT):
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
