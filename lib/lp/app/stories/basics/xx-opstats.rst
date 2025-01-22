Operational Statistics and Metrics
==================================

We make Zope 3 give us real time statistics about Launchpad's operation.
We can access them via XML-RPC:

    >>> import xmlrpc.client
    >>> from lp.testing.xmlrpc import XMLRPCTestTransport
    >>> lp_xmlrpc = xmlrpc.client.ServerProxy(
    ...     "http://xmlrpc.launchpad.test/+opstats",
    ...     transport=XMLRPCTestTransport(),
    ... )

We also emit similar metrics to statsd, so set that up.

    >>> from textwrap import dedent
    >>> from unittest import mock
    >>> from fixtures import MockPatchObject
    >>> from zope.component import getUtility
    >>> from lp.services.config import config
    >>> from lp.services.statsd.interfaces.statsd_client import IStatsdClient

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

Create a function to report our stats for these tests.

    >>> from collections import Counter
    >>> def reset():
    ...     from lp.services.webapp.opstats import OpStats
    ...
    ...     OpStats.resetStats()
    ...     stats_client.reset_mock()
    ...
    >>> def report():
    ...     stats = lp_xmlrpc.opstats()
    ...     for stat_key in sorted(stats.keys()):
    ...         value = stats[stat_key]
    ...         if value > 0:
    ...             print("%s: %d" % (stat_key, value))
    ...     for statsd_key, value in sorted(
    ...         Counter(
    ...             call[0][0] for call in stats_client.incr.call_args_list
    ...         ).items()
    ...     ):
    ...         print("statsd: %s: %d" % (statsd_key, value))
    ...     reset()
    ...

Number of requests and XML-RPC requests
---------------------------------------

Even though XML-RPC requests are technically HTTP requests, we do not
count them as such. Note that the call to obtain statistics will increment
the 'requests' and 'xml-rpc requests' statistics, but this will not be
visible until the next time we access the statistics as the statistics
are adjusted after the request has been served:

    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     stats = lp_xmlrpc.opstats()
    ...
    >>> for key in sorted(stats.keys()):
    ...     # Print all so new keys added to OpStats.stats will trigger
    ...     # failures in this test prompting developers to extend it.
    ...     print("%s: %d" % (key, stats[key]))
    ...
    1XXs: 0
    2XXs: 0
    3XXs: 0
    404s: 0
    4XXs: 0
    500s: 0
    503s: 0
    5XXs: 0
    5XXs_b: 0
    6XXs: 0
    http requests: 0
    requests: 0
    retries: 0
    soft timeouts: 0
    timeouts: 0
    xml-rpc faults: 0
    xml-rpc requests: 0
    >>> report()
    requests: 1
    xml-rpc requests: 1
    statsd: requests.all,env=test: 1
    statsd: requests.xmlrpc,env=test: 1

Number of HTTP requests and success codes
-----------------------------------------

    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     output = http("GET / HTTP/1.1\nHost: bugs.launchpad.test\n")
    ...
    >>> output.getStatus()
    200
    >>> report()
    2XXs: 1
    http requests: 1
    requests: 1
    statsd: errors.2XX,env=test: 1
    statsd: requests.all,env=test: 1
    statsd: requests.http,env=test: 1

Number of 404s
--------------

Note that retries is incremented too. As per the standard Launchpad
database policy, this request first uses the standby DB. The requested
information is not found in there, so a retry is attempted against the
master DB in case the information is missing due to replication lag.

    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     output = http("GET http://launchpad.test/non-existent HTTP/1.1\n")
    ...
    >>> output.getStatus()
    404
    >>> report()
    404s: 1
    4XXs: 1
    http requests: 1
    requests: 1
    retries: 1
    statsd: errors.404,env=test: 1
    statsd: errors.4XX,env=test: 1
    statsd: requests.all,env=test: 1
    statsd: requests.http,env=test: 1
    statsd: requests.retries,env=test: 1

Number of 500 Internal Server Errors (unhandled exceptions)
-----------------------------------------------------------

This is normally the number of OOPS pages displayed to the user, but
may also include the odd case where the OOPS system has failed and a
fallback error page is rendered by Zope3. There doesn't seem to be any
particular need to differentiate these cases though:

    >>> from zope.interface import Interface
    >>> from zope.publisher.interfaces.browser import IDefaultBrowserLayer
    >>> from lp.testing.fixture import ZopeAdapterFixture

    >>> class ErrorView:
    ...     """A broken view"""
    ...
    ...     def __call__(self, *args, **kw):
    ...         raise Exception("Oops")
    ...
    >>> error_view_fixture = ZopeAdapterFixture(
    ...     ErrorView, (None, IDefaultBrowserLayer), Interface, "error-test"
    ... )
    >>> error_view_fixture.setUp()
    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     output = http("GET /error-test HTTP/1.1\nHost: launchpad.test\n")
    ...
    >>> output.getStatus()
    500
    >>> report()
    500s: 1
    5XXs: 1
    http requests: 1
    requests: 1
    statsd: errors.500,env=test: 1
    statsd: errors.5XX,env=test: 1
    statsd: requests.all,env=test: 1
    statsd: requests.http,env=test: 1

We also have a special metric counting server errors returned to known
web browsers (5XXs_b) - in the production environment we care more
about errors returned to people than robots crawling obscure parts of
the site.

    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     output = http(
    ...         dedent(
    ...             """\
    ...         GET /error-test HTTP/1.1
    ...         Host: launchpad.test
    ...         User-Agent: Mozilla/42.0
    ...         """
    ...         )
    ...     )
    ...
    >>> output.getStatus()
    500
    >>> report()
    500s: 1
    5XXs: 1
    5XXs_b: 1
    http requests: 1
    requests: 1
    statsd: errors.500,env=test: 1
    statsd: errors.5XX,env=test: 1
    statsd: errors.5XX.browser,env=test: 1
    statsd: requests.all,env=test: 1
    statsd: requests.http,env=test: 1

    >>> error_view_fixture.cleanUp()

Number of XML-RPC Faults
------------------------

    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     try:
    ...         opstats = lp_xmlrpc.invalid()  # XXX: Need a HTTP test too
    ...         print("Should have raised a Fault exception!")
    ...     except xmlrpc.client.Fault:
    ...         pass
    ...
    >>> report()
    requests: 1
    xml-rpc faults: 1
    xml-rpc requests: 1
    statsd: errors.xmlrpc,env=test: 1
    statsd: requests.all,env=test: 1
    statsd: requests.xmlrpc,env=test: 1


Number of soft timeouts
-----------------------

    >>> test_data = dedent(
    ...     """
    ...     [database]
    ...     soft_request_timeout: 1
    ...     """
    ... )
    >>> config.push("base_test_data", test_data)
    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     output = http(
    ...         dedent(
    ...             r"""
    ...         GET /+soft-timeout HTTP/1.1
    ...         Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ...         """
    ...         )
    ...     )
    ...
    >>> output.getStatus()
    200
    >>> report()
    2XXs: 1
    http requests: 1
    requests: 1
    soft timeouts: 1
    statsd: errors.2XX,env=test: 1
    statsd: requests.all,env=test: 1
    statsd: requests.http,env=test: 1
    statsd: timeouts.soft,env=test: 1

Number of Timeouts
------------------

We can't reliably track this using the 503 response code as other
Launchpad code may well return this status and an XML-RPC request may
also return a timeout Fault:

    >>> test_data = dedent(
    ...     """
    ...     [database]
    ...     db_statement_timeout: 1
    ...     soft_request_timeout: 2
    ...     """
    ... )
    >>> config.push("test_data", test_data)
    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     output = http(
    ...         dedent(
    ...             r"""
    ...         GET /+soft-timeout HTTP/1.1
    ...         Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ...         """
    ...         )
    ...     )
    ...
    >>> output.getStatus()
    503

Reset the timeouts so +opstats doesn't die.

    >>> base_test_data = config.pop("base_test_data")
    >>> report()
    503s: 1
    5XXs: 1
    http requests: 1
    requests: 1
    timeouts: 1
    statsd: errors.503,env=test: 1
    statsd: errors.5XX,env=test: 1
    statsd: requests.all,env=test: 1
    statsd: requests.http,env=test: 1
    statsd: timeouts.hard,env=test: 1


HTTP access for Cricket
-----------------------

Stats can also be retrieved via HTTP in cricket-graph format:

    >>> with MockPatchObject(statsd_client, "_client", stats_client):
    ...     output = http("GET / HTTP/1.1\nHost: launchpad.test\n")
    ...     output = http("GET / HTTP/1.1\nHost: launchpad.test\n")
    ...
    >>> print(http("GET /+opstats HTTP/1.1\nHost: launchpad.test\n"))
    HTTP/1.1 200 Ok
    ...
    Content-Type: text/plain;...charset=US-ASCII
    ...
    <BLANKLINE>
    1XXs:0@...
    2XXs:2@...
    3XXs:0@...
    404s:0@...
    4XXs:0@...
    500s:0@...
    503s:0@...
    5XXs:0@...
    6XXs:0@...
    http_requests:2@...
    requests:2@...
    soft_timeouts:0@...
    timeouts:0@...
    xmlrpc_faults:0@...
    xmlrpc_requests:0@...
    <BLANKLINE>

No DB access required
---------------------

Accessing the opstats page will make no database queries. This is important to
make it as reliable as possible since we use this page for monitoring. Because
of this property, the load balancers also use this page to determine if a
Launchpad instance is responsive.

To confirm this, we first point all our database connection information
to somewhere that doesn't exist.

    >>> no_db_overrides = """
    ...     [database]
    ...     rw_main_primary: dbname=nonexistent
    ...     rw_main_standby: dbname=nonexistent
    ...
    ...     [launchpad_session]
    ...     database: dbname=nonexistent
    ...     """
    >>> config.push("no_db", no_db_overrides)

Then we need to drop all our existing connections, so when we reconnect
the new connection information is used.

    >>> from storm.zope.interfaces import IZStorm
    >>> getUtility(IZStorm)._reset()

We can still access the opstats page.

    >>> print(http("GET /+opstats HTTP/1.1\nHost: launchpad.test\n"))
    HTTP/1.1 200 Ok
    ...
    Content-Type: text/plain;...charset=US-ASCII
    ...
    <BLANKLINE>
    1XXs:0@...

This is also true if we are provide authentication.

    >>> print(
    ...     http(
    ...         r"""
    ... GET /+opstats HTTP/1.1
    ... Host: launchpad.test
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
    Content-Type: text/plain;...charset=US-ASCII
    ...
    <BLANKLINE>
    1XXs:0@...

But our database connections are broken.

    >>> from lp.services.database.interfaces import IStore
    >>> from lp.registry.model.person import Person
    >>> IStore(Person).find(Person, name="janitor")
    Traceback (most recent call last):
    ...
    storm.exceptions.DisconnectionError:...
    FATAL:  database "nonexistent" does not exist

    >>> _ = config.pop("no_db")
    >>> getUtility(IZStorm)._reset()

    >>> print(IStore(Person).find(Person, name="janitor").one().name)
    janitor

Clean up.

    >>> _ = config.pop("statsd_test")
