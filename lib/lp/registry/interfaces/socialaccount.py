# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""SocialAccount interfaces."""

__all__ = [
    "ISocialAccount",
    "ISocialAccountSet",
    "MatrixPlatform",
    "SocialPlatformType",
    "SOCIAL_PLATFORM_TYPES_MAP",
    "SocialAccountIdentityError",
    "validate_social_account_identity",
    "SOCIAL_PLATFORM_TYPES_MAP",
]

import http.client
import re

from lazr.enum import DBEnumeratedType, DBItem
from lazr.restful.declarations import (
    error_status,
    exported,
    exported_as_webservice_entry,
)
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import Choice, Dict, Int, TextLine

from lp import _
from lp.registry.interfaces.role import IHasOwner


class SocialPlatformType(DBEnumeratedType):
    """Social Platform Type

    Social Account is associated with a SocialPlatformType.
    """

    MATRIX = DBItem(
        1,
        """
        Matrix platform

        The Social Account will hold Matrix account info.
        """,
    )


# XXX pelpsi 2023-12-14 bug=760849: "beta" is a lie to get WADL generation
# working.
@exported_as_webservice_entry("social_account", as_of="beta")
class ISocialAccount(IHasOwner):
    """Social Account"""

    id = Int(title=_("Database ID"), required=True, readonly=True)
    # schema=Interface will be overridden in person.py because of circular
    # dependencies.
    person = exported(
        Reference(
            title=_("Owner"), required=True, schema=Interface, readonly=True
        )
    )

    platform = exported(
        Choice(
            title=_("Social Platform Type"),
            required=True,
            vocabulary=SocialPlatformType,
        )
    )

    identity = exported(
        Dict(
            title=_("Identity"),
            key_type=TextLine(),
            required=True,
            readonly=False,
            description=_(
                "A dictionary with the identity attributes and values for the "
                "social account. The format is specific for each platform. "
                "Matrix account attributes: username, homeserver "
            ),
        )
    )

    def destroySelf():
        """Delete this SocialAccount from the database."""


class ISocialAccountSet(Interface):
    """The set of SocialAccounts."""

    def new(self, person, platform, identity):
        """Create a new SocialAccount pointing to the given Person."""

    def getByPerson(person):
        """Return all SocialAccounts for the given person."""

    def getByPersonAndSocialPlatform(person, social_platform):
        """Return all SocialAccounts for the given person and platform."""

    def get(id):
        """Return the SocialAccount with the given id or None."""


class SocialPlatform:
    title = ""
    identity_fields = []
    identity_fields_example = {}
    platform_type = None
    icon = ""
    display_format = ""
    url = None

    @classmethod
    def validate_identity(cls, identity):
        pass


# XXX pelpsi: replace this with a pydantic validator
class MatrixPlatform(SocialPlatform):
    title = "Matrix"
    identity_fields = ["username", "homeserver"]
    identity_fields_example = {
        "username": "mark",
        "homeserver": "ubuntu.com",
    }
    platform_type = SocialPlatformType.MATRIX
    icon = "social-matrix"
    display_format = "<strong>@{username}:{homeserver}</strong>"
    url = "https://matrix.to//#/@{username}:{homeserver}"

    @classmethod
    def validate_identity(cls, identity):
        if not all(
            identity.get(required_field)
            for required_field in cls.identity_fields
        ):
            raise SocialAccountIdentityError(
                f"You must provide the following fields: "
                f"{', '.join(cls.identity_fields)}."
            )
        if not isinstance(identity["username"], str):
            raise SocialAccountIdentityError("Username must be a string.")
        # Matrix username can contain a-z, 0-9, ., _, =, -, and /
        # ref: https://spec.matrix.org/v1.1/appendices/#user-identifiers
        username_regex = r"^[A-z0-9-=_./]+"
        if not re.match(username_regex, identity["username"]):
            raise SocialAccountIdentityError("Username must be valid.")
        homeserver_regex = (
            r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            "[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$"
        )
        if not isinstance(identity["homeserver"], str):
            raise SocialAccountIdentityError("Homeserver must be a string.")
        if not re.match(homeserver_regex, identity["homeserver"]):
            raise SocialAccountIdentityError(
                "Homeserver must be a valid domain."
            )


SOCIAL_PLATFORM_TYPES_MAP = {
    SocialPlatformType.MATRIX: MatrixPlatform,
}


@error_status(http.client.BAD_REQUEST)
class SocialAccountIdentityError(Exception):
    """Raised when Social Account's identity is
    invalid for a given Social Platform Type.
    """


def validate_social_account_identity(obj, attr, value):
    social_account = obj

    social_platform = social_account.getSocialPlatform()
    social_platform.validate_identity(identity=value)

    return value
