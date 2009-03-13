__all__ = ['Cookbook',
           'CookbookServiceRootResource',
           'CookbookSet',
           'CookbookWebServiceObject',
           'CookbookServiceRootAbsoluteURL']

from zope.interface import implements
from zope.traversing.browser.interfaces import IAbsoluteURL
from zope.component import adapts, getUtility
from zope.publisher.interfaces.browser import IDefaultBrowserLayer

from canonical.lazr.rest import ServiceRootResource
from canonical.lazr.interfaces.rest import IServiceRootResource
from canonical.lazr.rest.example.interfaces import (
    ICookbook, ICookbookSet, IHasGet)


class CookbookWebServiceObject:
    pass


class CookbookTopLevelResource(CookbookWebServiceObject):

    @property
    def __parent__(self):
        return getUtility(IServiceRootResource)

    @property
    def __name__(self):
        raise NotImplementedError()


class Cookbook(CookbookWebServiceObject):
    implements(ICookbook, IAbsoluteURL)
    def __init__(self, name):
        self.name = name

    @property
    def __name__(self):
        return self.name


# Define some globally accessible sample data.
C1 = Cookbook(u"Mastering the Art of French Cooking")
C2 = Cookbook(u"The Joy of Cooking")
C3 = Cookbook(u"James Beard's American Cookery")
COOKBOOKS = [C1, C2, C3]


class CookbookSet(CookbookTopLevelResource):
    implements(ICookbookSet)

    def __init__(self, cookbooks=None):
        if cookbooks is None:
            cookbooks = COOKBOOKS
        self.cookbooks = list(cookbooks)

    def getCookbooks(self):
        return self.cookbooks

    def get(self, name):
        match = [c for c in self.cookbooks if c.name == name]
        if len(match) > 0:
            return match[0]
        return None

    __name__ = "cookbooks"


class CookbookServiceRootResource(ServiceRootResource):
    implements(IHasGet)
    _top_level_names = None
    @property
    def top_level_names(self):
        if self._top_level_names is None:
            self._top_level_names = {
                'cookbooks': getUtility(ICookbookSet)
                }
        return self._top_level_names

    def get(self, name):
        obj = self.top_level_names.get(name)
        obj.__parent__ = self
        return obj


class CookbookServiceRootAbsoluteURL:
    """A basic, extensible implementation of IAbsoluteURL."""
    implements(IAbsoluteURL)
    adapts(CookbookServiceRootResource, IDefaultBrowserLayer)


    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __str__(self):
        return "http://api.cookbooks.dev/beta"

    __call__ = __str__
