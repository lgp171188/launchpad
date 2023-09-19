Security proxies
----------------

Storm objects that are security proxied should still behave normally, this
includes being comparable with non-security proxied objects.

First, some imports and set up::

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.model.person import Person
    >>> from lp.services.database.interfaces import IStore

Get a proxied and unproxied person object for the same person, and demonstrate
working comparisons::

    >>> mark = IStore(Person).get(Person, 1)
    >>> mark_proxied = getUtility(IPersonSet).get(1)
    >>> mark is mark_proxied
    False
    >>> mark == mark
    True
    >>> mark == mark_proxied
    True
    >>> mark_proxied == mark
    True
    >>> mark_proxied == mark_proxied
    True

A ``lazr.enum.DBItem`` can also be given to Storm's find() method.

    >>> proxied_policy = mark_proxied.membership_policy
    >>> type(proxied_policy)
    <... 'zope.security._proxy._Proxy'>

    # We don't want this test to fail when we add new person entries, so we
    # compare it against a base number.
    >>> IStore(Person).find(
    ...     Person, membership_policy=proxied_policy
    ... ).count() > 60
    True
    >>> person = (
    ...     IStore(Person)
    ...     .find(Person, membership_policy=proxied_policy)
    ...     .first()
    ... )
    >>> person.membership_policy.name
    'MODERATED'

XXX: stevea: 20051018: Rewrite this test to use security proxies directly
XXX: bug 3315
``lazr.enum.DBItem`` objects are comparable correctly when proxied.

    >>> from lp.registry.interfaces.distroseries import IDistroSeriesSet
    >>> from lp.registry.interfaces.series import SeriesStatus
    >>> hoary = getUtility(IDistroSeriesSet).get(3)
    >>> print(hoary.status.name)
    DEVELOPMENT
    >>> hoary.status == SeriesStatus.DEVELOPMENT
    True
    >>> hoary.status is SeriesStatus.DEVELOPMENT
    False
