Poll Pages
==========

First import some stuff and setup some things we'll use in this test.

    >>> from datetime import datetime, timedelta, timezone
    >>> from zope.component import getUtility, getMultiAdapter
    >>> from zope.publisher.browser import TestRequest
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.interfaces.poll import IPollSet
    >>> from lp.services.webapp.servers import LaunchpadTestRequest

    >>> login("test@canonical.com")
    >>> ubuntu_team = getUtility(IPersonSet).getByName("ubuntu-team")


Creating new polls
------------------

When creating a new poll, its start date must be at least 12h after it is
created.

First we attempt to create a poll which starts 11h from now.  That will fail
with a proper explanation of why it failed.

    >>> eleven_hours_from_now = datetime.now() + timedelta(hours=11)
    >>> eleven_hours_from_now = eleven_hours_from_now.strftime(
    ...     "%Y-%m-%d %H:%M:%S"
    ... )
    >>> one_year_from_now = (
    ...     datetime.now(timezone.utc) + timedelta(days=365)
    ... ).strftime("%Y-%m-%d")
    >>> form = {
    ...     "field.name": "test-poll",
    ...     "field.title": "test-poll",
    ...     "field.proposition": "test-poll",
    ...     "field.allowspoilt": "1",
    ...     "field.secrecy": "SECRET",
    ...     "field.dateopens": eleven_hours_from_now,
    ...     "field.datecloses": one_year_from_now,
    ...     "field.actions.continue": "Continue",
    ... }
    >>> request = LaunchpadTestRequest(method="POST", form=form)
    >>> new_poll = getMultiAdapter((ubuntu_team, request), name="+newpoll")
    >>> new_poll.initialize()
    >>> print("\n".join(new_poll.errors))
    A poll cannot open less than 12 hours after it&#x27;s created.

Now we successfully create a poll which starts 12h from now.

    >>> twelve_hours_from_now = datetime.now() + timedelta(hours=12)
    >>> twelve_hours_from_now = twelve_hours_from_now.strftime(
    ...     "%Y-%m-%d %H:%M:%S"
    ... )
    >>> form["field.dateopens"] = twelve_hours_from_now
    >>> request = LaunchpadTestRequest(method="POST", form=form)
    >>> new_poll = getMultiAdapter((ubuntu_team, request), name="+newpoll")
    >>> new_poll.initialize()
    >>> new_poll.errors
    []


Displaying results of condorcet polls
-------------------------------------

    >>> poll = getUtility(IPollSet).getByTeamAndName(
    ...     ubuntu_team, "director-2004"
    ... )
    >>> poll.type.title
    'Condorcet Voting'

Although condorcet polls are disabled now, everything is implemented and we're
using a pairwise matrix to display the results. It's very trick to create this
matrix on page templates, so the view provides a method which return this
matrix as a python list, with the necessary headers (the option's names).

    >>> poll_results = getMultiAdapter((poll, TestRequest()), name="+index")
    >>> for row in poll_results.getPairwiseMatrixWithHeaders():
    ...     print(pretty(row))
    ...
    [None, 'A', 'B', 'C', 'D']
    ['A', None, 2, 2, 2]
    ['B', 2, None, 2, 2]
    ['C', 1, 1, None, 1]
    ['D', 2, 1, 2, None]

Voting on closed polls
----------------------

This is not allowed, and apart from not linking to the +vote page and not
even displaying its content for a closed poll, we also have some lower
level checks.

    >>> request = TestRequest(form={"changevote": "Change Vote"})
    >>> request.method = "POST"
    >>> voting_page = getMultiAdapter((poll, request), name="+vote")
    >>> form_processed = False
    >>> def form_processing():
    ...     global form_processed
    ...     form_processed = True
    ...
    >>> voting_page.processCondorcetVotingForm = form_processing
    >>> voting_page.initialize()

    >>> form_processed
    False
    >>> voting_page.feedback
    'This poll is not open.'
