Launchpad Publication
=====================

Launchpad uses the generic Zope3 publisher. It registers several
factories that are responsible for instantiating the appropriate
implementation of zope.publisher.IRequest and
zope.publisher.IPublication for the request.


Virtual host configurations
---------------------------

The configuration defines a number of domains, one for the main
Launchpad site and one for the sites of the various applications.

    >>> from lp.services.config import config
    >>> config.vhost.mainsite.hostname
    'launchpad.test'
    >>> config.vhost.blueprints.hostname
    'blueprints.launchpad.test'

It also says whether we use http or https (although this setting can be
overridden for the root URL of a particular host).

    >>> config.vhosts.use_https
    False

These are parsed into webapp.vhost.allvhosts.

    >>> from lp.services.webapp.vhosts import allvhosts
    >>> allvhosts.use_https
    False
    >>> for confname, vhost in sorted(allvhosts.configs.items()):
    ...     print(confname, "@", vhost.hostname)
    ...     print("rooturl:", vhost.rooturl)
    ...     print("althosts:", (", ".join(vhost.althostnames)))
    ...     print("----")
    ...
    answers @ answers.launchpad.test
    rooturl: http://answers.launchpad.test/
    althosts:
    ----
    api @ api.launchpad.test
    rooturl: http://api.launchpad.test/
    althosts:
    ----
    blueprints @ blueprints.launchpad.test
    rooturl: http://blueprints.launchpad.test/
    althosts:
    ----
    bugs @ bugs.launchpad.test
    rooturl: http://bugs.launchpad.test/
    althosts:
    ----
    code @ code.launchpad.test
    rooturl: http://code.launchpad.test/
    althosts:
    ----
    feeds @ feeds.launchpad.test
    rooturl: http://feeds.launchpad.test/
    althosts:
    ----
    mainsite @ launchpad.test
    rooturl: http://launchpad.test/
    althosts: localhost
    ----
    testopenid @ testopenid.test
    rooturl: http://testopenid.test/
    althosts:
    ----
    translations @ translations.launchpad.test
    rooturl: http://translations.launchpad.test/
    althosts:
    ----
    xmlrpc @ xmlrpc.launchpad.test
    rooturl: http://xmlrpc.launchpad.test/
    althosts:
    ----
    xmlrpc_private @ xmlrpc-private.launchpad.test
    rooturl: http://xmlrpc-private.launchpad.test/
    althosts:
    ----

The hostnames and alternative hostnames for all virtual hosts are
collected into a set.  This provides a quick way to determine if a
request is headed to one of the officialy-used Launchpad host names:

    >>> for hostname in sorted(allvhosts.hostnames):
    ...     print(hostname)
    ...
    answers.launchpad.test
    api.launchpad.test
    blueprints.launchpad.test
    bugs.launchpad.test
    code.launchpad.test
    feeds.launchpad.test
    launchpad.test
    localhost
    testopenid.test
    translations.launchpad.test
    xmlrpc-private.launchpad.test
    xmlrpc.launchpad.test


VirtualHostRequestPublicationFactory
------------------------------------

A number of VirtualHostRequestPublicationFactories are registered with
Zope to handle requests for a particular vhost, port, and set of HTTP
methods.

    >>> import io
    >>> from lp.services.webapp.publication import LaunchpadBrowserPublication
    >>> from lp.services.webapp.servers import (
    ...     LaunchpadBrowserRequest,
    ...     VirtualHostRequestPublicationFactory,
    ... )
    >>> from zope.app.publication.interfaces import IRequestPublicationFactory
    >>> from lp.testing import verifyObject

Those factories provide the IRequestPublicationFactory interface.

    >>> factory = VirtualHostRequestPublicationFactory(
    ...     "mainsite", LaunchpadBrowserRequest, LaunchpadBrowserPublication
    ... )
    >>> verifyObject(IRequestPublicationFactory, factory)
    True

By default, the request publication factory will only handle requests
to all the host names registered for a particular virtual host.

    >>> environment = {"REQUEST_METHOD": "GET", "HTTP_HOST": "launchpad.test"}
    >>> factory.canHandle(environment)
    True

A request publication factory that was initialized with
handle_default_host=True will handle a request that specifies no virtual
host. By default, handle_default_host is False.

    >>> environment = {"REQUEST_METHOD": "GET"}
    >>> factory.canHandle(environment)
    False

    >>> default_handling_factory = VirtualHostRequestPublicationFactory(
    ...     "mainsite",
    ...     LaunchpadBrowserRequest,
    ...     LaunchpadBrowserPublication,
    ...     handle_default_host=True,
    ... )
    >>> default_handling_factory.canHandle(environment)
    True

By default, a request publication factory handles requests to any port
on its registered hosts.

    >>> environment = {
    ...     "REQUEST_METHOD": "GET",
    ...     "SERVER_PORT": "1234",
    ...     "HTTP_HOST": "launchpad.test",
    ... }
    >>> factory.canHandle(environment)
    True

It's a shortcoming of Zope that a request publication factory can only
consider aspects of the HTTP request when deciding whether or not to
handle the request (that is, in canHandle()). Our factories need to
consider the HTTP request when deciding what kind of publication and
request factory to send (that is, in __call__()). So we abuse
canHandle() by saving the environment to a thread-local variable. This
information is retrieved later on, in __call__().

    >>> for key, value in sorted(factory._thread_local.environment.items()):
    ...     print("%s: %s" % (key, value))
    ...
    HTTP_HOST: launchpad.test
    REQUEST_METHOD: GET
    SERVER_PORT: 1234

When the request publication factory is called, it normally returns
the configured request and publication factories.

    >>> requestfactory, publicationfactory = factory()
    >>> publicationfactory
    <class '...LaunchpadBrowserPublication'>

If the request comes in on one of the virtual hosts, the request
factory is wrapped in an ApplicationServerSettingRequestFactory that
will on instantiation set the base URL of the request to the virtual
host configured settings.

    >>> type(requestfactory)
    <class '...ApplicationServerSettingRequestFactory'>
    >>> request = requestfactory(io.BytesIO(), environment)
    >>> type(request)
    <class 'lp.services.webapp.servers.LaunchpadBrowserRequest'>
    >>> request.getApplicationURL()
    'http://launchpad.test'

But if the request comes in to the local or default host, the request
factory is not wrapped:

    >>> environment = {"REQUEST_METHOD": "GET", "HTTP_HOST": "localhost:9000"}
    >>> default_handling_factory.canHandle(environment)
    True
    >>> requestfactory, publicationfactory = default_handling_factory()
    >>> requestfactory
    <class 'lp.services.webapp.servers.LaunchpadBrowserRequest'>

    >>> environment = {"REQUEST_METHOD": "GET"}
    >>> default_handling_factory.canHandle(environment)
    True
    >>> requestfactory, publicationfactory = default_handling_factory()
    >>> requestfactory
    <class 'lp.services.webapp.servers.LaunchpadBrowserRequest'>

A request publication factory will not handle requests unless they're
directed to one of its registered host names.

    >>> environment = {
    ...     "REQUEST_METHOD": "GET",
    ...     "HTTP_HOST": "answers.launchpad.test",
    ... }
    >>> factory.canHandle(environment)
    False

Calling the factory on a request it can't handle will result in an
error:

    >>> requestfactory, publicationfactory = factory()
    Traceback (most recent call last):
      ...
    AssertionError: This factory declined the request.

The factory accepts a port parameter that will restrict the handled
requests to request to a particular port.

    >>> factory = VirtualHostRequestPublicationFactory(
    ...     "mainsite",
    ...     LaunchpadBrowserRequest,
    ...     LaunchpadBrowserPublication,
    ...     port=1234,
    ... )
    >>> environment = {"REQUEST_METHOD": "GET", "HTTP_HOST": "launchpad.test"}
    >>> factory.canHandle(environment)
    False
    >>> environment["SERVER_PORT"] = "80"
    >>> factory.canHandle(environment)
    False
    >>> environment["SERVER_PORT"] = "1234"
    >>> factory.canHandle(environment)
    True

The port is also checked for in the HTTP_HOST variable:

    >>> environment = {
    ...     "REQUEST_METHOD": "GET",
    ...     "HTTP_HOST": "launchpad.test:1234",
    ... }
    >>> factory.canHandle(environment)
    True
    >>> environment["HTTP_HOST"] = "launchpad.test:one_two_three_four"
    >>> factory.canHandle(environment)
    False

If the port is given twice (in SERVER_PORT and the Host header), the
value from SERVER_PORT takes precedence. (The rationale behind this is
that it's valid for a client to put launchpad.test:80 in the Host header,
but the request is really coming on the port 1234 because it's being
proxied.)

    >>> environment = {
    ...     "REQUEST_METHOD": "GET",
    ...     "SERVER_PORT": "1234",
    ...     "HTTP_HOST": "launchpad.test:80",
    ... }
    >>> factory.canHandle(environment)
    True

It's okay to specify the port in both places if the ports are the same:

    >>> environment = {
    ...     "REQUEST_METHOD": "GET",
    ...     "SERVER_PORT": 1234,
    ...     "HTTP_HOST": "launchpad.test:1234",
    ... }
    >>> factory.canHandle(environment)
    True

The VirtualHostRequestPublicationFactory constructor also accepts a
`methods` parameter that restrict the set of allowed methods. This
doesn't affect canHandle, but it does affect which requests will make
the request publication factory return a
ProtocolErrorPublicationFactory when called. The
ProtocolErrorPublicationFactory is a parameterized object that
publishes a document describing a particular HTTP-level error.

    >>> environment = {
    ...     "REQUEST_METHOD": "DELETE",
    ...     "HTTP_HOST": "launchpad.test",
    ...     "SERVER_PORT": "1234",
    ... }
    >>> factory.canHandle(environment)
    True

    >>> requestfactory, publicationfactory = factory()
    >>> publicationfactory
    <lp.services.webapp.servers.ProtocolErrorPublicationFactory ...>

    >>> factory = VirtualHostRequestPublicationFactory(
    ...     "mainsite",
    ...     LaunchpadBrowserRequest,
    ...     LaunchpadBrowserPublication,
    ...     methods=["DELETE"],
    ... )
    >>> environment = {"REQUEST_METHOD": "GET", "HTTP_HOST": "launchpad.test"}
    >>> factory.canHandle(environment)
    True
    >>> requestfactory, publicationfactory = factory()
    >>> publicationfactory
    <lp.services.webapp.servers.ProtocolErrorPublicationFactory ...>

    >>> environment["REQUEST_METHOD"] = "DELETE"
    >>> factory.canHandle(environment)
    True
    >>> requestfactory, publicationfactory = factory()
    >>> publicationfactory
    <class '...LaunchpadBrowserPublication'>


Zope Publisher integration
--------------------------

A factory is registered for each of our available virtual host. This
is done by the register_launchpad_request_publication_factories
function called when the servers module is loaded.

(We need to call it here once again, because the test layer clears out
the registered factories.)

    >>> from lp.services.webapp.servers import (
    ...     register_launchpad_request_publication_factories,
    ... )
    >>> register_launchpad_request_publication_factories()

    >>> from lp.testing.publication import (
    ...     get_request_and_publication,
    ...     print_request_and_publication,
    ... )

    >>> print_request_and_publication("launchpad.test")
    LaunchpadBrowserRequest
    MainLaunchpadPublication

    >>> print_request_and_publication("")
    LaunchpadBrowserRequest
    MainLaunchpadPublication

    >>> print_request_and_publication("launchpad.test", method="DELETE")
    ProtocolErrorRequest
    ProtocolErrorPublication: status=405
      Allow: GET, HEAD, POST

    >>> print_request_and_publication("api.launchpad.test")
    WebServiceClientRequest
    WebServicePublication

    >>> print_request_and_publication("feeds.launchpad.test")
    FeedsBrowserRequest
    FeedsPublication

The web service RequestPublicationFactory responds to the six most
common HTTP methods, but it will only accept a MIME type of
application/json.

    >>> for m in ["GET", "HEAD", "DELETE", "OPTIONS"]:
    ...     print_request_and_publication("api.launchpad.test", method=m)
    ...
    WebServiceClientRequest
    WebServicePublication
    WebServiceClientRequest
    WebServicePublication
    WebServiceClientRequest
    WebServicePublication
    WebServiceClientRequest
    WebServicePublication


    >>> for m in ["POST", "PUT"]:
    ...     print_request_and_publication(
    ...         "api.launchpad.test", method=m, mime_type="application/json"
    ...     )
    ...
    WebServiceClientRequest
    WebServicePublication
    WebServiceClientRequest
    WebServicePublication

When a request for '/api' is made to one of the application
virtualhosts, such as the application root, it is also handled by the
web service request and publication:

    >>> print_request_and_publication(
    ...     "launchpad.test",
    ...     method="GET",
    ...     extra_environment={"PATH_INFO": "/api"},
    ... )
    WebServiceClientRequest
    WebServicePublication

Requests for '/api' on other hosts like feeds are handled like
other requests on these hosts:

    >>> print_request_and_publication(
    ...     "feeds.launchpad.test",
    ...     method="GET",
    ...     extra_environment={"PATH_INFO": "/api"},
    ... )
    FeedsBrowserRequest
    FeedsPublication

The XML-RPC RequestPublicationFactory only responds to POST requests,
and then only when the MIME type is text/xml.

    >>> print_request_and_publication(
    ...     "xmlrpc.launchpad.test", method="POST", mime_type="text/xml"
    ... )
    PublicXMLRPCRequest
    PublicXMLRPCPublication

    >>> print_request_and_publication(
    ...     "xmlrpc.launchpad.test",
    ...     method="POST",
    ...     mime_type="text/xml; charset=utf-8",
    ... )
    PublicXMLRPCRequest
    PublicXMLRPCPublication

    >>> print_request_and_publication("xmlrpc.launchpad.test", method="GET")
    ProtocolErrorRequest
    ProtocolErrorPublication: status=405
      Allow: POST

    >>> print_request_and_publication(
    ...     "xmlrpc.launchpad.test",
    ...     method="POST",
    ...     mime_type="application/xml",
    ... )
    ProtocolErrorRequest
    ProtocolErrorPublication: status=415

The private XML-RPC server works just like the public one, but it only
listens on a particular port.

Find the port the Private XMLRPC service is listening on.

    >>> private_port = config.vhost.xmlrpc_private.private_port
    >>> print_request_and_publication(
    ...     "xmlrpc-private.launchpad.test",
    ...     method="POST",
    ...     mime_type="application/xml",
    ... )
    ProtocolErrorRequest
    ProtocolErrorPublication: status=404

Try a normal request:

    >>> print_request_and_publication(
    ...     "xmlrpc-private.launchpad.test",
    ...     port=private_port,
    ...     method="POST",
    ...     mime_type="text/xml",
    ... )
    PrivateXMLRPCRequest
    PrivateXMLRPCPublication

    >>> print_request_and_publication(
    ...     "xmlrpc-private.launchpad.test",
    ...     port=private_port,
    ...     method="POST",
    ...     mime_type="text/xml; charset=utf-8",
    ... )
    PrivateXMLRPCRequest
    PrivateXMLRPCPublication

A request to an unknown host results in a 404 error.

    >>> print_request_and_publication("nosuchhost.launchpad.test")
    ProtocolErrorRequest
    ProtocolErrorPublication: status=404

Now some tests that do full HTTP calls using http() to get various
errors. I'm going to temporarily bump up the log level so that these
errors aren't logged as exceptions--that would make the tests look
less nice.

    >>> import logging
    >>> logger = logging.getLogger("SiteError")
    >>> old_level = logger.level
    >>> logger.setLevel(logging.CRITICAL)

    >>> logout()
    >>> from lp.testing.pages import http
    >>> print(http("GET / HTTP/1.1\n" "Host: nosuchhost.launchpad.test"))
    HTTP/1.1 404 Not Found
    ...

    >>> print(http("GET /foo/bar HTTP/1.1\n" "Host: xmlrpc.launchpad.test"))
    HTTP/1.1 405 Method Not Allowed
    Allow: POST
    ...
    Your request didn't fit the protocol expected by this server.
    ...

(A bit of cleanup so the test can continue:)

    >>> logger.setLevel(old_level)
    >>> login(ANONYMOUS)


ILaunchpadBrowserApplicationRequest
-----------------------------------

All Launchpad requests provides the ILaunchpadBrowserApplicationRequest
interface. That interface is an extension of the zope standard
IBrowserApplicationRequest.

    >>> from lp.services.webapp.interfaces import (
    ...     ILaunchpadBrowserApplicationRequest,
    ... )

    >>> request, publication = get_request_and_publication()
    >>> verifyObject(ILaunchpadBrowserApplicationRequest, request)
    True


Handling form data using IBrowserFormNG
---------------------------------------

Submitted form data is available in the form_ng request attribute. This
is an object providing the IBrowserFormNG interface which offers two
methods to obtain form data. (Form data is also available through the
regular Zope3 form attribute using the dictionary interface.)

    >>> from lp.services.webapp.interfaces import IBrowserFormNG
    >>> verifyObject(IBrowserFormNG, request.form_ng)
    True

You can check the presence of an uploaded field using the regular
python 'in' operator.

    >>> from lp.services.webapp.servers import LaunchpadBrowserRequest
    >>> from urllib.parse import urlencode
    >>> environment = {
    ...     "QUERY_STRING": urlencode(
    ...         {"a_field": "a_value", "items_field": [1, 2, 3]}, doseq=True
    ...     )
    ... }
    >>> request = LaunchpadBrowserRequest("", environment)
    >>> request.processInputs()

    >>> "a_field" in request.form_ng
    True
    >>> "another_field" in request.form_ng
    False

The advantage of the IBrowserFormNG API is that it offers methods that
checks the number of values you are expecting. The getOne() method
should be used when you expect only one value for the field.

    >>> print(request.form_ng.getOne("a_field"))
    a_value

UnexpectedFormData is raised if more than one value was submitted for
the field:

    >>> request.form_ng.getOne("items_field")
    Traceback (most recent call last):
      ...
    lp.app.errors.UnexpectedFormData: ...

None is returned if the field wasn't submitted:

    >>> request.form_ng.getOne("another_field") is None
    True

You can provide a default value that is returned if the field wasn't
submitted:

    >>> print(request.form_ng.getOne("another_field", "default"))
    default

The getAll() method should be used when you are expecting a list of
values.

    >>> for item in request.form_ng.getAll("items_field"):
    ...     print(item)
    ...
    1
    2
    3

If only one value was submitted, it will still be returned as part of
a list:

    >>> for item in request.form_ng.getAll("a_field"):
    ...     print(item)
    ...
    a_value

An empty list is returned when no value was submitted for the field:

    >>> request.form_ng.getAll("another_field")
    []

That method also accepts a default value that is to be returned when
no value was submitted with the field.

    >>> for item in request.form_ng.getAll("another_field", ["default"]):
    ...     print(item)
    ...
    default

All the submitted field names can be iterated over:

    >>> for name in sorted(request.form_ng):
    ...     print(name)
    ...
    a_field
    items_field


Page ID
-------

Our publication implementation sets a WSGI variable 'launchpad.pageid'.
This is an identifier of the form ContextName:ViewName.  We also set the
'pageid' key in the Talisker logging context.

    >>> from talisker.context import Context
    >>> from talisker.logs import logging_context
    >>> from lp.services.webapp.interfaces import IPlacelessAuthUtility
    >>> _ = Context.new()
    >>> auth_utility = getUtility(IPlacelessAuthUtility)
    >>> request, publication = get_request_and_publication()
    >>> request.setPrincipal(auth_utility.unauthenticatedPrincipal())

Originally, this variable isn't set.

    >>> "launchpad.pageid" in request._orig_env
    False
    >>> "pageid" in logging_context.flat
    False
    >>> logout()

It is set during the afterTraversal() hook. The pageid is made of the
name of the context class and the view class name.

    >>> class TestView:
    ...     """A very simple view."""
    ...
    ...     def __init__(self, context, request):
    ...         self.context = context
    ...         self.request = request
    ...
    ...     def __call__(self):
    ...         return "Result"
    ...

    >>> class TestContext:
    ...     """Test context object."""
    ...

    >>> view = TestView(TestContext(), request)
    >>> publication.beforeTraversal(request)
    >>> publication.afterTraversal(request, view)
    >>> print(request._orig_env["launchpad.pageid"])
    TestContext:TestView
    >>> print(logging_context.flat["pageid"])
    TestContext:TestView
    >>> from lp.services.webapp.adapter import (
    ...     clear_request_started,
    ...     set_request_started,
    ... )
    >>> clear_request_started()


Durations
---------

Similarly to our page IDs, our publication implementation will store the
durations for the traversal and object publication processes in the Talisker
logging context.

    >>> import time
    >>> _ = Context.new()
    >>> request, publication = get_request_and_publication()
    >>> request.setPrincipal(auth_utility.unauthenticatedPrincipal())
    >>> logout()

For traversal we start counting the duration during the beforeTraversal()
hook and stop the count in afterTraversal().  The duration is then available
as traversal_duration_ms in the Talisker logging context.  On Python >= 3.3,
there is also traversal_thread_duration_ms with the time spent in the
current thread.

    >>> "traversal_duration_ms" in logging_context.flat
    False
    >>> "traversal_thread_duration_ms" in logging_context.flat
    False
    >>> publication.beforeTraversal(request)
    >>> publication.afterTraversal(request, None)
    >>> "traversal_duration_ms" in logging_context.flat
    True
    >>> if hasattr(time, "CLOCK_THREAD_CPUTIME_ID"):
    ...     "traversal_thread_duration_ms" in logging_context.flat
    ... else:
    ...     True
    ...
    True

For publication we start counting the duration during the callObject()
hook and stop the count in afterCall().  The duration is then available as
publication_duration_ms in the Talisker logging context.  On Python >= 3.3,
there is also publication_thread_duration_ms with the time spent in the
current thread.

    >>> "publication_duration_ms" in logging_context.flat
    False
    >>> "publication_thread_duration_ms" in logging_context.flat
    False
    >>> print(
    ...     publication.callObject(request, TestView(TestContext(), request))
    ... )
    Result
    >>> publication.afterCall(request, None)
    >>> "publication_duration_ms" in logging_context.flat
    True
    >>> if hasattr(time, "CLOCK_THREAD_CPUTIME_ID"):
    ...     "publication_thread_duration_ms" in logging_context.flat
    ... else:
    ...     True
    ...
    True
    >>> publication.endRequest(request, None)

If an exception is raised during traversal or object publication, we'll
store the durations up to the point in which the exception is raised.  This
is done inside the handleException() hook.  (The hook also sets and resets
the request timer from lp.services.webapp.adapter, so you'll notice
some calls to prepare that code to what handleException expects.)

If the exception is raised before we even start the traversal, then
there's nothing to store.

    >>> logger.setLevel(logging.CRITICAL)
    >>> _ = Context.new()
    >>> request, publication = get_request_and_publication()
    >>> request.setPrincipal(auth_utility.unauthenticatedPrincipal())
    >>> import sys
    >>> try:
    ...     raise Exception()
    ... except:
    ...     exc_info = sys.exc_info()
    ...
    >>> set_request_started()
    >>> publication.handleException(
    ...     None, request, exc_info, retry_allowed=False
    ... )
    >>> "traversal_duration_ms" in logging_context.flat
    False
    >>> "traversal_thread_duration_ms" in logging_context.flat
    False
    >>> "publication_duration_ms" in logging_context.flat
    False
    >>> "publication_thread_duration_ms" in logging_context.flat
    False
    >>> clear_request_started()

If we started the traversal, but haven't finished it, we'll only have
the duration for the traversal and not for the publication.

    >>> publication.beforeTraversal(request)
    >>> publication.handleException(
    ...     None, request, exc_info, retry_allowed=False
    ... )
    >>> "traversal_duration_ms" in logging_context.flat
    True
    >>> if hasattr(time, "CLOCK_THREAD_CPUTIME_ID"):
    ...     "traversal_thread_duration_ms" in logging_context.flat
    ... else:
    ...     True
    ...
    True
    >>> "publication_duration_ms" in logging_context.flat
    False
    >>> "publication_thread_duration_ms" in logging_context.flat
    False
    >>> clear_request_started()

If we started the publication (which means the traversal has been
completed), we'll have the duration for the traversal and the duration for
the publication, up to the point where it was forcefully stopped.

    >>> publication.afterTraversal(request, None)
    >>> print(
    ...     publication.callObject(request, TestView(TestContext(), request))
    ... )
    Result
    >>> set_request_started()
    >>> publication.handleException(
    ...     None, request, exc_info, retry_allowed=False
    ... )
    >>> "traversal_duration_ms" in logging_context.flat
    True
    >>> if hasattr(time, "CLOCK_THREAD_CPUTIME_ID"):
    ...     "traversal_thread_duration_ms" in logging_context.flat
    ... else:
    ...     True
    ...
    True
    >>> "publication_duration_ms" in logging_context.flat
    True
    >>> if hasattr(time, "CLOCK_THREAD_CPUTIME_ID"):
    ...     "publication_thread_duration_ms" in logging_context.flat
    ... else:
    ...     True
    ...
    True
    >>> publication.endRequest(request, None)
    >>> logger.setLevel(old_level)

When a Retry or DisconnectionError exception is raised and the request
supports retry, it will be retried with a copy of the WSGI environment.
If that happens, though, we'll remove the
{publication,traversal}{,thread}duration variables from there, and unwind
the Talisker logging context.

    >>> _ = Context.new()
    >>> request, publication = get_request_and_publication()
    >>> publication.initializeLoggingContext(request)
    >>> request.setPrincipal(auth_utility.unauthenticatedPrincipal())
    >>> _ = logging_context.push(
    ...     traversal_duration_ms=500,
    ...     traversal_thread_duration_ms=400,
    ...     publication_duration_ms=500,
    ...     publication_thread_duration_ms=400,
    ... )
    >>> request.supportsRetry()
    True
    >>> from zope.publisher.interfaces import Retry
    >>> foo_exc_info = (Exception, "foo", None)
    >>> try:
    ...     raise Retry(foo_exc_info)
    ... except:
    ...     publication.handleException(
    ...         None, request, sys.exc_info(), retry_allowed=True
    ...     )
    ...
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.Retry: foo

    >>> "publication_duration_ms" in logging_context.flat
    False
    >>> "publication_thread_duration_ms" in logging_context.flat
    False
    >>> "traversal_duration_ms" in logging_context.flat
    False
    >>> "traversal_thread_duration_ms" in logging_context.flat
    False

    >>> _ = Context.new()
    >>> request, publication = get_request_and_publication()
    >>> publication.initializeLoggingContext(request)
    >>> request.setPrincipal(auth_utility.unauthenticatedPrincipal())
    >>> _ = logging_context.push(
    ...     traversal_duration_ms=500,
    ...     traversal_thread_duration_ms=400,
    ...     publication_duration_ms=500,
    ...     publication_thread_duration_ms=400,
    ... )
    >>> request.supportsRetry()
    True
    >>> from storm.exceptions import DisconnectionError
    >>> try:
    ...     raise DisconnectionError("foo DisconnectionError")
    ... except:
    ...     exc_info = sys.exc_info()
    ...
    >>> publication.handleException(
    ...     None, request, exc_info, retry_allowed=True
    ... )
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.Retry: foo DisconnectionError

    >>> "publication_duration_ms" in logging_context.flat
    False
    >>> "publication_thread_duration_ms" in logging_context.flat
    False
    >>> "traversal_duration_ms" in logging_context.flat
    False
    >>> "traversal_thread_duration_ms" in logging_context.flat
    False

Of course, any request can only be retried a certain number of times and
when we reach that number of retries we don't pop the durations from the
WSGI env.

    >>> _ = Context.new()
    >>> request, publication = get_request_and_publication()
    >>> publication.initializeLoggingContext(request)
    >>> request.setPrincipal(auth_utility.unauthenticatedPrincipal())
    >>> _ = logging_context.push(
    ...     traversal_duration_ms=500,
    ...     traversal_thread_duration_ms=400,
    ...     publication_duration_ms=500,
    ...     publication_thread_duration_ms=400,
    ... )
    >>> request.supportsRetry = lambda: False
    >>> request.supportsRetry()
    False
    >>> from zope.publisher.interfaces import Retry
    >>> try:
    ...     raise Retry(foo_exc_info)
    ... except:
    ...     publication.handleException(
    ...         None, request, sys.exc_info(), retry_allowed=True
    ...     )
    ...
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.Retry: foo

    >>> logging_context.flat["publication_duration_ms"]
    500
    >>> logging_context.flat["publication_thread_duration_ms"]
    400
    >>> logging_context.flat["traversal_duration_ms"]
    500
    >>> logging_context.flat["traversal_thread_duration_ms"]
    400

(A bit of cleanup so the test can continue)

    >>> login(ANONYMOUS)


Transaction Logging
-------------------

The publication implementation is responsible for putting the name
of the logged in user in the transaction. (The afterCall() hook is
responsible for that part. In these examples, None is passed as the
published object, because the implementation doesn't make use of it.)

The user attribute is an empty string, when no user is logged in.

    >>> import transaction
    >>> txn = transaction.begin()
    >>> request, publication = get_request_and_publication()
    >>> print(request.principal)
    None

    # Our afterCall() implementation expects to find _publication_start and
    # _publication_thread_start in its request, which are set by
    # callObject(). Since we don't want to callObject() here, we'll
    # have to change the request manually.
    >>> request._publication_start = 1.345
    >>> request._publication_thread_start = None
    >>> publication.afterCall(request, None)
    >>> print(txn.user)
    <BLANKLINE>

But if there is a logged in user, the transaction user attribute will
contain its ID (as well as an empty '/' path, which is a Zope artefact
allowing different authentication based on the traversed objects):

    >>> from lp.registry.interfaces.person import IPersonSet
    >>> personset = getUtility(IPersonSet)
    >>> txn = transaction.begin()
    >>> foo_bar = personset.getByEmail("foo.bar@canonical.com")
    >>> foo_bar.id
    16
    >>> request.setPrincipal(foo_bar)
    >>> publication.afterCall(request, None)
    >>> print(txn.user)
     / 16


Read-Only Requests
------------------

Our publication implementation make sure that requests supposed to be
read-only (GET and HEAD) don't change anything in the database.
(Actually, if the published method calls transaction.commit() itself,
that assumption won't hold.)

This is handled by the finishReadOnlyRequest() hook, which is called by
afterCall().  For example, this publication subclass will simply print
some string in its finishReadOnlyRequest().

    >>> class MyPublication(LaunchpadBrowserPublication):
    ...     def finishReadOnlyRequest(self, txn):
    ...         print("booo!")
    ...

    >>> publication = MyPublication(None)
    >>> publication.afterCall(request, None)
    booo!

In the default implementation, the following database modification will
be automatically reverted in a GET request.

    >>> from lp.services.identity.model.emailaddress import EmailAddress
    >>> from lp.services.database.interfaces import IPrimaryStore
    >>> from lp.registry.model.person import Person
    >>> login("foo.bar@canonical.com")
    >>> txn = transaction.begin()
    >>> def get_foo_bar_person():
    ...     return (
    ...         IPrimaryStore(Person)
    ...         .find(
    ...             Person,
    ...             Person.id == EmailAddress.personID,
    ...             EmailAddress.email == "foo.bar@canonical.com",
    ...         )
    ...         .one()
    ...     )
    ...
    >>> foo_bar = get_foo_bar_person()
    >>> print(foo_bar.description)
    None
    >>> foo_bar.description = "Montreal"

    >>> request, publication = get_request_and_publication(method="GET")

    # Our afterCall() implementation expects to find _publication_start and
    # _publication_thread_start in its request, which are set by
    # callObject(). Since we don't want to callObject() here, we'll
    # have to change the request manually.
    >>> request._publication_start = 1.345
    >>> request._publication_thread_start = None
    >>> publication.afterCall(request, None)
    >>> txn = transaction.begin()
    >>> foo_bar = get_foo_bar_person()
    >>> print(foo_bar.description)
    None

But not if the request uses POST, the changes will be preserved.

    >>> txn = transaction.begin()
    >>> get_foo_bar_person().description = "Darwin"

    >>> request, publication = get_request_and_publication(method="POST")

    # Our afterCall() implementation expects to find _publication_start and
    # _publication_thread_start in its request, which are set by
    # callObject(). Since we don't want to callObject() here, we'll
    # have to change the request manually.
    >>> request._publication_start = 1.345
    >>> request._publication_thread_start = None
    >>> publication.afterCall(request, None)
    >>> txn = transaction.begin()
    >>> print(get_foo_bar_person().description)
    Darwin


Doomed transactions are aborted
-------------------------------

Doomed transactions are aborted.

    >>> request, publication = get_request_and_publication(method="POST")
    >>> txn = transaction.begin()

    # This sets up an alert so we can easily see that the transaction has
    # been aborted.
    >>> bound_abort = txn.abort
    >>> def faux_abort():
    ...     bound_abort()
    ...     print("Aborted")
    ...
    >>> txn.abort = faux_abort

    # Now we doom the transaction.
    >>> txn.doom()
    >>> txn.isDoomed()
    True

    # Our afterCall() implementation expects to find _publication_start and
    # _publication_thread_start in its request, which are set by
    # callObject(). Since we don't want to callObject() here, we'll
    # have to change the request manually.
    >>> request._publication_start = 1.345
    >>> request._publication_thread_start = None

    >>> publication.afterCall(request, None)
    Aborted
    >>> txn.isDoomed()  # It is still doomed.
    True
    >>> del txn.abort  # Clean up test fixture.


Requests on Python C Methods succeed
------------------------------------

Rarely but occasionally, it is possible to traverse to a Python C method.
For instance, an XMLRPC proxy might allow a traversal to __repr__.
`callObject` handles these methods itself, since Zope's
`zope.publisher.publish.mapply` cannot.

    >>> request.setPrincipal(auth_utility.unauthenticatedPrincipal())
    >>> publication.callObject(request, {}.__repr__)
    '{}'
    >>> import zope.security.checker
    >>> publication.callObject(
    ...     request, zope.security.checker.ProxyFactory({}).__repr__
    ... )
    '{}'


HEAD requests have empty body
-----------------------------

The publication implementation also makes sure that no body is
returned as part of HEAD requests. (Again this is handled by the
afterCall() publication hook.)

    >>> txn = transaction.begin()
    >>> request, publication = get_request_and_publication(method="HEAD")
    >>> response = request.response
    >>> response.setResult("Content that will disappear.")

    # Our afterCall() implementation expects to find _publication_start and
    # _publication_thread_start in its request, which are set by
    # callObject(). Since we don't want to callObject() here, we'll
    # have to change the request manually.
    >>> request._publication_start = 1.345
    >>> request._publication_thread_start = None
    >>> publication.afterCall(request, None)
    >>> print(six.ensure_text(request.response.consumeBody()))
    <BLANKLINE>

In other cases, like a GET, the body would be unchanged.

    >>> txn = transaction.begin()
    >>> request, publication = get_request_and_publication(method="GET")
    >>> response = request.response
    >>> response.setResult("Some boring content.")

    # Our afterCall() implementation expects to find _publication_start and
    # _publication_thread_start in its request, which are set by
    # callObject(). Since we don't want to callObject() here, we'll
    # have to change the request manually.
    >>> request._publication_start = 1.345
    >>> request._publication_thread_start = None
    >>> publication.afterCall(request, None)
    >>> print(six.ensure_text(request.response.consumeBody()))
    Some boring content.


Authentication of requests
--------------------------

In LaunchpadBrowserPublication, authentication happens in the
beforeTraversal() hook. Our publication will set the principal to
the value of the getPrincipal().

For example, this publication subclass returns a marker object that
will get associated with the request after the beforeTraversal() hook.

    >>> marker = object()
    >>> class MyPublication(LaunchpadBrowserPublication):
    ...     def getPrincipal(self, request):
    ...         return marker
    ...

    >>> publication = MyPublication(None)
    >>> from lp.services.webapp.servers import LaunchpadTestRequest
    >>> request = LaunchpadTestRequest()

    # We need to close the previous interaction.
    >>> from zope.security.management import endInteraction
    >>> endInteraction()

    # The call to beforeTraversal will start a request that will need
    # to be manually ended.
    >>> publication.beforeTraversal(request)
    >>> request.principal is marker
    True

The default implementation will use the IPlacelessAuthentication
utility to setup the request.

    >>> import base64
    >>> login(ANONYMOUS)  # Get rid of the marker object in the interaction.
    >>> foo_bar_auth = "Basic %s" % (
    ...     base64.b64encode(b"foo.bar@canonical.com:test").decode("ASCII")
    ... )
    >>> request, publication = get_request_and_publication(
    ...     extra_environment=dict(HTTP_AUTHORIZATION=foo_bar_auth)
    ... )
    >>> principal = publication.getPrincipal(request)
    >>> print(principal.title)
    Foo Bar

The feeds implementation always returns the anonymous user.

    >>> request, publication = get_request_and_publication(
    ...     "feeds.launchpad.test",
    ...     extra_environment=dict(HTTP_AUTHORIZATION=foo_bar_auth),
    ... )
    >>> principal = publication.getPrincipal(request)

    >>> from zope.authentication.interfaces import IUnauthenticatedPrincipal
    >>> IUnauthenticatedPrincipal.providedBy(principal)
    True

The webservice implementation returns the principal for the person
associated with the OAuth access token specified in the request.  The
principal's access_level and scope will match what was specified in the
token.

    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.services.database.policy import PrimaryDatabasePolicy
    >>> from lp.services.database.interfaces import IStoreSelector
    >>> from lp.services.oauth.interfaces import IOAuthConsumerSet
    >>> from lp.services.webapp.interfaces import OAuthPermission
    >>> getUtility(IStoreSelector).push(PrimaryDatabasePolicy())
    >>> salgado = getUtility(IPersonSet).getByName("salgado")
    >>> consumer = getUtility(IOAuthConsumerSet).getByKey("foobar123451432")
    >>> token, _ = consumer.newRequestToken()
    >>> firefox = getUtility(IProductSet)["firefox"]
    >>> token.review(salgado, OAuthPermission.WRITE_PUBLIC, context=firefox)
    >>> access_token, access_secret = token.createAccessToken()
    >>> form = dict(
    ...     oauth_consumer_key="foobar123451432",
    ...     oauth_token=access_token.key,
    ...     oauth_version="1.0",
    ...     oauth_signature_method="PLAINTEXT",
    ...     oauth_signature="&".join(["", access_secret]),
    ...     oauth_timestamp=time.time(),
    ...     oauth_nonce="4572616e48616d6d65724c61686176",
    ... )
    >>> policy = getUtility(IStoreSelector).pop()
    >>> test_request, publication = get_request_and_publication(
    ...     "api.launchpad.test",
    ...     "GET",
    ...     extra_environment=dict(QUERY_STRING=urlencode(form)),
    ... )
    >>> test_request.processInputs()
    >>> principal = publication.getPrincipal(test_request)
    >>> print(principal.title)
    Guilherme Salgado
    >>> principal.access_level
    <DBItem AccessLevel.WRITE_PUBLIC...
    >>> print(principal.scope_url)
    /firefox

If the token is expired or doesn't exist, an Unauthorized exception is
raised, though.

    # Must login in order to edit the token.
    >>> login("salgado@ubuntu.com")
    >>> from datetime import datetime, timedelta, timezone
    >>> now = datetime.now(timezone.utc)
    >>> access_token.date_expires = now - timedelta(days=1)
    >>> form2 = form.copy()
    >>> form2["oauth_nonce"] = "1764572616e48616d6d65724c61686"
    >>> test_request = LaunchpadTestRequest(form=form2)
    >>> publication.getPrincipal(test_request)
    Traceback (most recent call last):
    ...
    lp.services.oauth.interfaces.TokenException: Expired token...

    >>> access_token.date_expires = now + timedelta(days=1)

    >>> form2 = form.copy()
    >>> form2["oauth_token"] += "z"
    >>> form2["oauth_nonce"] = "4572616e48616d6d65724c61686176"
    >>> test_request = LaunchpadTestRequest(form=form2)
    >>> publication.getPrincipal(test_request)
    Traceback (most recent call last):
    ...
    lp.services.oauth.interfaces.TokenException: Unknown access token...

The consumer must be registered as well, and the signature must be
correct.

    >>> form2 = form.copy()
    >>> form2["oauth_consumer_key"] += "z"
    >>> test_request = LaunchpadTestRequest(form=form2)
    >>> publication.getPrincipal(test_request)
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized:
    Unknown consumer (foobar123451432z).

    >>> form2 = form.copy()
    >>> form2["oauth_signature"] += "z"
    >>> form2["oauth_nonce"] = "2616e48616d6d65724c61686176457"
    >>> test_request = LaunchpadTestRequest(form=form2)
    >>> publication.getPrincipal(test_request)
    Traceback (most recent call last):
    ...
    lp.services.oauth.interfaces.TokenException: Invalid signature.

The user's account must be active.

    >>> from lp.services.identity.interfaces.account import AccountStatus

    >>> login("foo.bar@canonical.com")
    >>> salgado.setAccountStatus(AccountStatus.SUSPENDED, None, "Bye")

    >>> login("salgado@ubuntu.com")
    >>> test_request = LaunchpadTestRequest(form=form)
    >>> publication.getPrincipal(test_request)
    Traceback (most recent call last):
    ...
    lp.services.oauth.interfaces.TokenException: Inactive account.

Close the bogus request that was started by the call to
beforeTraversal, in order to ensure we leave our state sane.
Also, pop all the database policies we have been accumulating.

    >>> publication.endRequest(request, None)
    >>> store_selector = getUtility(IStoreSelector)
    >>> while store_selector.get_current():
    ...     db_policy = store_selector.pop()
    ...
