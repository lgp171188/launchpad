Note: A more readable version of this is in db-policy.rst. Most of this
doctest will disappear soon when the auth replication set is collapsed
back into the main replication set as part of login server separation.
-- StuartBishop 20100222

In addition to what Storm provides, we also have some Launchpad
specific Storm tools to cope with our primary and standby store arrangement.

    >>> from lp.services.identity.interfaces.emailaddress import (
    ...     EmailAddressStatus,
    ...     IEmailAddressSet,
    ... )
    >>> from lp.services.database.interfaces import (
    ...     IPrimaryObject,
    ...     IPrimaryStore,
    ...     IStandbyStore,
    ...     IStore,
    ... )
    >>> from lp.services.identity.model.emailaddress import EmailAddress
    >>> from zope.security.proxy import ProxyFactory
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.model.person import Person


You need to use the correct primary Store to make changes to
a Launchpad database object. You can use adapters to
retrieve the correct Store.

    >>> main_primary = IPrimaryStore(Person)

You can detect if a store is writable by checking what interfaces it
provides.

    >>> IPrimaryStore.providedBy(main_primary)
    True
    >>> IStandbyStore.providedBy(main_primary)
    False


Changes to the standby Stores will lag behind the primary Stores. If
you only need to read an object but require it to be in sync with the
primary, you should use the default Store. Launchpad will give you the
standby store if it is sure all your recent changes have been replicated.
Otherwise, it gives you the primary. See IStoreSelector for details.

    >>> main_default = IStore(Person)
    >>> main_standby = IStandbyStore(Person)
    >>> main_default is main_primary
    True
    >>> main_default is main_standby
    False


You can also adapt database object instances to Stores, although
this is less generally useful.

    >>> janitor = IStandbyStore(Person).find(Person, name="janitor").one()
    >>> IStandbyStore(janitor) is IStandbyStore(Person)
    True
    >>> IPrimaryStore(janitor) is IPrimaryStore(Person)
    True
    >>> IPrimaryStore(janitor) is IStandbyStore(Person)
    False


If we need the primary copy of an object, we can adapt it to IPrimaryObject.
Good defensive programming is to use this adapter if you want to make
changes to an object, just in case you have been passed an instance
from a store other than the correct Primary.

    >>> main_standby = IStandbyStore(Person)
    >>> t = transaction.begin()
    >>> person = main_standby.find(Person, name="mark").one()
    >>> person.display_name = "Cannot change"
    >>> transaction.commit()
    Traceback (most recent call last):
    ...
    storm.database.ReadOnlySqlTransaction: ...

    >>> transaction.abort()
    >>> t = transaction.begin()
    >>> person = main_standby.find(Person, name="mark").one()
    >>> IPrimaryObject(person).display_name = "Can change"
    >>> transaction.commit()


If the adapted object was security proxied, the primary copy is
similarly wrapped.

    >>> from zope.security.proxy import removeSecurityProxy
    >>> person = getUtility(IPersonSet).getByEmail("no-priv@canonical.com")
    >>> removeSecurityProxy(person) is person
    False
    >>> print(person.displayname)
    No Privileges Person
    >>> person.name = "foo"
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> person = IPrimaryObject(person)
    >>> removeSecurityProxy(person) is person
    False
    >>> print(person.displayname)
    No Privileges Person
    >>> person.name = "foo"
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> person = IPrimaryObject(removeSecurityProxy(person))
    >>> removeSecurityProxy(person) is person
    True
    >>> print(person.displayname)
    No Privileges Person
    >>> person.name = "foo"

Our objects may compare equal even if they have come from different
stores.

    >>> primary_email = (
    ...     IPrimaryStore(EmailAddress)
    ...     .find(
    ...         EmailAddress,
    ...         Person.name == "janitor",
    ...         EmailAddress.person == Person.id,
    ...     )
    ...     .one()
    ... )
    >>> standby_email = (
    ...     IStandbyStore(EmailAddress)
    ...     .find(
    ...         EmailAddress,
    ...         Person.name == "janitor",
    ...         EmailAddress.person == Person.id,
    ...     )
    ...     .one()
    ... )
    >>> primary_email is standby_email
    False
    >>> primary_email == standby_email
    True
    >>> primary_email != standby_email
    False

Comparison works for security wrapped objects too.

    >>> wrapped_email = getUtility(IEmailAddressSet).getByEmail(
    ...     primary_email.email
    ... )
    >>> removeSecurityProxy(wrapped_email) is primary_email
    True
    >>> wrapped_email is primary_email
    False
    >>> wrapped_email == primary_email
    True
    >>> wrapped_email != primary_email
    False

Objects not yet flushed to the database also compare equal.

    >>> unflushed = EmailAddress(
    ...     email="notflushed@example.com",
    ...     status=EmailAddressStatus.NEW,
    ...     person=getUtility(IPersonSet).get(1),
    ... )
    >>> unflushed == unflushed
    True
    >>> unflushed != unflushed
    False
    >>> wrapped_unflushed = ProxyFactory(unflushed)
    >>> wrapped_unflushed is unflushed
    False
    >>> wrapped_unflushed == unflushed
    True
    >>> wrapped_unflushed != unflushed
    False

Objects differing by class never compare equal.

    >>> email_one = IPrimaryStore(EmailAddress).get(EmailAddress, 1)
    >>> person_one = IPrimaryStore(Person).get(Person, 1)
    >>> email_one == person_one
    False
    >>> email_one != person_one
    True
