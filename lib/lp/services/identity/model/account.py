# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementation classes for Account and associates."""

__all__ = [
    "Account",
    "AccountSet",
]

from datetime import datetime, timezone

from storm.locals import DateTime, Int, ReferenceSet, Unicode
from zope.interface import implementer

from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.helpers import backslashreplace
from lp.services.identity.interfaces.account import (
    AccountCreationRationale,
    AccountStatus,
    IAccount,
    IAccountSet,
)
from lp.services.openid.model.openididentifier import OpenIdIdentifier


class AccountStatusDBEnum(DBEnum):
    def __set__(self, obj, value):
        if self.__get__(obj) == value:
            return
        IAccount["status"].bind(obj)._validate(value)
        super().__set__(obj, value)


@implementer(IAccount)
class Account(StormBase):
    """An Account."""

    __storm_table__ = "Account"

    id = Int(primary=True)

    date_created = DateTime(
        name="date_created",
        allow_none=False,
        default=UTC_NOW,
        tzinfo=timezone.utc,
    )

    displayname = Unicode(name="displayname", allow_none=False)

    creation_rationale = DBEnum(
        name="creation_rationale",
        enum=AccountCreationRationale,
        allow_none=False,
    )
    status = AccountStatusDBEnum(
        name="status",
        enum=AccountStatus,
        default=AccountStatus.NOACCOUNT,
        allow_none=False,
    )
    date_status_set = DateTime(
        name="date_status_set",
        allow_none=False,
        default=UTC_NOW,
        tzinfo=timezone.utc,
    )
    status_history = Unicode(name="status_comment", default=None)

    openid_identifiers = ReferenceSet(
        "Account.id", OpenIdIdentifier.account_id
    )

    _creating = False

    def __init__(self, displayname, creation_rationale, status):
        super().__init__()
        self._creating = True
        self.displayname = displayname
        self.creation_rationale = creation_rationale
        self.status = status
        del self._creating

    def __repr__(self):
        displayname = backslashreplace(self.displayname)
        return "<%s '%s' (%s)>" % (
            self.__class__.__name__,
            displayname,
            self.status,
        )

    def addStatusComment(self, user, comment):
        """See `IAccountModerateRestricted`."""
        prefix = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        if user is not None:
            prefix += " %s" % user.name
        old_lines = (
            self.status_history.splitlines() if self.status_history else []
        )
        self.status_history = "\n".join(
            old_lines + ["%s: %s" % (prefix, comment), ""]
        )

    def setStatus(self, status, user, comment):
        """See `IAccountModerateRestricted`."""
        comment = comment or ""
        self.addStatusComment(
            user, "%s -> %s: %s" % (self.status.title, status.title, comment)
        )
        # date_status_set is maintained by a DB trigger.
        self.status = status

    def reactivate(self, comment):
        """See `IAccountSpecialRestricted`."""
        self.setStatus(AccountStatus.ACTIVE, None, comment)


@implementer(IAccountSet)
class AccountSet:
    """See `IAccountSet`."""

    def new(
        self,
        rationale,
        displayname,
        openid_identifier=None,
        status=AccountStatus.NOACCOUNT,
    ):
        """See `IAccountSet`."""
        assert status in (AccountStatus.NOACCOUNT, AccountStatus.PLACEHOLDER)
        account = Account(
            displayname=displayname,
            creation_rationale=rationale,
            status=status,
        )
        IStore(Account).add(account)
        IStore(Account).flush()

        # Create an OpenIdIdentifier record if requested.
        if openid_identifier is not None:
            assert isinstance(openid_identifier, str)
            identifier = OpenIdIdentifier()
            identifier.account = account
            identifier.identifier = openid_identifier
            IPrimaryStore(OpenIdIdentifier).add(identifier)

        return account

    def get(self, id):
        """See `IAccountSet`."""
        account = IStore(Account).get(Account, id)
        if account is None:
            raise LookupError(id)
        return account

    def getByOpenIDIdentifier(self, openid_identifier):
        """See `IAccountSet`."""
        store = IStore(Account)
        account = store.find(
            Account,
            Account.id == OpenIdIdentifier.account_id,
            OpenIdIdentifier.identifier == openid_identifier,
        ).one()
        if account is None:
            raise LookupError(openid_identifier)
        return account
