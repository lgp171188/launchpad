# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database class for table ArchiveAuthToken."""

__all__ = [
    "ArchiveAuthToken",
]

from datetime import timezone

from lazr.uri import URI
from storm.expr import LeftJoin
from storm.locals import And, DateTime, Int, Join, Or, Reference, Unicode
from storm.store import Store
from zope.interface import implementer

from lp.registry.model.teammembership import TeamParticipation
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.identity.interfaces.account import AccountStatus
from lp.services.identity.model.account import Account
from lp.soyuz.enums import ArchiveSubscriberStatus
from lp.soyuz.interfaces.archiveauthtoken import (
    IArchiveAuthToken,
    IArchiveAuthTokenSet,
)


@implementer(IArchiveAuthToken)
class ArchiveAuthToken(StormBase):
    """See `IArchiveAuthToken`."""

    __storm_table__ = "ArchiveAuthToken"

    id = Int(primary=True)

    archive_id = Int(name="archive", allow_none=False)
    archive = Reference(archive_id, "Archive.id")

    person_id = Int(name="person", allow_none=True)
    person = Reference(person_id, "Person.id")

    date_created = DateTime(
        name="date_created", allow_none=False, tzinfo=timezone.utc
    )

    date_deactivated = DateTime(
        name="date_deactivated", allow_none=True, tzinfo=timezone.utc
    )

    token = Unicode(name="token", allow_none=False)

    name = Unicode(name="name", allow_none=True)

    def deactivate(self):
        """See `IArchiveAuthTokenSet`."""
        self.date_deactivated = UTC_NOW

    @property
    def archive_url(self):
        """Return a custom archive url for basic authentication."""
        normal_url = URI(self.archive.archive_url)
        if self.name:
            name = "+" + self.name
        else:
            name = self.person.name
        auth_url = normal_url.replace(userinfo="%s:%s" % (name, self.token))
        return str(auth_url)

    def asDict(self):
        return {"token": self.token, "archive_url": self.archive_url}


@implementer(IArchiveAuthTokenSet)
class ArchiveAuthTokenSet:
    """See `IArchiveAuthTokenSet`."""

    title = "Archive Tokens in Launchpad"

    def get(self, token_id):
        """See `IArchiveAuthTokenSet`."""
        return IStore(ArchiveAuthToken).get(ArchiveAuthToken, token_id)

    def getByToken(self, token):
        """See `IArchiveAuthTokenSet`."""
        return (
            IStore(ArchiveAuthToken)
            .find(ArchiveAuthToken, ArchiveAuthToken.token == token)
            .one()
        )

    def getByArchive(self, archive, with_current_subscription=False):
        """See `IArchiveAuthTokenSet`."""
        # Circular imports.
        from lp.registry.model.person import Person
        from lp.soyuz.model.archivesubscriber import ArchiveSubscriber

        store = Store.of(archive)
        tables = [
            ArchiveAuthToken,
            LeftJoin(Person, ArchiveAuthToken.person == Person.id),
            LeftJoin(Account, Person.account == Account.id),
        ]
        clauses = [
            ArchiveAuthToken.archive == archive,
            ArchiveAuthToken.date_deactivated == None,
            Or(
                ArchiveAuthToken.person == None,
                Account.status == AccountStatus.ACTIVE,
            ),
        ]
        if with_current_subscription:
            tables.extend(
                [
                    Join(
                        ArchiveSubscriber,
                        ArchiveAuthToken.archive_id
                        == ArchiveSubscriber.archive_id,
                    ),
                    Join(
                        TeamParticipation,
                        And(
                            ArchiveSubscriber.subscriber_id
                            == TeamParticipation.team_id,
                            TeamParticipation.person_id
                            == ArchiveAuthToken.person_id,
                        ),
                    ),
                ]
            )
            clauses.append(
                ArchiveSubscriber.status == ArchiveSubscriberStatus.CURRENT
            )
        return (
            store.using(*tables)
            .find(ArchiveAuthToken, *clauses)
            .config(distinct=True)
        )

    def getActiveTokenForArchiveAndPerson(self, archive, person):
        """See `IArchiveAuthTokenSet`."""
        return (
            self.getByArchive(archive, with_current_subscription=True)
            .find(ArchiveAuthToken.person == person)
            .one()
        )

    def getActiveTokenForArchiveAndPersonName(self, archive, person_name):
        """See `IArchiveAuthTokenSet`."""
        # Circular import.
        from lp.registry.model.person import Person

        return (
            self.getByArchive(archive, with_current_subscription=True)
            .find(
                ArchiveAuthToken.person == Person.id,
                Person.name == person_name,
            )
            .one()
        )

    def getActiveNamedTokenForArchive(self, archive, name):
        """See `IArchiveAuthTokenSet`."""
        return (
            self.getByArchive(archive)
            .find(ArchiveAuthToken.name == name)
            .one()
        )

    def getActiveNamedTokensForArchive(self, archive, names=None):
        """See `IArchiveAuthTokenSet`."""
        if names:
            return self.getByArchive(archive).find(
                ArchiveAuthToken.name.is_in(names)
            )
        else:
            return self.getByArchive(archive).find(
                ArchiveAuthToken.name != None
            )

    def deactivateNamedTokensForArchive(self, archive, names):
        """See `IArchiveAuthTokenSet`."""
        tokens = self.getActiveNamedTokensForArchive(archive, names)
        # Push this down to a subselect so that `ResultSet.set` works
        # properly.
        tokens = Store.of(archive).find(
            ArchiveAuthToken,
            ArchiveAuthToken.id.is_in(
                tokens.get_select_expr(ArchiveAuthToken.id)
            ),
        )
        tokens.set(date_deactivated=UTC_NOW)
