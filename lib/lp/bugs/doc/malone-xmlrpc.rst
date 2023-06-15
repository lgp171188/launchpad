XML-RPC Integration with Malone
===============================

Malone provides an XML-RPC interface for filing bugs.

    >>> import xmlrpc.client
    >>> from lp.testing.xmlrpc import XMLRPCTestTransport
    >>> filebug_api = xmlrpc.client.ServerProxy(
    ...     "http://test@canonical.com:test@xmlrpc.launchpad.test/bugs/",
    ...     transport=XMLRPCTestTransport(),
    ... )


The filebug API
---------------

The filebug API is:

    filebug_api.filebug(params)

params is a dict, with the following keys:

REQUIRED ARGS: summary: A string
               comment: A string

OPTIONAL ARGS: product: The product name, as a string. Default None.
               distro: The distro name, as a string. Default None.
               package: A string, allowed only if distro is specified.
                        Default None.
               security_related: Is this a security vulnerability?
                                 Default False.
               subscribers: A list of email addresses. Default None.

Either product or distro must be provided.

The bug owner is the currently authenticated user, taken from the
request.

The return value is the bug URL, in short form, e.g.:

    http://launchpad.net/bugs/42

Support for attachments will be added in the near future.


Examples
--------

First, let's define a simple event listener to show that the
IObjectCreatedEvent is being published when a bug is reported through
the XML-RPC interface.

    >>> from lazr.lifecycle.interfaces import IObjectCreatedEvent
    >>> from lp.bugs.interfaces.bug import IBug
    >>> from lp.testing.fixture import ZopeEventHandlerFixture

    >>> def on_created_event(obj, event):
    ...     print("ObjectCreatedEvent: %r" % obj)
    ...

    >>> on_created_listener = ZopeEventHandlerFixture(
    ...     on_created_event, (IBug, IObjectCreatedEvent)
    ... )
    >>> on_created_listener.setUp()

Reporting a product bug.

(We'll define a simple function to extract the bug ID from the URL
return value.)

    >>> def get_bug_id_from_url(url):
    ...     return int(url.split("/")[-1])
    ...

    >>> params = dict(
    ...     product="firefox", summary="the summary", comment="the comment"
    ... )
    >>> bug_url = filebug_api.filebug(params)
    ObjectCreatedEvent: <Bug ...>
    >>> print(bug_url)
    http://bugs.launchpad.test/bugs/...

    >>> from zope.component import getUtility
    >>> from lp.bugs.interfaces.bug import IBugSet

    >>> bugset = getUtility(IBugSet)
    >>> bug = bugset.get(get_bug_id_from_url(bug_url))

    >>> print(bug.title)
    the summary
    >>> print(bug.description)
    the comment
    >>> print(bug.owner.name)
    name12

    >>> firefox_bug = bug.bugtasks[0]

    >>> print(firefox_bug.product.name)
    firefox

Reporting a distro bug.

    >>> params = dict(
    ...     distro="ubuntu", summary="another bug", comment="another comment"
    ... )
    >>> bug_url = filebug_api.filebug(params)
    ObjectCreatedEvent: <Bug ...>
    >>> print(bug_url)
    http://bugs.launchpad.test/bugs/...

    >>> bug = bugset.get(get_bug_id_from_url(bug_url))

    >>> print(bug.title)
    another bug
    >>> print(bug.description)
    another comment
    >>> print(bug.owner.name)
    name12

    >>> ubuntu_bug = bug.bugtasks[0]

    >>> print(ubuntu_bug.distribution.name)
    ubuntu
    >>> ubuntu_bug.sourcepackagename is None
    True

Reporting a package bug.

    >>> params = dict(
    ...     distro="ubuntu",
    ...     package="evolution",
    ...     summary="email is cool",
    ...     comment="email is nice",
    ...     security_related=True,
    ...     subscribers=["no-priv@canonical.com"],
    ... )
    >>> bug_url = filebug_api.filebug(params)
    ObjectCreatedEvent: <Bug ...>
    >>> print(bug_url)
    http://bugs.launchpad.test/bugs/...

    >>> login("test@canonical.com")
    >>> bug = bugset.get(get_bug_id_from_url(bug_url))

    >>> print(bug.title)
    email is cool
    >>> print(bug.description)
    email is nice
    >>> bug.security_related
    True
    >>> bug.private
    True
    >>> for name in sorted(p.name for p in bug.getDirectSubscribers()):
    ...     print(name)
    ...
    name12
    no-priv
    >>> bug.getIndirectSubscribers()
    []

    >>> evolution_bug = bug.bugtasks[0]

    >>> print(evolution_bug.distribution.name)
    ubuntu
    >>> print(evolution_bug.sourcepackagename.name)
    evolution


Error Handling
--------------

Malone's xmlrpc interface provides extensive error handling. The various
error conditions it recognizes are:

Failing to specify a product or distribution.

    >>> params = dict()
    >>> filebug_api.filebug(params)
    Traceback (most recent call last):
    ...
    xmlrpc.client.Fault: <Fault 60: 'Required arguments missing. You must
    specify either a product or distribution in which the bug exists.'>

Specifying *both* a product and distribution.

    >>> params = dict(product="firefox", distro="ubuntu")
    >>> filebug_api.filebug(params)
    Traceback (most recent call last):
    ...
    xmlrpc.client.Fault: <Fault 70: 'Too many arguments. You may specify
    either a product or a distribution, but not both.'>

Specifying a non-existent product.

    >>> params = dict(product="nosuchproduct")
    >>> filebug_api.filebug(params)
    Traceback (most recent call last):
    ...
    xmlrpc.client.Fault: <Fault 10: 'No such project: nosuchproduct'>

Specifying a non-existent distribution.

    >>> params = dict(distro="nosuchdistro")
    >>> filebug_api.filebug(params)
    Traceback (most recent call last):
    ...
    xmlrpc.client.Fault: <Fault 80: 'No such distribution: nosuchdistro'>

Specifying a non-existent package.

    >>> params = dict(distro="ubuntu", package="nosuchpackage")
    >>> filebug_api.filebug(params)
    Traceback (most recent call last):
    ...
    xmlrpc.client.Fault: <Fault 90: 'No such package: nosuchpackage'>

Missing summary.

    >>> params = dict(product="firefox")
    >>> filebug_api.filebug(params)
    Traceback (most recent call last):
    ...
    xmlrpc.client.Fault: <Fault 100: 'Required parameter missing: summary'>

Missing comment.

    >>> params = dict(product="firefox", summary="the summary")
    >>> filebug_api.filebug(params)
    Traceback (most recent call last):
    ...
    xmlrpc.client.Fault: <Fault 100: 'Required parameter missing: comment'>

Invalid subscriber.

    >>> params = dict(
    ...     product="firefox",
    ...     summary="summary",
    ...     comment="comment",
    ...     subscribers=["foo.bar@canonical.com", "nosuch@subscriber.com"],
    ... )
    >>> filebug_api.filebug(params)
    Traceback (most recent call last):
    ...
    xmlrpc.client.Fault: <Fault 20: 'Invalid subscriber: No user with the
    email address "nosuch@subscriber.com" was found'>

    >>> on_created_listener.cleanUp()


Generating bugtracker authentication tokens
-------------------------------------------

Launchpad Bugs also provides an XML-RPC API for generating login tokens
for authentication with external bug trackers.

    >>> from zope.component import getUtility
    >>> from lp.xmlrpc.interfaces import IPrivateApplication
    >>> from lp.bugs.interfaces.malone import IPrivateMaloneApplication
    >>> from lp.testing import verifyObject

    >>> private_root = getUtility(IPrivateApplication)
    >>> verifyObject(IPrivateMaloneApplication, private_root.bugs)
    True

The API provides a single method, newBugTrackerToken(), which returns
the ID of the new LoginToken.

    >>> from lp.services.verification.interfaces.logintoken import (
    ...     ILoginTokenSet,
    ... )
    >>> from lp.services.webapp.servers import LaunchpadTestRequest
    >>> from lp.bugs.interfaces.externalbugtracker import (
    ...     IExternalBugTrackerTokenAPI,
    ... )
    >>> from lp.bugs.xmlrpc.bug import ExternalBugTrackerTokenAPI

    >>> bugtracker_token_api = ExternalBugTrackerTokenAPI(
    ...     private_root.bugs, LaunchpadTestRequest()
    ... )

    >>> verifyObject(IExternalBugTrackerTokenAPI, bugtracker_token_api)
    True

    >>> token_string = bugtracker_token_api.newBugTrackerToken()
    >>> token = getUtility(ILoginTokenSet)[token_string]
    >>> token
    <LoginToken object>

The LoginToken generated will be of the LoginTokenType BUGTRACKER.

    >>> print(token.tokentype.title)
    Launchpad is authenticating itself with a remote bug tracker.

These requests are all handled by the private xml-rpc server.

    >>> bugtracker_api = xmlrpc.client.ServerProxy(
    ...     "http://xmlrpc-private.launchpad.test:8087/bugs",
    ...     transport=XMLRPCTestTransport(),
    ... )

    >>> token_string = bugtracker_api.newBugTrackerToken()
    >>> token = getUtility(ILoginTokenSet)[token_string]
    >>> token
    <LoginToken object>

    >>> print(token.tokentype.title)
    Launchpad is authenticating itself with a remote bug tracker.
