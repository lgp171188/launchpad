The LaunchBag is a collection of all the 'stuff' we have traversed. It
contains the request's 'context' or environment, which can be used to
filter or otherwise specialize views or behaviour.

First, we'll set up various imports and stub objects.

    >>> from zope.component import getUtility
    >>> from lp.services.webapp.interfaces import ILaunchBag
    >>> from lp.services.webapp.interfaces import BasicAuthLoggedInEvent
    >>> from lp.services.webapp.interfaces import LoggedOutEvent
    >>> from lp.services.webapp.interfaces import (
    ...     CookieAuthPrincipalIdentifiedEvent,
    ... )

    >>> class Principal:
    ...     id = 23
    ...

    >>> principal = Principal()
    >>> class Participation:
    ...     principal = principal
    ...     interaction = None
    ...

    >>> class Response:
    ...     def getCookie(self, name):
    ...         return None
    ...

    >>> class Request:
    ...     principal = principal
    ...     response = Response()
    ...     cookies = {}
    ...
    ...     def setPrincipal(self, principal):
    ...         pass
    ...

    >>> request = Request()

There have been no logins, so launchbag.login will be None.

    >>> launchbag = getUtility(ILaunchBag)
    >>> print(launchbag.login)
    None

Let's send a basic auth login event.

    >>> login = "foo.bar@canonical.com"
    >>> event = BasicAuthLoggedInEvent(request, login, principal)
    >>> from zope.event import notify
    >>> notify(event)

Now, launchbag.login will be 'foo.bar@canonical.com'.

    >>> print(launchbag.login)
    foo.bar@canonical.com

Login should be set back to None on a logout.

    >>> event = LoggedOutEvent(request)
    >>> notify(event)
    >>> print(launchbag.login)
    None

'user' will also be set to None:

    >>> print(launchbag.user)
    None

Let's do a cookie auth principal identification.  In this case, the login
will be cookie@example.com.

    >>> event = CookieAuthPrincipalIdentifiedEvent(
    ...     principal, request, "cookie@example.com"
    ... )
    >>> notify(event)
    >>> print(launchbag.login)
    cookie@example.com


time_zone_name and time_zone
----------------------------

The time_zone_name attribute gives the name of the user's time zone; the
time_zone attribute gives it as a tzinfo object.

    >>> from lp.testing.factory import LaunchpadObjectFactory
    >>> factory = LaunchpadObjectFactory()
    >>> person = factory.makePerson()
    >>> ignored = login_person(person)
    >>> launchbag.time_zone_name
    'UTC'
    >>> launchbag.time_zone
    datetime.timezone.utc

They're cached, so even if the user's time zone is changed, they will stay
the same. This is to optimize the look-up time, since some pages look them
up a lot of times.

    >>> person.setLocation(
    ...     launchbag.user.latitude,
    ...     launchbag.user.longitude,
    ...     "Europe/Paris",
    ...     launchbag.user,
    ... )
    >>> launchbag.time_zone_name
    'UTC'
    >>> launchbag.time_zone
    datetime.timezone.utc

After the LaunchBag has been cleared, the correct time zone is returned.

    >>> launchbag.clear()
    >>> launchbag.time_zone_name
    'Europe/Paris'
    >>> launchbag.time_zone
    <... 'Europe/Paris' ...>
