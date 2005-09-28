# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""Publisher of objects as web pages.

XXX: Much stuff from canonical.publication needs to move here.
"""

__metaclass__ = type
__all__ = ['UserAttributeCache', 'LaunchpadView', 'canonical_url', 'nearest',
           'get_current_browser_request', 'canonical_url_iterator',
           'rootObject']

from zope.interface import implements
from zope.component import getUtility
import zope.security.management
from zope.security.checker import ProxyFactory, NamesChecker
from zope.publisher.interfaces.http import IHTTPApplicationRequest
from canonical.launchpad.interfaces import (
    ICanonicalUrlData, NoCanonicalUrl, ILaunchpadRoot, ILaunchpadApplication,
    ILaunchBag)

# Import the launchpad.conf configuration object.
from canonical.config import config


class UserAttributeCache:
    """Mix in to provide self.user, cached."""

    _no_user = object()
    _user = _no_user

    @property
    def user(self):
        """The logged-in Person, or None if there is no one logged in."""
        if self._user is self._no_user:
            self._user = getUtility(ILaunchBag).user
        return self._user


class LaunchpadView(UserAttributeCache):
    """Base class for views in Launchpad.

    Available attributes and methods are:

    - context
    - request
    - initialize() <-- subclass this for specific initialization
    - template     <-- the template set from zcml, otherwise not present
    - user         <-- currently logged-in user
    - render()     <-- used to render the page.  override this if you have many
                       templates not set via zcml, or you want to do rendering
                       from Python.
    """

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def initialize(self):
        """Override this in subclasses."""
        pass

    @property
    def template(self):
        """The page's template, if configured in zcml."""
        return self.index

    def render(self):
        return self.template()

    def __call__(self):
        self.initialize()
        return self.render()


class LaunchpadRootUrlData:
    """ICanonicalUrlData for the ILaunchpadRoot object."""

    implements(ICanonicalUrlData)

    path = ''
    inside = None

    def __init__(self, context):
        self.context = context

def canonical_urldata_iterator(obj):
    """Iterate over the urldata for the object and each of its canonical url
    parents.

    Raises NoCanonicalUrl if canonical url data is not available.
    """
    current_object = obj
    # The while loop is to proceed the first time around because we're
    # on the initial object, and subsequent times, because there is an object
    # inside.
    while current_object is obj or urldata.inside is not None:
        urldata = ICanonicalUrlData(current_object, None)
        if urldata is None:
            raise NoCanonicalUrl(obj, current_object)
        yield urldata
        current_object = urldata.inside

def canonical_url_iterator(obj):
    """Iterate over the object and each of its canonical url parents.

    Raises NoCanonicalUrl if a canonical url is not available.
    """
    yield obj
    for urldata in canonical_urldata_iterator(obj):
        if urldata.inside is not None:
            yield urldata.inside

def canonical_url(obj, request=None):
    """Return the canonical URL string for the object.

    If the request is provided, then protocol, host and port are taken
    from the request.

    If a request is not provided, but a web-request is in progress,
    the protocol, host and port are taken from the current request.

    Otherwise, the protocol, host and port are taken from the root_url given in
    launchpad.conf.

    Raises NoCanonicalUrl if a canonical url is not available.
    """
    urlparts = [urldata.path
                for urldata in canonical_urldata_iterator(obj)
                if urldata.path]

    if request is None:
        # Look for a request from the interaction.  If there is none, fall
        # back to the root_url from the config file.
        current_request = get_current_browser_request()
        if current_request is not None:
            request = current_request

    if request is None:
        root_url = config.launchpad.root_url
    else:
        root_url = request.getApplicationURL() + '/'
    return root_url + '/'.join(reversed(urlparts))

def get_current_browser_request():
    """Return the current browser request, looked up from the interaction.

    If there is no suitable request, then return None.

    Returns only requests that provide IHTTPApplicationRequest.
    """
    interaction = zope.security.management.queryInteraction()
    requests = [
        participation
        for participation in interaction.participations
        if IHTTPApplicationRequest.providedBy(participation)
        ]
    if not requests:
        return None
    assert len(requests) == 1, (
        "We expect only one IHTTPApplicationRequest in the interaction."
        " Got %s." % len(requests))
    return requests[0]

def nearest(obj, *interfaces):
    """Return the nearest object up the canonical url chain that provides
    one of the interfaces given.

    The object returned might be the object given as an argument, if that
    object provides one of the given interfaces.

    Return None is no suitable object is found.
    """
    for current_obj in canonical_url_iterator(obj):
        for interface in interfaces:
            if interface.providedBy(current_obj):
                return current_obj
    return None


class RootObject:
    implements(ILaunchpadApplication, ILaunchpadRoot)

rootObject = ProxyFactory(RootObject(), NamesChecker(["__class__"]))
