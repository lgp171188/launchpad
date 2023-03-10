Script Monitoring
=================

To help monitor the health of the various cron jobs that keep
Launchpad running, we record the status of successful script runs in
the database.  This data can then be used for the following:

 * Check that the script is running as often as it should.
 * Check that the script has run recently.
 * Check that the script's average runtime is sensible.


Recording Successful Runs
-------------------------

When a script completes successfully, it should record the fact in the
database.  This is performed with a call to
IScriptActivitySet.recordSuccess():

    >>> from datetime import datetime, timezone
    >>> import socket
    >>> from textwrap import dedent
    >>> from unittest import mock

    >>> from fixtures import MockPatchObject
    >>> from zope.component import getUtility

    >>> from lp.services.config import config
    >>> from lp.services.scripts.interfaces.scriptactivity import (
    ...     IScriptActivitySet,
    ... )
    >>> from lp.services.statsd.interfaces.statsd_client import IStatsdClient
    >>> from lp.testing.dbuser import switch_dbuser

    >>> switch_dbuser("garbo_daily")  # A script db user

    >>> config.push(
    ...     "statsd_test",
    ...     dedent(
    ...         """
    ...     [statsd]
    ...     environment: test
    ...     """
    ...     ),
    ... )
    >>> statsd_client = getUtility(IStatsdClient)
    >>> stats_client = mock.Mock()

    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     activity = getUtility(IScriptActivitySet).recordSuccess(
    ...         name="script-name",
    ...         date_started=datetime(2007, 2, 1, 10, 0, tzinfo=timezone.utc),
    ...         date_completed=datetime(
    ...             2007, 2, 1, 10, 1, tzinfo=timezone.utc
    ...         ),
    ...         hostname="script-host",
    ...     )
    ...

    >>> _ = config.pop("statsd_test")

The activity object records the script name, the host name it ran on
and the start and end timestamps:

    >>> print(activity.name)
    script-name
    >>> print(activity.hostname)
    script-host
    >>> print(activity.date_started)
    2007-02-01 10:00:00+00:00
    >>> print(activity.date_completed)
    2007-02-01 10:01:00+00:00

It sends a corresponding timing stat to statsd.

    >>> stats_client.timing.call_count
    1
    >>> print(stats_client.timing.call_args[0][0])
    script_activity,env=test,name=script-name
    >>> stats_client.timing.call_args[0][1]
    60000.0

We can also query for the last activity for a particular script, which
will match the activity we just created:

    >>> activity = getUtility(IScriptActivitySet).getLastActivity(
    ...     "script-name"
    ... )
    >>> print(activity.date_started)
    2007-02-01 10:00:00+00:00

If no activity has occurred for a script, getLastActivity() returns
None:

    >>> print(
    ...     getUtility(IScriptActivitySet).getLastActivity("no-such-script")
    ... )
    None

If the hostname parameter is omitted, it defaults to the host the
script ran on, as determined by 'socket.gethostname()':

    >>> local_activity = getUtility(IScriptActivitySet).recordSuccess(
    ...     name=factory.getUniqueString(),
    ...     date_started=datetime.now(timezone.utc),
    ...     date_completed=datetime.now(timezone.utc),
    ... )
    >>> local_activity.hostname == socket.gethostname()
    True
