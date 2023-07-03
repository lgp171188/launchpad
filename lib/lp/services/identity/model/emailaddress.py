# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "EmailAddress",
    "EmailAddressSet",
    "HasOwnerMixin",
    "UndeletableEmailAddress",
]


import hashlib
import operator

import six
from storm.expr import Lower
from zope.interface import implementer

from lp.app.validators.email import valid_email
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.sqlbase import SQLBase, sqlvalues
from lp.services.database.sqlobject import ForeignKey, StringCol
from lp.services.identity.interfaces.emailaddress import (
    EmailAddressAlreadyTaken,
    EmailAddressStatus,
    IEmailAddress,
    IEmailAddressSet,
    InvalidEmailAddress,
)


class HasOwnerMixin:
    """A mixing providing an 'owner' property which returns self.person.

    This is to be used on content classes who want to provide IHasOwner but
    have the owner stored in an attribute named 'person' rather than 'owner'.
    """

    owner = property(operator.attrgetter("person"))


@implementer(IEmailAddress)
class EmailAddress(SQLBase, HasOwnerMixin):
    _table = "EmailAddress"
    _defaultOrder = ["email"]

    email = StringCol(
        dbName="email", notNull=True, unique=True, alternateID=True
    )
    status = DBEnum(name="status", enum=EmailAddressStatus, allow_none=False)
    person = ForeignKey(dbName="person", foreignKey="Person", notNull=False)

    def __repr__(self):
        return "<EmailAddress <%s> [%s]>" % (self.email, self.status)

    def destroySelf(self):
        """See `IEmailAddress`."""
        # Import this here to avoid circular references.
        from lp.registry.interfaces.mailinglist import MailingListStatus
        from lp.registry.model.mailinglist import MailingListSubscription

        if self.status == EmailAddressStatus.PREFERRED:
            raise UndeletableEmailAddress(
                "This is a person's preferred email, so it can't be deleted."
            )
        mailing_list = self.person and self.person.mailing_list
        if (
            mailing_list is not None
            and mailing_list.status != MailingListStatus.PURGED
            and mailing_list.address == self.email
        ):
            raise UndeletableEmailAddress(
                "This is the email address of a team's mailing list, so it "
                "can't be deleted."
            )

        # XXX 2009-05-04 jamesh bug=371567: This function should not
        # be responsible for removing subscriptions, since the SSO
        # server can't write to that table.
        store = IPrimaryStore(MailingListSubscription)
        for subscription in store.find(
            MailingListSubscription, email_address=self
        ):
            store.remove(subscription)
        super().destroySelf()

    @property
    def rdf_sha1(self):
        """See `IEmailAddress`."""
        return (
            hashlib.sha1(("mailto:" + self.email).encode("UTF-8"))
            .hexdigest()
            .upper()
        )


@implementer(IEmailAddressSet)
class EmailAddressSet:
    def getByPerson(self, person):
        """See `IEmailAddressSet`."""
        return EmailAddress.selectBy(person=person, orderBy="email")

    def getPreferredEmailForPeople(self, people):
        """See `IEmailAddressSet`."""
        return EmailAddress.select(
            """
            EmailAddress.status = %s AND
            EmailAddress.person IN %s
            """
            % sqlvalues(
                EmailAddressStatus.PREFERRED, [person.id for person in people]
            )
        )

    def getByEmail(self, email):
        """See `IEmailAddressSet`."""
        return (
            IStore(EmailAddress)
            .find(
                EmailAddress,
                Lower(EmailAddress.email)
                == six.ensure_text(email).strip().lower(),
            )
            .one()
        )

    def new(self, email, person=None, status=EmailAddressStatus.NEW):
        """See IEmailAddressSet."""
        email = email.strip()

        if not valid_email(email):
            raise InvalidEmailAddress(
                "%s is not a valid email address." % email
            )

        if self.getByEmail(email) is not None:
            raise EmailAddressAlreadyTaken(
                "The email address '%s' is already registered." % email
            )
        assert status in EmailAddressStatus.items
        assert person
        return EmailAddress(email=email, status=status, person=person)


class UndeletableEmailAddress(Exception):
    """User attempted to delete an email address which can't be deleted."""
