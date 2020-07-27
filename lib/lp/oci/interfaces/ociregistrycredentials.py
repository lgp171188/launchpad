# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for handling credentials for OCI registry actions."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIRegistryCredentials',
    'IOCIRegistryCredentialsSet',
    'OCIRegistryCredentialsAlreadyExist',
    ]

from lazr.restful.declarations import error_status
from six.moves import http_client
from zope.interface import Interface
from zope.schema import (
    Int,
    TextLine,
    )

from lp import _
from lp.registry.interfaces.role import IHasOwner
from lp.services.fields import (
    PersonChoice,
    URIField,
    )


@error_status(http_client.CONFLICT)
class OCIRegistryCredentialsAlreadyExist(Exception):
    """A new `OCIRegistryCredentials` was added with the
    same details as an existing one.
    """

    def __init__(self):
        super(OCIRegistryCredentialsAlreadyExist, self).__init__(
            "Credentials already exist with the same URL and username.")


class IOCIRegistryCredentialsView(Interface):

    id = Int(title=_("ID"), required=True, readonly=True)

    def getCredentials():
        """Get the saved credentials."""

    username = TextLine(
        title=_("Username"),
        description=_("The username for the credentials, if available."),
        required=True,
        readonly=True)


class IOCIRegistryCredentialsEditableAttributes(IHasOwner):

    owner = PersonChoice(
        title=_("Owner"),
        required=True,
        vocabulary="AllUserTeamsParticipationPlusSelf",
        description=_("The owner of these credentials. "
                      "Only the owner is entitled to create "
                      "push rules using them."),
        readonly=False)

    url = URIField(
        allowed_schemes=['http', 'https'],
        title=_("URL"),
        description=_("The registry URL."),
        required=True,
        readonly=False)


class IOCIRegistryCredentialsEdit(Interface):
    """`IOCIRegistryCredentials` methods that require launchpad.Edit
    permission.
    """

    def setCredentials(value):
        """Set the credentials to be encrypted and saved."""

    def destroySelf():
        """Delete these credentials."""


class IOCIRegistryCredentials(IOCIRegistryCredentialsEdit,
                              IOCIRegistryCredentialsEditableAttributes,
                              IOCIRegistryCredentialsView):
    """Credentials for pushing to an OCI registry."""


class IOCIRegistryCredentialsSet(Interface):
    """A utility to create and access OCI Registry Credentials."""

    def new(owner, url, credentials):
        """Create an `IOCIRegistryCredentials`."""

    def getOrCreate(owner, url, credentials):
        """Get an `IOCIRegistryCredentials` that match the url and username
        or create a new object."""

    def findByOwner(owner):
        """Find matching `IOCIRegistryCredentials` by owner."""
