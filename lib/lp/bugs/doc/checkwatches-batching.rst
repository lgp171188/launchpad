Batching in checkwatches
========================

The checkwatches system tries to be sensitive to batching options
given. Specifically, the _getRemoteIdsToCheck() method is responsible
for batching up operations.

    >>> import transaction
    >>> from lp.bugs.scripts.checkwatches import CheckwatchesMaster

    >>> updater = CheckwatchesMaster(transaction)
    >>> transaction.commit()


Basics
------

    >>> class BasicRemoteSystem:
    ...     sync_comments = False
    ...

    >>> remote = BasicRemoteSystem()

When there are no bug watches to check, the result is empty.

    >>> print(pretty(updater._getRemoteIdsToCheck(remote, [], batch_size=2)))
    {'all_remote_ids': [],
     'remote_ids_to_check': [],
     'unmodified_remote_ids': []}

With up to batch_size watches, it advises us to check all the remote
bug IDs given.

    >>> bug_watches = [
    ...     factory.makeBugWatch(remote_bug="a"),
    ...     factory.makeBugWatch(remote_bug="b"),
    ... ]
    >>> transaction.commit()

    >>> print(
    ...     pretty(
    ...         updater._getRemoteIdsToCheck(
    ...             remote, bug_watches, batch_size=2
    ...         )
    ...     )
    ... )
    {'all_remote_ids': ['a', 'b'],
     'remote_ids_to_check': ['a', 'b'],
     'unmodified_remote_ids': []}

With more than batch_size watches, it advises to only check a subset
of the remote bug IDs given.

    >>> bug_watches = [
    ...     factory.makeBugWatch(remote_bug="a"),
    ...     factory.makeBugWatch(remote_bug="b"),
    ...     factory.makeBugWatch(remote_bug="c"),
    ... ]
    >>> transaction.commit()

    >>> print(
    ...     pretty(
    ...         updater._getRemoteIdsToCheck(
    ...             remote, bug_watches, batch_size=2
    ...         )
    ...     )
    ... )
    {'all_remote_ids': ['a', 'b'],
     'remote_ids_to_check': ['a', 'b'],
     'unmodified_remote_ids': []}


Querying the remote system for modified bugs
--------------------------------------------

For bug watches that have been checked before, the remote system is
asked which of a list of bugs have been modified since a given date.

    >>> from zope.security.proxy import removeSecurityProxy
    >>> from datetime import datetime, timezone

    >>> class QueryableRemoteSystem:
    ...     sync_comments = False
    ...
    ...     def getModifiedRemoteBugs(self, remote_bug_ids, timestamp):
    ...         print(
    ...             "getModifiedRemoteBugs(%s, %r)"
    ...             % (pretty(remote_bug_ids), timestamp)
    ...         )
    ...         # Return every *other* bug ID for demo purposes.
    ...         return remote_bug_ids[::2]
    ...

    >>> remote = QueryableRemoteSystem()
    >>> now = datetime(2010, 1, 13, 16, 52, tzinfo=timezone.utc)

When there are no bug watches to check, the result is empty, and the
remote system is not queried.

    >>> ids_to_check = updater._getRemoteIdsToCheck(
    ...     remote, [], batch_size=2, server_time=now, now=now
    ... )

    >>> print(pretty(ids_to_check))
    {'all_remote_ids': [],
     'remote_ids_to_check': [],
     'unmodified_remote_ids': []}

With up to batch_size previously checked watches, the remote system is
queried once, and we are advised to check only one of the watches.

    >>> bug_watches = [
    ...     factory.makeBugWatch(remote_bug="a"),
    ...     factory.makeBugWatch(remote_bug="b"),
    ... ]
    >>> for bug_watch in bug_watches:
    ...     removeSecurityProxy(bug_watch).lastchecked = now
    ...
    >>> transaction.commit()

    >>> ids_to_check = updater._getRemoteIdsToCheck(
    ...     remote, bug_watches, batch_size=2, server_time=now, now=now
    ... )
    getModifiedRemoteBugs(['a', 'b'], datetime.datetime(...))

    >>> print(pretty(ids_to_check))
    {'all_remote_ids': ['a', 'b'],
     'remote_ids_to_check': ['a'],
     'unmodified_remote_ids': ['b']}

With just more than batch_size previously checked watches, the remote
system is queried twice, and we are advised to check two of the
watches.

    >>> bug_watches = [
    ...     factory.makeBugWatch(remote_bug="a"),
    ...     factory.makeBugWatch(remote_bug="b"),
    ...     factory.makeBugWatch(remote_bug="c"),
    ... ]
    >>> for bug_watch in bug_watches:
    ...     removeSecurityProxy(bug_watch).lastchecked = now
    ...
    >>> transaction.commit()

    >>> ids_to_check = updater._getRemoteIdsToCheck(
    ...     remote, bug_watches, batch_size=2, server_time=now, now=now
    ... )
    getModifiedRemoteBugs(['a', 'b'], datetime.datetime(...))
    getModifiedRemoteBugs(['c'], datetime.datetime(...))

    >>> print(pretty(ids_to_check))
    {'all_remote_ids': ['a', 'b', 'c'],
     'remote_ids_to_check': ['a', 'c'],
     'unmodified_remote_ids': ['b']}
