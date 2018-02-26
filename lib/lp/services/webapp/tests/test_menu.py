# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from lazr.restful.utils import get_current_browser_request
from zope.security.management import newInteraction

from lp.services.webapp.menu import (
    Link,
    MENU_ANNOTATION_KEY,
    MenuBase,
    )
from lp.testing import (
    ANONYMOUS,
    login,
    logout,
    TestCase,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestMenu(MenuBase):
    links = ['test_link']
    times_called = 0

    def test_link(self):
        self.times_called += 1
        return Link('+test', 'Test', summary='Summary')


class TestMenuBaseLinkCaching(TestCase):
    """Link objects generated by MenuBase subclasses are cached.

    They are cached in the request as their state can't change during the
    lifetime of a request, but we cache them because some of them are
    expensive to generate and there are plenty of pages where we use
    "context/menu:bugs/foo" in TAL more than once, which causes the whole list
    of Links for the Bugs facet to be re-generated every time.
    """
    layer = DatabaseFunctionalLayer

    def tearDown(self):
        logout()
        super(TestMenuBaseLinkCaching, self).tearDown()

    def test_no_cache_when_there_is_no_request(self):
        # Calling login() would cause a new interaction to be setup with a
        # LaunchpadTestRequest, so we need to call newInteraction() manually
        # here.
        newInteraction()
        menu = TestMenu(object())
        menu._get_link('test_link')
        self.assertEqual(menu.times_called, 1)
        menu._get_link('test_link')
        self.assertEqual(menu.times_called, 2)

    def test_cache_when_there_is_a_request(self):
        login(ANONYMOUS)
        menu = TestMenu(object())
        menu._get_link('test_link')
        self.assertEqual(menu.times_called, 1)
        menu._get_link('test_link')
        self.assertEqual(menu.times_called, 1)

    def test_correct_value_is_cached(self):
        login(ANONYMOUS)
        menu = TestMenu(object())
        link = menu._get_link('test_link')
        request = get_current_browser_request()
        cache = request.annotations.get(MENU_ANNOTATION_KEY)
        self.assertEqual([link], cache.values())

    def test_cache_key_is_unique(self):
        # The cache key must include the link name, the context of the link
        # and the class where the link is defined.
        login(ANONYMOUS)
        context = object()
        menu = TestMenu(context)
        menu._get_link('test_link')
        cache = get_current_browser_request().annotations.get(
            MENU_ANNOTATION_KEY)
        self.assertEqual(len(cache.keys()), 1)
        self.assertContentEqual(
            cache.keys()[0], (menu.__class__, context, 'test_link'))
