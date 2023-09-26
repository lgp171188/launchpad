# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OpenIdIdentifier database class."""

__all__ = ["OpenIdIdentifier"]

from datetime import timezone

from storm.locals import DateTime, Int, Reference, Unicode

from lp.services.database.constants import UTC_NOW
from lp.services.database.stormbase import StormBase


class OpenIdIdentifier(StormBase):
    """An OpenId Identifier that can be used to log into an Account"""

    __storm_table__ = "openididentifier"
    identifier = Unicode(primary=True)
    account_id = Int("account")
    account = Reference(account_id, "Account.id")
    date_created = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )
