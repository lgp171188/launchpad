# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for handling credentials for OCI registry actions."""

__all__ = [
    "IOCIPushRule",
    "IOCIPushRuleSet",
    "OCIPushRuleAlreadyExists",
]

import http.client

from lazr.restful.declarations import (
    error_status,
    export_destructor_operation,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    mutator_for,
    operation_for_version,
    operation_parameters,
)
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import Int, TextLine

from lp import _
from lp.oci.interfaces.ocirecipe import IOCIRecipe
from lp.oci.interfaces.ociregistrycredentials import IOCIRegistryCredentials


@error_status(http.client.CONFLICT)
class OCIPushRuleAlreadyExists(Exception):
    """A new OCIPushRuleAlreadyExists was added with the
    same details as an existing one.
    """

    def __init__(self):
        super().__init__(
            "A push rule already exists with the same URL, image name, "
            "and credentials"
        )


class IOCIPushRuleView(Interface):
    """`IOCIPushRule` methods that require launchpad.View
    permission.
    """

    id = Int(title=_("ID"), required=False, readonly=True)

    registry_url = exported(
        TextLine(
            title=_("Registry URL"),
            description=_(
                "The registry URL for the credentials of this push rule"
            ),
            required=True,
            readonly=True,
        )
    )

    username = exported(
        TextLine(
            title=_("Username"),
            description=_("The username for the credentials, if available."),
            required=True,
            readonly=True,
        )
    )


class IOCIPushRuleEditableAttributes(Interface):
    """`IOCIPushRule` attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    recipe = Reference(
        IOCIRecipe,
        title=_("OCI recipe"),
        description=_("The recipe for which the rule is defined."),
        required=True,
        readonly=False,
    )

    registry_credentials = Reference(
        IOCIRegistryCredentials,
        title=_("Registry credentials"),
        description=_("The registry credentials to use."),
        required=True,
        readonly=False,
    )

    image_name = exported(
        TextLine(
            title=_("Image name"),
            description=_("The intended name of the image on the registry."),
            required=True,
            readonly=True,
        )
    )

    @mutator_for(image_name)
    @operation_parameters(
        image_name=TextLine(title=_("Image name"), required=True)
    )
    @export_write_operation()
    @operation_for_version("devel")
    def setNewImageName(image_name):
        """Set the new image name, checking for uniqueness."""


class IOCIPushRuleEdit(Interface):
    """`IOCIPushRule` methods that require launchpad.Edit
    permission.
    """

    @export_destructor_operation()
    @operation_for_version("devel")
    def destroySelf():
        """Destroy this push rule."""


@exported_as_webservice_entry(
    publish_web_link=True, as_of="devel", singular_name="oci_push_rule"
)
class IOCIPushRule(
    IOCIPushRuleEdit, IOCIPushRuleEditableAttributes, IOCIPushRuleView
):
    """A rule for pushing builds of an OCI recipe to a registry."""


class IOCIPushRuleSet(Interface):
    """A utility to create and access OCI Push Rules."""

    def new(recipe, registry_credentials, image_name):
        """Create an `IOCIPushRule`."""

    def findByRecipe(self, recipe):
        """Find matching `IOCIPushRule`s by recipe."""

    def findByRegistryCredentials(self, credentials):
        """Find matching `IOCIPushRule` by credentials."""

    def getByID(id):
        """Get a single `IOCIPushRule` by its ID."""
