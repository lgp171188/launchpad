Changing Bug Task Status
========================

Restrictions
------------

There are a few simple rules around who can change the status of a
bug task.  There are five statuses that can only be set by either
the project maintainer, driver or bug supervisor:

 * Deferred
 * Won't Fix
 * Does Not Exist
 * Expired
 * Triaged

    >>> owner = factory.makePerson()
    >>> product = factory.makeProduct(owner=owner)
    >>> bugtask = factory.makeBugTask(target=product)
    >>> user = factory.makePerson()

    >>> from lp.bugs.interfaces.bugtask import BugTaskStatus
    >>> ignored = login_person(owner)
    >>> bugtask.transitionToStatus(BugTaskStatus.DEFERRED, owner)
    >>> print(bugtask.status.title)
    Deferred

    >>> bugtask.transitionToStatus(BugTaskStatus.WONTFIX, owner)
    >>> print(bugtask.status.title)
    Won't Fix

    >>> bugtask.transitionToStatus(BugTaskStatus.DOESNOTEXIST, owner)
    >>> print(bugtask.status.title)
    Does Not Exist

Regular users of Launchpad cannot transition a bug task to any of
these statuses.

An additional restraint is added to Won't Fix, Does Not Exist and Deferred.
Only the product maintainer, driver or bug supervisor can change
from this status to any other status.

    >>> ignored = login_person(user)
    >>> bugtask.transitionToStatus(BugTaskStatus.CONFIRMED, user)
    Traceback (most recent call last):
    ...
    lp.bugs.interfaces.bugtask.UserCannotEditBugTaskStatus: ...

    >>> bugtask.transitionToStatus(BugTaskStatus.DOESNOTEXIST, owner)
    >>> print(bugtask.status.title)
    Does Not Exist
    >>> bugtask.transitionToStatus(BugTaskStatus.CONFIRMED, user)
    Traceback (most recent call last):
    ...
    lp.bugs.interfaces.bugtask.UserCannotEditBugTaskStatus: ...

    >>> bugtask.transitionToStatus(BugTaskStatus.WONTFIX, owner)
    >>> print(bugtask.status.title)
    Won't Fix
    >>> bugtask.transitionToStatus(BugTaskStatus.CONFIRMED, user)
    Traceback (most recent call last):
    ...
    lp.bugs.interfaces.bugtask.UserCannotEditBugTaskStatus: ...

    >>> bugtask.transitionToStatus(BugTaskStatus.DEFERRED, owner)
    >>> print(bugtask.status.title)
    Deferred
    >>> bugtask.transitionToStatus(BugTaskStatus.CONFIRMED, user)
    Traceback (most recent call last):
    ...
    lp.bugs.interfaces.bugtask.UserCannotEditBugTaskStatus: ...

This is fully tested in
lp.bugs.tests.test_bugtask_status.TestBugTaskStatusSetting.

Testing for Permission
----------------------

The method IBugTask.canTransitionToStatus comes in handy here. It
tells us if a transition to a status is permitted. It is *not* a
dry-run of IBugTask.transitionToStatus, but is good enough and fast
enough to be used by UI code, e.g. to display only those statuses to
which a user can transition a particular bugtask.

    >>> bugtask.canTransitionToStatus(BugTaskStatus.TRIAGED, owner)
    True
    >>> bugtask.canTransitionToStatus(BugTaskStatus.TRIAGED, user)
    False

This method is fully tested in
lp.bugs.tests.test_bugtask_status.TestCanTransitionToStatus.
