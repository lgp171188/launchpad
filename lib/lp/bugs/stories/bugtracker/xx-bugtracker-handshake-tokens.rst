Handling BugTracker handshake tokens
====================================

Launchpad can generate LoginTokens which can then be used to
authenticate it with remote bug trackers. Generating these tokens is
done using the internal XML-RPC service.

    >>> import xmlrpc.client
    >>> from lp.testing.xmlrpc import XMLRPCTestTransport
    >>> bugtracker_api = xmlrpc.client.ServerProxy(
    ...     "http://xmlrpc-private.launchpad.test:8087/bugs",
    ...     transport=XMLRPCTestTransport(),
    ... )

    >>> token_string = bugtracker_api.newBugTrackerToken()

Browsing to the token's +bugtracker-handshake URL will result in an
error if we attempt it as a GET request.

    >>> token_url = (
    ...     "http://launchpad.test/token/%s/+bugtracker-handshake"
    ...     % token_string
    ... )

    >>> anon_browser.open(token_url)
    Traceback (most recent call last):
      ...
    urllib.error.HTTPError: HTTP Error 405: Method Not Allowed
