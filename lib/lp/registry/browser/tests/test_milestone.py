# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test milestone views."""

__metaclass__ = type

import unittest

from zope.component import getUtility

from canonical.testing.layers import DatabaseFunctionalLayer
from lp.bugs.interfaces.bugtask import IBugTaskSet
from lp.testing import ANONYMOUS, login_person, login, TestCaseWithFactory
from lp.testing.views import create_initialized_view
from lp.testing.memcache import MemcacheTestCase


class TestMilestoneMemcache(MemcacheTestCase):

    def setUp(self):
        super(TestMilestoneMemcache, self).setUp()
        product = self.factory.makeProduct()
        login_person(product.owner)
        series = self.factory.makeProductSeries(product=product)
        self.milestone = self.factory.makeMilestone(
            productseries=series, name="1.1")
        bugtask = self.factory.makeBugTask(target=product)
        bugtask.transitionToAssignee(product.owner)
        bugtask.milestone = self.milestone
        self.observer = self.factory.makePerson()

    def test_milestone_index_memcache_anonymous(self):
        # Miss the cache on first render.
        login(ANONYMOUS)
        view = create_initialized_view(
            self.milestone, name='+index', principal=None)
        content = view.render()
        self.assertCacheMiss('<dt>Assigned to you:</dt>', content)
        self.assertCacheMiss('id="milestone_bugtasks"', content)
        # Hit the cache on the second render.
        view = create_initialized_view(
            self.milestone, name='+index', principal=None)
        self.assertTrue(view.milestone.active)
        self.assertEqual(10, view.expire_cache_minutes)
        content = view.render()
        self.assertCacheHit(
            '<dt>Assigned to you:</dt>',
            'anonymous, view/expire_cache_minutes minute', content)
        self.assertCacheHit(
            'id="milestone_bugtasks"',
            'anonymous, view/expire_cache_minutes minute', content)

    def test_milestone_index_memcache_no_cache_logged_in(self):
        login_person(self.observer)
        # Miss the cache on first render.
        view = create_initialized_view(
            self.milestone, name='+index', principal=self.observer)
        content = view.render()
        self.assertCacheMiss('<dt>Assigned to you:</dt>', content)
        self.assertCacheMiss('id="milestone_bugtasks"', content)
        # Miss the cache again on the second render.
        view = create_initialized_view(
            self.milestone, name='+index', principal=self.observer)
        self.assertTrue(view.milestone.active)
        self.assertEqual(10, view.expire_cache_minutes)
        content = view.render()
        self.assertCacheMiss('<dt>Assigned to you:</dt>', content)
        self.assertCacheMiss('id="milestone_bugtasks"', content)

    def test_milestone_index_active_cache_time(self):
        # Verify the active milestone cache time.
        view = create_initialized_view(self.milestone, name='+index')
        self.assertTrue(view.milestone.active)
        self.assertEqual(10, view.expire_cache_minutes)

    def test_milestone_index_inactive_cache_time(self):
        # Verify the inactive milestone cache time.
        self.milestone.active = False
        view = create_initialized_view(self.milestone, name='+index')
        self.assertFalse(view.milestone.active)
        self.assertEqual(360, view.expire_cache_minutes)


class TestMilestoneDeleteView(TestCaseWithFactory):
    """Test the delete rules applied by the Milestone Delete view."""

    layer = DatabaseFunctionalLayer

    def test_delete_conjoined_bugtask(self):
        product = self.factory.makeProduct()
        bug = self.factory.makeBug(product=product)
        master_bugtask = getUtility(IBugTaskSet).createTask(
            bug, productseries=product.development_focus, owner=product.owner)
        milestone = self.factory.makeMilestone(
            productseries=product.development_focus)
        login_person(product.owner)
        master_bugtask.transitionToMilestone(milestone, product.owner)
        form = {
            'field.actions.delete': 'Delete Milestone',
            }
        view = create_initialized_view(milestone, '+delete', form=form)
        self.assertEqual([], view.errors)
        self.assertEqual(0, len(product.all_milestones))
        self.assertEqual(0, product.development_focus.all_bugtasks.count())


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
