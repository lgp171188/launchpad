Our database adapters need to trap writes to tables in standby replication
sets. These tables may be reached directly using a STANDBY_FLAVOR store, or
traversed to from a PRIMARY_FLAVOR store.

Because our development environment is not replicated, we use database
permissions to ensure that tables we should not be writing to cannot
be written to. The same permissions structure is also used on production,
so the Slony-I triggers blocking writes to replicated tables will never
actually be invoked.

    >>> from lp.registry.model.person import Person
    >>> from lp.services.database.interfaces import (
    ...     IStoreSelector,
    ...     MAIN_STORE,
    ...     PRIMARY_FLAVOR,
    ...     STANDBY_FLAVOR,
    ... )
    >>> import transaction
    >>> from zope.component import getUtility

If a STANDBY_FLAVOR store is requested, it should trap all writes.

    >>> t = transaction.begin()
    >>> main_standby = getUtility(IStoreSelector).get(
    ...     MAIN_STORE, STANDBY_FLAVOR
    ... )
    >>> janitor = main_standby.find(Person, name="janitor").one()
    >>> janitor.display_name = "Ben Dover"
    >>> transaction.commit()
    Traceback (most recent call last):
    ...
    storm.database.ReadOnlySqlTransaction: ...

Test this once more to ensure the settings stick across transactions.

    >>> transaction.abort()
    >>> t = transaction.begin()
    >>> main_standby.find(Person, name="janitor").one().display_name = "BenD"
    >>> transaction.commit()
    Traceback (most recent call last):
    ...
    storm.database.ReadOnlySqlTransaction: ...

If a PRIMARY_FLAVOR is requested, it should allow writes to table in that
Store's replication set.

    >>> t = transaction.begin()
    >>> main_primary = getUtility(IStoreSelector).get(
    ...     MAIN_STORE, PRIMARY_FLAVOR
    ... )
    >>> main_primary.find(Person, name="janitor").one().display_name = "BenD"
    >>> transaction.commit()
    >>> t = transaction.begin()
    >>> print(main_primary.find(Person, name="janitor").one().display_name)
    BenD
    >>> transaction.abort()
