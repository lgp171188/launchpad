=========================
Person / Product listings
=========================

These listings are where only the branches associated with the product and the
person are shown, rather than all of the person's branches.

    >>> login(ANONYMOUS)
    >>> eric = factory.makePerson(name="eric")
    >>> fooix = factory.makeProduct(name="fooix")
    >>> logout()

When there are no branches, a helpful message is shown.

    >>> browser.open("http://code.launchpad.test/~eric/fooix")
    >>> print_tag_with_id(browser.contents, "no-branch-message")
    There are no branches of Fooix for Eric in Launchpad today.

If we create a couple of fooix branches, and a few other branches, we can see
that only the fooix branches are shown.

    >>> login(ANONYMOUS)
    >>> from lp.testing import time_counter
    >>> from datetime import datetime, timedelta, timezone
    >>> date_generator = time_counter(
    ...     datetime(2007, 12, 1, tzinfo=timezone.utc), timedelta(days=1)
    ... )
    >>> branch = factory.makeProductBranch(
    ...     owner=eric,
    ...     product=fooix,
    ...     name="testing",
    ...     date_created=next(date_generator),
    ... )
    >>> branch = factory.makeProductBranch(
    ...     owner=eric,
    ...     product=fooix,
    ...     name="feature",
    ...     date_created=next(date_generator),
    ... )
    >>> branch = factory.makeAnyBranch(
    ...     owner=eric, date_created=next(date_generator)
    ... )
    >>> branch = factory.makeAnyBranch(
    ...     owner=eric, date_created=next(date_generator)
    ... )
    >>> logout()

    >>> browser.open("http://code.launchpad.test/~eric/fooix")
    >>> print_tag_with_id(browser.contents, "portlet-person-codesummary")
    Branches ...
    >>> print_tag_with_id(browser.contents, "branchtable")
    Name                         ...
    lp://dev/~eric/fooix/feature ...
    lp://dev/~eric/fooix/testing ...
