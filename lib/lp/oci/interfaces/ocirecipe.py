# Copyright 2019 Canonical Ltd.  This software is licensed under the
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
    'NoSuchOCIRecipe',
    'NoSourceForOCIRecipe',
    'OCIRecipeBuildAlreadyPending',
    'OCIRecipeNotOwner',
    ]

import httplib

from lazr.restful.declarations import error_status
from lazr.restful.fields import (
    CollectionField,
    Reference,
    )
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
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.role import IHasOwner
from lp.services.fields import (
    PersonChoice,
    PublicPersonChoice,
    )


@error_status(httplib.UNAUTHORIZED)
class OCIRecipeNotOwner(Unauthorized):
    """The registrant/requester is not the owner or a member of its team."""


@error_status(httplib.BAD_REQUEST)
class OCIRecipeBuildAlreadyPending(Exception):
    """A build was requested when an identical build was already pending."""

    def __init__(self):
        super(OCIRecipeBuildAlreadyPending, self).__init__(
            "An identical build of this snap package is already pending.")


@error_status(httplib.BAD_REQUEST)
class DuplicateOCIRecipeName(Exception):
    """An OCI Recipe already exists with the same name."""


class NoSuchOCIRecipe(NameLookupFailed):
    """The requested OCI Recipe does not exist."""
    _message_prefix = "No such OCI Recipe exists for this OCI Project"


@error_status(httplib.BAD_REQUEST)
class NoSourceForOCIRecipe(Exception):
    """OCI Recipes must have a source and build file."""

    def __init__(self):
        super(NoSourceForOCIRecipe, self).__init__(
            "New OCI Recipes must have a git branch and build file.")


class IOCIRecipeView(Interface):
    """`IOCIRecipe` attributes that require launchpad.View permission."""

    id = Int(title=_("ID"), required=True, readonly=True)
    date_created = Datetime(
        title=_("Date created"), required=True, readonly=True)
    date_last_modified = Datetime(
        title=_("Date last modified"), required=True, readonly=True)

    registrant = PublicPersonChoice(
        title=_("Registrant"),
        description=_("The user who registered this recipe."),
        vocabulary='ValidPersonOrTeam', required=True, readonly=True)

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


class IOCIRecipeEdit(Interface):
    """`IOCIRecipe` methods that require launchpad.Edit permission."""

    def destroySelf():
        """Delete this OCI recipe, provided that it has no builds."""


class IOCIRecipeEditableAttributes(IHasOwner):
    """`IOCIRecipe` attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    name = TextLine(
        title=_("The name of this recipe."),
        constraint=name_validator,
        required=True)

    owner = PersonChoice(
        title=_("Owner"), required=True, readonly=False,
        vocabulary="AllUserTeamsParticipationPlusSelf",
        description=_("The owner of this OCI recipe."))

    oci_project = Reference(
        IOCIProject,
        title=_("The OCI project that this recipe is for."),
        required=True,
        readonly=True)

    official = Bool(
        title=_("OCI Project Official"), required=True, default=False,
        description=_("True if this recipe is official for its OCI project."))

    git_repository = Reference(
        IGitRepository,
        title=_("A Git repository with a branch containing an OCI recipe."))

    description = Text(title=_("A short description of this recipe."))

    git_path = TextLine(
        title=_("The branch within this recipe's Git "
                "repository where its build files are maintained."),
        required=True)

    build_file = TextLine(
        title=_("The relative path to the file within this recipe's "
                "branch that defines how to build the recipe."),
        constraint=path_does_not_escape,
        required=True)

    require_virtualized = Bool(
        title=_("Require virtualized"), required=True, default=True)

    build_daily = Bool(
        title=_("Build daily"), required=True, default=False,
        description=_("If True, this recipe should be built daily."))


class IOCIRecipe(IOCIRecipeView, IOCIRecipeEdit, IOCIRecipeEditableAttributes):
    """A recipe for building Open Container Initiative images."""


class IOCIRecipeSet(Interface):
    """A utility to create and access OCI Recipes."""

    def new(name, registrant, owner, oci_project, description, official,
            require_virtualized, git_repository, git_path, build_file):
        """Create an IOCIRecipe."""

    def exists(oci_project, name):
        """Check to see if an existing OCI Recipe exists."""

    def getByName(oci_project, name):
        """Return the appropriate `OCIRecipe` for the given objects."""
