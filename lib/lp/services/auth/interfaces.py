# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Personal access token interfaces."""

__metaclass__ = type
__all__ = [
    "IAccessToken",
    "IAccessTokenSet",
    "IAccessTokenTarget",
    "IAccessTokenVerifiedRequest",
    ]

from lazr.restful.declarations import (
    call_with,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
    operation_returns_collection_of,
    REQUEST_USER,
    )
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
from lp.services.auth.enums import AccessTokenScope
from lp.services.fields import PublicPersonChoice
from lp.services.webservice.apihelpers import patch_reference_property


# XXX cjwatson 2021-10-13 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(as_of="beta")
class IAccessToken(Interface):
    """A personal access token for the webservice API."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_created = exported(Datetime(
        title=_("When the token was created."), required=True, readonly=True))

    owner = exported(PublicPersonChoice(
        title=_("The person who created the token."),
        vocabulary="ValidPersonOrTeam", required=True, readonly=True))

    description = exported(TextLine(
        title=_("A short description of the token."), required=True))

    git_repository = Reference(
        title=_("The Git repository for which the token was issued."),
        # Really IGitRepository, patched in _schema_circular_imports.py.
        schema=Interface, required=True, readonly=True)

    target = exported(Reference(
        title=_("The target for which the token was issued."),
        # Really IAccessTokenTarget, patched in _schema_circular_imports.py.
        schema=Interface, required=True, readonly=True))

    scopes = exported(List(
        value_type=Choice(vocabulary=AccessTokenScope),
        title=_("A list of scopes granted by the token."),
        required=True, readonly=True))

    date_last_used = exported(Datetime(
        title=_("When the token was last used."),
        required=False, readonly=True))

    date_expires = exported(Datetime(
        title=_("When the token should expire or was revoked."),
        required=False, readonly=True))

    is_expired = Bool(
        title=_("Whether this token has expired."),
        required=False, readonly=True)

    revoked_by = exported(PublicPersonChoice(
        title=_("The person who revoked the token, if any."),
        vocabulary="ValidPersonOrTeam", required=False, readonly=True))

    def updateLastUsed():
        """Update this token's last-used date, if possible."""

    @call_with(revoked_by=REQUEST_USER)
    @export_write_operation()
    @operation_for_version("devel")
    def revoke(revoked_by):
        """Revoke this token."""


class IAccessTokenSet(Interface):
    """The set of all personal access tokens."""

    def new(secret, owner, description, target, scopes, date_expires=None):
        """Return a new access token with a given secret.

        :param secret: A text string.
        :param owner: An `IPerson` who is creating the token.
        :param description: A short description of the token.
        :param target: An `IAccessTokenTarget` for which the token is being
            issued.
        :param scopes: A list of `AccessTokenScope`s to be granted by the
            token.
        :param date_expires: The time when this token should expire, or
            None.
        """

    def getBySecret(secret):
        """Return the access token with this secret, or None.

        :param secret: A text string.
        """

    def findByOwner(owner):
        """Return all access tokens for this owner.

        :param owner: An `IPerson`.
        """

    def findByTarget(target, visible_by_user=None):
        """Return all access tokens for this target.

        :param target: An `IAccessTokenTarget`.
        :param visible_by_user: If given, return only access tokens visible
            by this user.
        """


class IAccessTokenVerifiedRequest(Interface):
    """Marker interface for a request with a verified access token."""


# XXX cjwatson 2021-10-13 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(as_of="beta")
class IAccessTokenTarget(Interface):
    """An object that can be a target for access tokens."""

    @call_with(visible_by_user=REQUEST_USER)
    @operation_returns_collection_of(IAccessToken)
    @export_read_operation()
    @operation_for_version("devel")
    def getAccessTokens(visible_by_user=None):
        """Return personal access tokens for this target."""


patch_reference_property(IAccessToken, "target", IAccessTokenTarget)
