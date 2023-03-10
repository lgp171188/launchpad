OAuth pages
===========

The pages used in our implementation of the OAuth protocol.

+authorize-token
----------------

This is the page where a user reviews (approving or declining) a
consumer's request to access Launchpad on their behalf.

    # Define some things we're going to use throughout this test.
    >>> from zope.component import getMultiAdapter
    >>> from lp.services.oauth.interfaces import (
    ...     IOAuthConsumerSet,
    ...     OAuthPermission,
    ... )
    >>> from lp.services.webapp.interfaces import ILaunchpadRoot
    >>> from lp.services.webapp.servers import LaunchpadTestRequest

    >>> consumer = getUtility(IOAuthConsumerSet).getByKey("launchpad-library")
    >>> root = getUtility(ILaunchpadRoot)
    >>> def get_view_with_fresh_token(form):
    ...     token, _ = consumer.newRequestToken()
    ...     form.update({"oauth_token": token.key})
    ...     request = LaunchpadTestRequest(form=form)
    ...     login("salgado@ubuntu.com", request)
    ...     view = getMultiAdapter((root, request), name="+authorize-token")
    ...     view.initialize()
    ...     return view, token
    ...

    >>> from lp.services.beautifulsoup import (
    ...     BeautifulSoup,
    ...     SoupStrainer,
    ... )
    >>> def print_hidden_fields(html):
    ...     soup = BeautifulSoup(
    ...         html, parse_only=SoupStrainer(attrs={"type": "hidden"})
    ...     )
    ...     for tag in soup.find_all(attrs={"type": "hidden"}):
    ...         if tag["value"]:
    ...             print(tag["name"], tag["value"])
    ...

When the client doesn't specify a duration, the resulting request
token will have no expiration date set.

    >>> from datetime import datetime, timezone
    >>> view, token = get_view_with_fresh_token({})
    >>> view.reviewToken(OAuthPermission.READ_PRIVATE, None)
    >>> print(token.date_expires)
    None

When the client specifies a duration, the resulting request
token will have an appropriate expiration date set.

    >>> from lp.services.oauth.browser import TemporaryIntegrations
    >>> view, token = get_view_with_fresh_token({})
    >>> view.reviewToken(
    ...     OAuthPermission.READ_PRIVATE, TemporaryIntegrations.HOUR
    ... )
    >>> token.date_expires > datetime.now(timezone.utc)
    True

When the consumer doesn't specify a context, the token will not have a
context either.

    >>> view, token = get_view_with_fresh_token({})
    >>> print(view.token_context)
    None

    # Note that the token is stored in a hidden field in the HTML so that
    # it's submitted together with the user's chosen permission.
    >>> print_hidden_fields(view())
    loggingout...
    oauth_token...

    >>> view.reviewToken(OAuthPermission.READ_PRIVATE, None)
    >>> print(token.person.name)
    salgado
    >>> print(token.context)
    None
    >>> token.permission
    <DBItem OAuthPermission.READ_PRIVATE...
    >>> print(token.is_reviewed)
    True

The context can be a product, and if it's specified it will be carried
over to the token once it's reviewed.

    >>> view, token = get_view_with_fresh_token({"lp.context": "firefox"})
    >>> print(view.token_context.name)
    firefox

    # The context is also stored in a hidden field in the HTML so that
    # it's submitted together with the user's chosen permission.
    >>> print_hidden_fields(view())
    loggingout...
    oauth_token...
    lp.context firefox

    >>> view.reviewToken(OAuthPermission.READ_PUBLIC, None)
    >>> print(token.context.name)
    firefox

Likewise for a project.

    >>> view, token = get_view_with_fresh_token({"lp.context": "mozilla"})
    >>> print(view.token_context.name)
    mozilla

    # The context is also stored in a hidden field in the HTML so that
    # it's submitted together with the user's chosen permission.
    >>> print_hidden_fields(view())
    loggingout...
    oauth_token...
    lp.context mozilla

    >>> view.reviewToken(OAuthPermission.READ_PUBLIC, None)
    >>> print(token.context.name)
    mozilla

And a distribution.

    >>> view, token = get_view_with_fresh_token({"lp.context": "ubuntu"})
    >>> print(view.token_context.name)
    ubuntu

    # The context is also stored in a hidden field in the HTML so that
    # it's submitted together with the user's chosen permission.
    >>> print_hidden_fields(view())
    loggingout...
    oauth_token...
    lp.context ubuntu

    >>> view.reviewToken(OAuthPermission.READ_PUBLIC, None)
    >>> print(token.context.name)
    ubuntu

If the consumer wants to access only things related to a distribution's
package, it must specify the distribution and the package's name.

    >>> view, token = get_view_with_fresh_token(
    ...     {"lp.context": "ubuntu/evolution"}
    ... )
    >>> print(view.token_context.title)
    evolution package in Ubuntu

    # The context is also stored in a hidden field in the HTML so that
    # it's submitted together with the user's chosen permission.
    >>> print_hidden_fields(view())
    loggingout...
    oauth_token...
    lp.context ubuntu/evolution

    >>> view.reviewToken(OAuthPermission.READ_PUBLIC, None)
    >>> print(token.context.title)
    evolution package in Ubuntu

An error is raised if the context is not found.

    >>> view, token = get_view_with_fresh_token({"lp.context": "fooooo"})
    Traceback (most recent call last):
    ...
    lp.app.errors.UnexpectedFormData: ...

Or if the user gives us a package in a non-existing distribution.

    >>> view, token = get_view_with_fresh_token(
    ...     {"lp.context": "firefox/evolution"}
    ... )
    Traceback (most recent call last):
    ...
    lp.app.errors.UnexpectedFormData: ...
