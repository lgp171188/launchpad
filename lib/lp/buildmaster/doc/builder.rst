XXX Julian 2010-08-03 bug=613096
Most of this doctest is really a unit test in disguise.  It should get
re-written and unit tests moved to buildmaster/tests/test_builder.py


=============
Builder Class
=============

The Builder class represents a machine in the build farm. These
workers are used to execute untrusted code -- for example when building
packages.

There are several builders in the sample data. Let's examine the first.

    >>> from lp.buildmaster.model.builder import Builder
    >>> from lp.services.database.interfaces import IStore
    >>> builder = IStore(Builder).get(Builder, 1)

As expected, it implements IBuilder.

    >>> from lp.testing import verifyObject

    >>> print(builder.name)
    bob
    >>> print(builder.builderok)
    True
    >>> print(builder.failnotes)
    None


BuilderSet
==========

Builders and groups thereof are managed through a utility, IBuilderSet.

    >>> from zope.component import getUtility
    >>> from lp.buildmaster.interfaces.builder import IBuilderSet
    >>> builderset = getUtility(IBuilderSet)
    >>> verifyObject(IBuilderSet, builderset)
    True

Iterating over a BuilderSet yields all registered builders.

    >>> for b in builderset:
    ...     print(b.name)
    bob
    frog

count() return the number of builders registered:

    >>> builderset.count()
    2

Builders can be retrieved by name.

    >>> print(builderset['bob'].name)
    bob
    >>> print(builderset['bad'])
    None

And also by ID.

    >>> print(builderset.get(2).name)
    frog
    >>> print(builderset.get(100).name)
    Traceback (most recent call last):
    ...
    lp.app.errors.NotFoundError: 100

The 'new' method will create a new builder in the database.

    >>> from lp.testing import admin_logged_in
    >>> with admin_logged_in():
    ...     bnew = builderset.new(
    ...         [1], 'http://dummy.com:8221/', 'dummy', 'Dummy Title', 1)
    >>> print(bnew.name)
    dummy

'getBuilders' returns builders with the 'active' flag set, ordered by
virtualization status, architecture, then name.

    >>> for b in builderset.getBuilders():
    ...     print(b.name)
    bob
    dummy
    frog
    >>> login('foo.bar@canonical.com')
    >>> bnew.active = False
    >>> login(ANONYMOUS)
    >>> for b in builderset.getBuilders():
    ...     print(b.name)
    bob
    frog

'getBuildQueueSizes' returns the number of pending builds for each
Processor/virtualization.

    >>> queue_sizes = builderset.getBuildQueueSizes()
    >>> size, duration = queue_sizes['nonvirt']['386']
    >>> print(size)
    1
    >>> print(duration)
    0:01:00

There are no 'amd64' build queue entries.

    >>> for arch_tag in queue_sizes['nonvirt']:
    ...     print(arch_tag)
    386

The virtualized build queue for 386 is also empty.

    >>> list(queue_sizes['virt'])
    []

The queue size is not affect by builds target to disabled
archives. Builds for disabled archive are not dispatched as well, this
is an effective manner to hold activity in a specific archive.

We will temporarily disable the ubuntu primary archive.

    >>> login('foo.bar@canonical.com')
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
    >>> ubuntu.main_archive.disable()
    >>> import transaction
    >>> transaction.commit()
    >>> login(ANONYMOUS)

That done, the non-virtualized queue for i386 becomes empty.

    >>> queue_sizes = builderset.getBuildQueueSizes()
    >>> list(queue_sizes['nonvirt'])
    []

Let's re-enable the ubuntu primary archive.

    >>> login('foo.bar@canonical.com')
    >>> ubuntu.main_archive.enable()
    >>> transaction.commit()
    >>> login(ANONYMOUS)

The build for the ubuntu primary archive shows up again.

    >>> queue_sizes = builderset.getBuildQueueSizes()
    >>> size, duration = queue_sizes['nonvirt']['386']
    >>> print(size)
    1
    >>> print(duration)
    0:01:00

All job types are included. If we create a recipe build job, it will
show up in the calculated queue size.

    >>> recipe_bq = factory.makeSourcePackageRecipeBuild(
    ...     distroseries=ubuntu.currentseries).queueBuild()
    >>> transaction.commit()
    >>> queue_sizes = builderset.getBuildQueueSizes()
    >>> size, duration = queue_sizes['virt']['386']
    >>> print(size)
    1
    >>> print(duration)
    0:10:00
