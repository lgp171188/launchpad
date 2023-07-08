# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for handling credentials for OCI registry actions."""

__all__ = [
    "IOCIRegistryCredentials",
    "IOCIRegistryCredentialsSet",
    "OCIRegistryCredentialsAlreadyExist",
    "OCIRegistryCredentialsNotOwner",
    "user_can_edit_credentials_for_owner",
]

import http.client

from lazr.restful.declarations import error_status
from zope.interface import Interface
from zope.schema import Int, TextLine
from zope.security.interfaces import Unauthorized

from lp import _
from lp.registry.interfaces.role import IHasOwner, IPersonRoles
from lp.services.fields import PersonChoice, URIField


@error_status(http.client.CONFLICT)
class OCIRegistryCredentialsAlreadyExist(Exception):
    """A new `OCIRegistryCredentials` was added with the
    same details as an existing one.
    """

    def __init__(self):
        super().__init__(
            "Credentials already exist with the same URL, username, and "
            "region."
        )


@error_status(http.client.UNAUTHORIZED)
class OCIRegistryCredentialsNotOwner(Unauthorized):
    """The registrant is not the owner or a member of its team."""


class IOCIRegistryCredentialsView(Interface):
    id = Int(title=_("ID"), required=True, readonly=True)

    def getCredentials():
        """Get the saved credentials."""

    username = TextLine(
        title=_("Username"),
        description=_("The username for the credentials, if available."),
        required=True,
        readonly=True,
    )

    region = TextLine(
        title=_("Region"),
        description=_("The registry region, if available."),
        required=False,
        readonly=True,
    )


class IOCIRegistryCredentialsEditableAttributes(IHasOwner):
    owner = PersonChoice(
        title=_("Owner"),
        required=True,
        vocabulary="AllUserTeamsParticipationPlusSelf",
        description=_(
            "The owner of these credentials. "
            "Only the owner is entitled to create "
            "push rules using them."
        ),
        readonly=False,
    )

    url = URIField(
        allowed_schemes=["http", "https"],
        title=_("URL"),
        description=_("The registry URL."),
        required=True,
        readonly=False,
    )


class IOCIRegistryCredentialsEdit(Interface):
    """`IOCIRegistryCredentials` methods that require launchpad.Edit
    permission.
    """

    def setCredentials(value):
        """Set the credentials to be encrypted and saved."""

    def destroySelf():
        """Delete these credentials."""


class IOCIRegistryCredentials(
    IOCIRegistryCredentialsEdit,
    IOCIRegistryCredentialsEditableAttributes,
    IOCIRegistryCredentialsView,
):
    """Credentials for pushing to an OCI registry."""


class IOCIRegistryCredentialsSet(Interface):
    """A utility to create and access OCI Registry Credentials."""

    def new(registrant, owner, url, credentials, override_owner=False):
        """Create an `IOCIRegistryCredentials`."""

    def getOrCreate(registrant, owner, url, credentials, override_owner=False):
        """Get an `IOCIRegistryCredentials` that match the url and username
        or create a new object."""

    def findByOwner(owner):
        """Find matching `IOCIRegistryCredentials` by owner."""


def user_can_edit_credentials_for_owner(owner, user):
    """Can `user` edit OCI registry credentials belonging to `owner`?"""
    if user is None:
        return False
    # This must follow the same rules as
    # ViewOCIRegistryCredentials.checkAuthenticated would apply if we were
    # asking about a hypothetical OCIRegistryCredentials object owned by the
    # context person or team.
    roles = IPersonRoles(user)
    return roles.inTeam(owner) or roles.in_admin
