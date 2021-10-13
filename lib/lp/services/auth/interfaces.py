# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Personal access token interfaces."""

__metaclass__ = type
__all__ = [
    "IAccessToken",
    "IAccessTokenSet",
    "IAccessTokenVerifiedRequest",
    ]

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import (
    Bool,
    Choice,
    Datetime,
    Int,
    List,
    TextLine,
    )

from lp import _
from lp.code.interfaces.gitrepository import IGitRepository
from lp.services.auth.enums import AccessTokenScope
from lp.services.fields import PublicPersonChoice


class IAccessToken(Interface):
    """A personal access token for the webservice API."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_created = Datetime(
        title=_("When the token was created."), required=True, readonly=True)

    owner = PublicPersonChoice(
        title=_("The person who created the token."),
        vocabulary="ValidPersonOrTeam", required=True, readonly=True)

    description = TextLine(
        title=_("A short description of the token."), required=True)

    git_repository = Reference(
        title=_("The Git repository for which the token was issued."),
        schema=IGitRepository, required=True, readonly=True)

    scopes = List(
        value_type=Choice(vocabulary=AccessTokenScope),
        title=_("A list of scopes granted by the token."),
        required=True, readonly=True)

    date_last_used = Datetime(
        title=_("When the token was last used."),
        required=False, readonly=False)

    date_expires = Datetime(
        title=_("When the token should expire or was revoked."),
        required=False, readonly=False)

    is_expired = Bool(
        title=_("Whether this token has expired."),
        required=False, readonly=True)

    revoked_by = PublicPersonChoice(
        title=_("The person who revoked the token, if any."),
        vocabulary="ValidPersonOrTeam", required=False, readonly=False)

    def updateLastUsed():
        """Update this token's last-used date, if possible."""

    def revoke(revoked_by):
        """Revoke this token."""


class IAccessTokenSet(Interface):
    """The set of all personal access tokens."""

    def new(secret, owner, description, target, scopes):
        """Return a new access token with a given secret.

        :param secret: A text string.
        :param owner: An `IPerson` who is creating the token.
        :param description: A short description of the token.
        :param target: An `IAccessTokenTarget` for which the token is being
            issued.
        :param scopes: A list of `AccessTokenScope`s to be granted by the
            token.
        """

    def getBySecret(secret):
        """Return the access token with this secret, or None.

        :param secret: A text string.
        """

    def findByOwner(owner):
        """Return all access tokens for this owner.

        :param owner: An `IPerson`.
        """

    def findByTarget(target):
        """Return all access tokens for this target.

        :param target: An `IGitRepository`.
        """


class IAccessTokenVerifiedRequest(Interface):
    """Marker interface for a request with a verified access token."""
