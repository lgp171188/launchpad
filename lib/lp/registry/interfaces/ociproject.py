# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Project interfaces."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIProject',
    'IOCIProjectSet',
    'OCI_PROJECT_ALLOW_CREATE',
    'OCIProjectCreateFeatureDisabled',
    ]

from lazr.restful.declarations import (
    call_with,
    error_status,
    export_factory_operation,
    exported,
    exported_as_webservice_entry,
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
from zope.interface import Interface
from zope.schema import (
    Bool,
    Datetime,
    Dict,
    Int,
    Text,
    TextLine,
    )
from zope.security.interfaces import Unauthorized

from lp import _
from lp.app.validators.name import name_validator
from lp.app.validators.path import path_does_not_escape
from lp.bugs.interfaces.bugtarget import IBugTarget
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.hasgitrepositories import IHasGitRepositories
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.ociprojectname import IOCIProjectName
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.series import SeriesStatus
from lp.services.database.constants import DEFAULT
from lp.services.fields import (
    PersonChoice,
    PublicPersonChoice,
    )


OCI_PROJECT_ALLOW_CREATE = 'oci.project.create.enabled'


class IOCIProjectView(IHasGitRepositories, Interface):
    """IOCIProject attributes that require launchpad.View permission."""

    id = Int(title=_("ID"), required=True, readonly=True)
    date_created = exported(Datetime(
        title=_("Date created"), required=True, readonly=True))
    date_last_modified = exported(Datetime(
        title=_("Date last modified"), required=True, readonly=True))

    registrant = exported(PublicPersonChoice(
        title=_("Registrant"),
        description=_("The person that registered this project."),
        vocabulary='ValidPersonOrTeam', required=True, readonly=True))

    series = exported(CollectionField(
        title=_("Series inside this OCI project."),
        # Really IOCIProjectSeries
        value_type=Reference(schema=Interface)))

    display_name = exported(TextLine(
        title=_("Display name for this OCI project."),
        required=True, readonly=True))

    def getSeriesByName(name):
        """Get an OCIProjectSeries for this OCIProject by series' name."""

    def getRecipeByNameAndOwner(recipe_name, owner_name, visible_by_user=None):
        """Returns the exact match search for recipe_name AND owner_name."""

    def getRecipes(visible_by_user=None):
        """Returns the set of OCI recipes for this project."""

    def searchRecipes(query, visible_by_user=None):
        """Searches for recipes in this OCI project."""

    def getOfficialRecipes(visible_by_user=None):
        """Gets the official recipes for this OCI project."""

    def getUnofficialRecipes(visible_by_user=None):
        """Gets the unofficial recipes for this OCI project."""

    def getAllowedInformationTypes(user):
        """Get a list of acceptable `InformationType`s for for OCI recipes
        of this OCI project.

        If the user is a Launchpad admin, any type is acceptable.
        """

    def getDefaultGitRepository(person):
        """Returns the default git repository for the given user under the
        namespace of this OCI project"""

    def getDefaultGitRepositoryPath(person):
        """Returns the default git repository path for this OCI Project,
        regardless if the repository exists or not.
        """


class IOCIProjectEditableAttributes(IBugTarget):
    """IOCIProject attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    distribution = exported(ReferenceChoice(
        title=_("The distribution that this OCI project is associated with."),
        schema=IDistribution, vocabulary="Distribution",
        required=False, readonly=False))
    project = exported(ReferenceChoice(
        title=_('The project that this OCI project is associated with.'),
        schema=IProduct, vocabulary='Product',
        required=False, readonly=False))
    name = exported(TextLine(
        title=_("Name"), required=True, readonly=False,
        constraint=name_validator,
        description=_("The name of this OCI project.")))
    ociprojectname = Reference(
        IOCIProjectName,
        title=_("The name of this OCI project, as an `IOCIProjectName`."),
        required=True,
        readonly=True)
    description = exported(Text(
        title=_("The description for this OCI project."),
        required=True, readonly=False))
    pillar = Reference(
        Interface,
        title=_("The pillar containing this target."),
        required=True, readonly=False)


class IOCIProjectEdit(Interface):
    """IOCIProject attributes that require launchpad.Edit permission."""

    def newSeries(name, summary, registrant,
                  status=SeriesStatus.DEVELOPMENT, date_created=DEFAULT):
        """Creates a new `IOCIProjectSeries`."""

    def setOfficialRecipeStatus(recipe, status):
        """Change whether an OCI Recipe is official or not for this project."""


class IOCIProjectLegitimate(Interface):
    """IOCIProject methods that require launchpad.AnyLegitimatePerson
    permission.
    """
    @call_with(registrant=REQUEST_USER)
    @operation_parameters(
        name=TextLine(
            title=_("OCI Recipe name."),
            description=_("The name of the new OCI Recipe."),
            required=True),
        owner=PersonChoice(
            title=_("Person or team that owns the new OCI Recipe."),
            vocabulary="AllUserTeamsParticipationPlusSelf",
            required=True),
        git_ref=Reference(IGitRef, title=_("Git branch."), required=True),
        build_file=TextLine(
            title=_("Build file path."),
            description=_(
                "The relative path to the file within this recipe's "
                "branch that defines how to build the recipe."),
            constraint=path_does_not_escape,
            required=True),
        build_args=Dict(
            title=_("Build ARGs to be used when building the recipe"),
            description=_(
                "A dict of VARIABLE=VALUE to be used as ARG when building "
                "the recipe."
            ),
            required=False),
        description=Text(
            title=_("Description for this recipe."),
            description=_("A short description of this recipe."),
            required=False),
        build_daily=Bool(
            title=_("Should this recipe be built daily?."), required=False))
    @export_factory_operation(Interface, [])
    @operation_for_version("devel")
    def newRecipe(name, registrant, owner, git_ref, build_file,
                  description=None, build_daily=False,
                  require_virtualized=True, build_args=None):
        """Create an IOCIRecipe for this project."""


@exported_as_webservice_entry(
    publish_web_link=True, as_of="devel", singular_name="oci_project")
class IOCIProject(IOCIProjectView, IOCIProjectEdit,
                  IOCIProjectEditableAttributes, IOCIProjectLegitimate):
    """A project containing Open Container Initiative recipes."""


class IOCIProjectSet(Interface):
    """A utility to create and access OCI Projects."""

    def new(registrant, pillar, name, date_created=None, description=None,
            bug_reporting_guidelines=None, bug_reported_acknowledgement=None,
            bugfiling_duplicate_search=False):
        """Create an `IOCIProject`."""

    def getByPillarAndName(pillar, name):
        """Get the OCIProjects for a given distribution or project.

        :param pillar: An instance of Distribution or Product, or the
            respective pillar name.
        :param name: The OCIProject name to find.
        :return: The OCIProject found.
        """

    def findByPillarAndName(pillar, name_substring):
        """Find OCIProjects for a given pillar that contain the provided
        name."""

    def searchByName(name_substring):
        """Search OCIProjects that contain the provided name."""

    def preloadDataForOCIProjects(oci_projects):
        """Preload data for the given list of OCIProject objects."""


@error_status(http_client.UNAUTHORIZED)
class OCIProjectCreateFeatureDisabled(Unauthorized):
    """Only certain users can create new OCI Projects."""

    def __init__(self):
        super(OCIProjectCreateFeatureDisabled, self).__init__(
            "You do not have permission to create an OCI project.")
