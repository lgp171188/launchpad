************
Introduction
************

Some standard behaviour is defined by the web service itself, not by
the individual resources.

Multiple versions
=================

The Launchpad web service defines three versions: 'beta', '1.0', and
'devel'.

    >>> def me_link_for_version(version):
    ...     response = webservice.get("/", api_version=version)
    ...     print(response.jsonBody()["me_link"])
    ...

    >>> me_link_for_version("beta")
    http://api.launchpad.test/beta/people/+me

    >>> me_link_for_version("1.0")
    http://api.launchpad.test/1.0/people/+me

    >>> me_link_for_version("devel")
    http://api.launchpad.test/devel/people/+me

No other versions are available.

    >>> print(webservice.get("/", api_version="nosuchversion"))
    HTTP/1.1 404 Not Found
    ...


Anonymous requests
==================

A properly signed web service request whose OAuth token key is empty
is treated as an anonymous request.

    >>> root = "http://api.launchpad.test/beta"
    >>> body = anon_webservice.get(root).jsonBody()
    >>> print(body["projects_collection_link"])
    http://api.launchpad.test/beta/projects
    >>> print(body["me_link"])
    http://api.launchpad.test/beta/people/+me

Normally, Launchpad will reject any call made with an unrecognized
consumer key, because access tokens are registered with specific
consumer keys.

    >>> from lp.testing.pages import LaunchpadWebServiceCaller
    >>> from lp.services.oauth.interfaces import IOAuthConsumerSet

    >>> caller = LaunchpadWebServiceCaller("new-consumer", "access-key")
    >>> response = caller.get(root)
    >>> response.status
    401
    >>> print(six.ensure_text(response.body))
    Unknown consumer (new-consumer).

But with anonymous access there is no registration step. The first
time Launchpad sees a consumer key might be during an
anonymous request, and it can't reject that request just because it
doesn't recognize the client.

    >>> login(ANONYMOUS)
    >>> from zope.component import getUtility
    >>> consumer_set = getUtility(IOAuthConsumerSet)
    >>> print(consumer_set.getByKey("another-new-consumer"))
    None
    >>> logout()

    >>> caller = LaunchpadWebServiceCaller("another-new-consumer", "")
    >>> response = caller.get(root)
    >>> response.status
    200

Anonymous requests can't access certain data.

    >>> response = anon_webservice.get(body["me_link"])
    >>> response.status
    401
    >>> print(six.ensure_text(response.body))
    You need to be logged in to view this URL.

Anonymous requests can't change the dataset.

    >>> import json
    >>> data = json.dumps({"display_name": "This won't work"})
    >>> response = anon_webservice.patch(
    ...     root + "/~salgado", "application/json", data
    ... )
    >>> response.status
    401
    >>> print(six.ensure_text(response.body))
    (<Person salgado (Guilherme Salgado)>, 'display_name', 'launchpad.Edit')

A completely unsigned web service request is treated as an anonymous
request, with the OAuth consumer name being equal to the User-Agent.

    >>> agent = "unsigned-user-agent"
    >>> login(ANONYMOUS)
    >>> print(consumer_set.getByKey(agent))
    None
    >>> logout()

    >>> from lp.testing.pages import http
    >>> def request_with_user_agent(agent, url="/devel"):
    ...     if agent is None:
    ...         agent_string = ""
    ...     else:
    ...         agent_string = "\nUser-Agent: %s" % agent
    ...     request = (
    ...         "GET %s HTTP/1.1\n" "Host: api.launchpad.test" "%s\n\n"
    ...     ) % (url, agent_string)
    ...     return http(request)
    ...

    >>> response = request_with_user_agent(agent)
    >>> print(str(response))
    HTTP/1.1 200 Ok
    ...
    {...}

An unsigned request, like a request signed with the empty string,
isn't logged in as any particular user:

    >>> response = request_with_user_agent(agent, "/devel/people/+me")
    >>> print(str(response))
    HTTP/1.1 401 Unauthorized
    ...
    You need to be logged in to view this URL.


API Requests to other hosts
===========================

JavaScript working with the API must deal with the browser's Same Origin
Policy - requests may only be made to the host that the page was loaded
from.  For example, we can not visit a page on http://bugs.launchpad.net
and make a request to http://api.launchpad.net.

Instead of directing the request to api.launchpad.net, we may direct it
at the /api subpath of the current virtual host, such as
http://bugs.launchpad.net/api.  Such requests are handled as if they
were directed at the api.launchpad.net subdomain.

The URLs in the returned representations point to the current host,
rather than the api host.  The canonical_url() function also returns
links to the current host.

The ServiceRoot for http://bugs.launchpad.test/api/devel/ is the same as a
request to http://api.launchpad.net/beta/, but with the links pointing
to a different host.

    >>> webservice.domain = "bugs.launchpad.test"
    >>> root = webservice.get(
    ...     "http://bugs.launchpad.test/api/devel/"
    ... ).jsonBody()
    >>> print(root["people_collection_link"])
    http://bugs.launchpad.test/api/devel/people

Requests on these hosts also honor the standard Launchpad authorization
scheme (and don't require OAuth).

    >>> import base64
    >>> from lp.testing.pages import LaunchpadWebServiceCaller
    >>> noauth_webservice = LaunchpadWebServiceCaller(
    ...     domain="bugs.launchpad.test"
    ... )
    >>> sample_auth = "Basic %s" % base64.b64encode(
    ...     b"test@canonical.com:test"
    ... ).decode("ASCII")
    >>> print(
    ...     noauth_webservice.get(
    ...         "http://bugs.launchpad.test/api/devel/people/+me",
    ...         headers={"Authorization": sample_auth},
    ...     )
    ... )
    HTTP/1.1 303 See Other
    ...
    Location: http://bugs.launchpad.test/api/devel/~name12...
    ...

But the regular authentication still doesn't work on the normal API
virtual host: an attempt to do HTTP Basic Auth will be treated as an
anonymous request.

    >>> noauth_webservice.domain = "api.launchpad.test"
    >>> print(
    ...     noauth_webservice.get(
    ...         "http://api.launchpad.test/beta/people/+me",
    ...         headers={"Authorization": sample_auth},
    ...     )
    ... )
    HTTP/1.1 401 Unauthorized
    ...
    You need to be logged in to view this URL.


The 'Vary' Header
=================

Launchpad's web service sets the Vary header differently from other
parts of Launchpad.

    >>> browser.open("http://launchpad.test/")
    >>> print(browser.headers["Vary"])
    Cookie, Authorization

    >>> response = webservice.get("http://bugs.launchpad.test/api/devel/")
    >>> print(response.getheader("Vary"))
    Accept

The web service's Vary header does not mention the 'Cookie' header,
because the web service doesn't use cookies. It doesn't mention the
'Authorization' header, because every web service request has a
distinct 'Authorization' header. It does mention the 'Accept' header,
because the web service does use content negotiation.
