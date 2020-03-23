# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for handling credentials for OCI registry actions."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIPushRule',
    'IOCIPushRuleSet'
    ]

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import (
    Int,
    TextLine,
    )

from lp import _
from lp.oci.interfaces.ocirecipe import IOCIRecipe
from lp.oci.interfaces.ociregistrycredentials import IOCIRegistryCredentials


class IOCIPushRuleView(Interface):
<<<<<<< 16ae97a6453c1c6d4e298ff58b1cc50a78f4b326
    """`IOCIPushRule` methods that require launchpad.View
=======
    """`IOCIPushRule` methods that required launchpad.View
>>>>>>> Add OCIPushRule model
    permission.
    """

    id = Int(title=_("ID"), required=True, readonly=True)


class IOCIPushRuleEditableAttributes(Interface):
    """`IOCIPushRule` attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    recipe = Reference(
        IOCIRecipe,
        title=_("OCI recipe"),
        description=_("The recipe for which the rule is defined."),
        required=True,
        readonly=False)

    registry_credentials = Reference(
        IOCIRegistryCredentials,
        title=_("Registry credentials"),
        description=_("The registry credentials to use."),
        required=True,
        readonly=False)

    image_name = TextLine(
        title=_("Image name"),
        description=_("The intended name of the image on the registry."),
        required=True,
        readonly=False)


class IOCIPushRuleEdit(Interface):
    """`IOCIPushRule` methods that require launchpad.Edit
    permission.
    """

    def destroySelf():
        """Destroy this push rule."""


class IOCIPushRule(IOCIPushRuleEdit, IOCIPushRuleEditableAttributes,
                   IOCIPushRuleView):
    """A rule for pushing builds of an OCI recipe to a registry."""


class IOCIPushRuleSet(Interface):
    """A utility to create and access OCI Push Rules."""

    def new(recipe, registry_credentials, image_name):
<<<<<<< 16ae97a6453c1c6d4e298ff58b1cc50a78f4b326
        """Create an `IOCIPushRule`."""
=======
        """Create an `IOCIRPushRule`."""
>>>>>>> Add OCIPushRule model
