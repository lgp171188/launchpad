# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from BeautifulSoup import BeautifulSoup
from storm.zope.interfaces import IResultSet
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

import unittest

from canonical.config import config
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.testing.pages import find_tag_by_id
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.publisher import canonical_url
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    LaunchpadFunctionalLayer,
    )
from lp.registry.enum import (
    DistroSeriesDifferenceStatus,
    DistroSeriesDifferenceType,
    )
from lp.services.features.flags import FeatureController
from lp.services.features.model import (
    FeatureFlag,
    getFeatureStore,
    )
from lp.services.features import (
    getFeatureFlag,
    per_thread,
    )
from lp.testing import (
    TestCaseWithFactory,
    login_person,
    person_logged_in,
    )
from lp.registry.browser.distroseries import (
    BLACKLISTED,
    NON_BLACKLISTED,
    HIGHER_VERSION_THAN_PARENT,
    )
from lp.testing.views import create_initialized_view


class TestDistroSeriesNeedsPackagesView(TestCaseWithFactory):
    """Test the distroseries +needs-packaging view."""

    layer = LaunchpadZopelessLayer

    def test_cached_unlinked_packages(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distroseries = self.factory.makeDistroSeries(distribution=ubuntu)
        view = create_initialized_view(distroseries, '+needs-packaging')
        naked_packages = removeSecurityProxy(view.cached_unlinked_packages)
        self.assertTrue(
            IResultSet.providedBy(
                view.cached_unlinked_packages.currentBatch().list),
            '%s should batch IResultSet so that slicing will limit the '
            'query' % view.cached_unlinked_packages.currentBatch().list)


class TestDistroSeriesView(TestCaseWithFactory):
    """Test the distroseries +index view."""

    layer = LaunchpadZopelessLayer

    def test_needs_linking(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distroseries = self.factory.makeDistroSeries(distribution=ubuntu)
        view = create_initialized_view(distroseries, '+index')
        self.assertEqual(view.needs_linking, None)


def set_derived_series_ui_feature_flag(test_case):
    # Helper to set the feature flag enabling the derived series ui.
    ignore = getFeatureStore().add(FeatureFlag(
        scope=u'default', flag=u'soyuz.derived-series-ui.enabled',
        value=u'on', priority=1))

    # XXX Michael Nelson 2010-09-21 bug=631884
    # Currently LaunchpadTestRequest doesn't set per-thread
    # features.
    def in_scope(value):
        return True
    per_thread.features = FeatureController(in_scope)

    def reset_per_thread_features():
        per_thread.features = None
    test_case.addCleanup(reset_per_thread_features)


class DistroSeriesLocalPackageDiffsPageTestCase(TestCaseWithFactory):
    """Test the distroseries +localpackagediffs page."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(DistroSeriesLocalPackageDiffsPageTestCase,
              self).setUp('foo.bar@canonical.com')
        set_derived_series_ui_feature_flag(self)
        self.simple_user = self.factory.makePerson()

    def test_filter_form_if_differences(self):
        # Test that the page includes the filter form if differences
        # are present
        login_person(self.simple_user)
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        current_difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)

        view = create_initialized_view(
            derived_series, '+localpackagediffs', principal=self.simple_user)

        self.assertIsNot(
            None,
            find_tag_by_id(view(), 'distroseries-localdiff-search-filter'),
            "Form filter should be shown when there are differences.")

    def test_filter_noform_if_nodifferences(self):
        # Test that the page doesn't includes the filter form if no
        # differences are present
        login_person(self.simple_user)
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))

        view = create_initialized_view(
            derived_series, '+localpackagediffs', principal=self.simple_user)

        self.assertIs(
            None,
            find_tag_by_id(view(), 'distroseries-localdiff-search-filter'),
            "Form filter should not be shown when there are no differences.")


class DistroSeriesLocalPackageDiffsTestCase(TestCaseWithFactory):
    """Test the distroseries +localpackagediffs view."""

    layer = LaunchpadZopelessLayer

    def test_view_redirects_without_feature_flag(self):
        # If the feature flag soyuz.derived-series-ui.enabled is not set the
        # view simply redirects to the derived series.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))

        self.assertIs(
            None, getFeatureFlag('soyuz.derived-series-ui.enabled'))
        view = create_initialized_view(
            derived_series, '+localpackagediffs')

        response = view.request.response
        self.assertEqual(302, response.getStatus())
        self.assertEqual(
            canonical_url(derived_series), response.getHeader('location'))

    def test_label(self):
        # The view label includes the names of both series.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))

        view = create_initialized_view(
            derived_series, '+localpackagediffs')

        self.assertEqual(
            "Source package differences between 'Derilucid' and "
            "parent series 'Lucid'",
            view.label)

    def test_batch_includes_needing_attention_only(self):
        # The differences attribute includes differences needing
        # attention only.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        current_difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)
        old_difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.RESOLVED)

        view = create_initialized_view(
            derived_series, '+localpackagediffs')

        self.assertContentEqual(
            [current_difference], view.cached_differences.batch)

    def test_batch_includes_different_versions_only(self):
        # The view contains differences of type DIFFERENT_VERSIONS only.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        different_versions_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)
        unique_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            difference_type=(
                DistroSeriesDifferenceType.UNIQUE_TO_DERIVED_SERIES))

        view = create_initialized_view(
            derived_series, '+localpackagediffs')

        self.assertContentEqual(
            [different_versions_diff], view.cached_differences.batch)

    def test_template_includes_help_link(self):
        # The help link for popup help is included.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))

        set_derived_series_ui_feature_flag(self)
        view = create_initialized_view(
            derived_series, '+localpackagediffs')

        soup = BeautifulSoup(view())
        help_links = soup.findAll(
            'a', href='/+help/soyuz/derived-series-syncing.html')
        self.assertEqual(1, len(help_links))

    def test_diff_row_includes_last_comment_only(self):
        # The most recent comment is rendered for each difference.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)
        difference.addComment(difference.owner, "Earlier comment")
        difference.addComment(difference.owner, "Latest comment")

        set_derived_series_ui_feature_flag(self)
        view = create_initialized_view(
            derived_series, '+localpackagediffs')

        # Find all the rows within the body of the table
        # listing the differences.
        soup = BeautifulSoup(view())
        diff_table = soup.find('table', {'class': 'listing'})
        rows = diff_table.tbody.findAll('tr')

        self.assertEqual(1, len(rows))
        self.assertIn("Latest comment", unicode(rows[0]))
        self.assertNotIn("Earlier comment", unicode(rows[0]))

    def test_diff_row_links_to_extra_details(self):
        # The source package name links to the difference details.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)

        set_derived_series_ui_feature_flag(self)
        view = create_initialized_view(
            derived_series, '+localpackagediffs')
        soup = BeautifulSoup(view())
        diff_table = soup.find('table', {'class': 'listing'})
        row = diff_table.tbody.findAll('tr')[0]

        href = canonical_url(difference).replace('http://launchpad.dev', '')
        links = row.findAll('a', href=href)
        self.assertEqual(1, len(links))
        self.assertEqual(difference.source_package_name.name, links[0].string)


class DistroSeriesLocalPackageDiffsFunctionalTestCase(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def test_batch_filtered(self):
        # The name_filter parameter allows to filter packages by name.
        set_derived_series_ui_feature_flag(self)
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        diff1 = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-src-package")
        diff2 = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-second-src-package")

        filtered_view = create_initialized_view(
            derived_series,
            '+localpackagediffs',
            query_string='field.name_filter=my-src-package')
        unfiltered_view = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        self.assertContentEqual(
            [diff1], filtered_view.cached_differences.batch)
        self.assertContentEqual(
            [diff2, diff1], unfiltered_view.cached_differences.batch)

    def test_batch_unfiltered(self):
        # The default filter is all non blacklisted differences.
        set_derived_series_ui_feature_flag(self)
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        diff1 = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-src-package")
        diff2 = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            source_package_name_str="my-second-src-package")
        blacklisted_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)

        filtered_view = create_initialized_view(
            derived_series,
            '+localpackagediffs',
            query_string='field.package_type=%s' %NON_BLACKLISTED)
        filtered_view2 = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        self.assertContentEqual(
            [diff2, diff1], filtered_view.cached_differences.batch)
        self.assertContentEqual(
            [diff2, diff1], filtered_view2.cached_differences.batch)

    def test_batch_differences_packages(self):
        # field.package_type parameter allows to list only
        # blacklisted differences.
        set_derived_series_ui_feature_flag(self)
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        blacklisted_diff = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT)

        blacklisted_view = create_initialized_view(
            derived_series,
            '+localpackagediffs',
            query_string='field.package_type=%s' %BLACKLISTED)
        unblacklisted_view = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        self.assertContentEqual(
            [blacklisted_diff], blacklisted_view.cached_differences.batch)
        self.assertContentEqual(
            [], unblacklisted_view.cached_differences.batch)

    def test_batch_blacklisted_differences_with_higher_version(self):
        # field.package_type parameter allows to list only
        # blacklisted differences with a child's version higher than parent's.
        set_derived_series_ui_feature_flag(self)
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        blacklisted_diff_higher = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT,
            versions={'base': '1.1', 'parent': '1.3', 'derived': '1.10'})
        blacklisted_diff_not_higher = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series,
            status=DistroSeriesDifferenceStatus.BLACKLISTED_CURRENT,
            versions={'base': '1.1', 'parent': '1.12', 'derived': '1.10'})

        blacklisted_view = create_initialized_view(
            derived_series,
            '+localpackagediffs',
            query_string='field.package_type=%s' %HIGHER_VERSION_THAN_PARENT)
        unblacklisted_view = create_initialized_view(
            derived_series,
            '+localpackagediffs')

        self.assertContentEqual(
            [blacklisted_diff_higher],
            blacklisted_view.cached_differences.batch)
        self.assertContentEqual(
            [], unblacklisted_view.cached_differences.batch)

    def test_canPerformSync_non_editor(self):
        # Non-editors do not see options to sync.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)

        set_derived_series_ui_feature_flag(self)
        with person_logged_in(self.factory.makePerson()):
            view = create_initialized_view(
                derived_series, '+localpackagediffs')

        self.assertFalse(view.canPerformSync())

    def test_canPerformSync_editor(self):
        # Editors are presented with options to perform syncs.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        difference = self.factory.makeDistroSeriesDifference(
            derived_series=derived_series)

        set_derived_series_ui_feature_flag(self)
        with person_logged_in(derived_series.owner):
            view = create_initialized_view(
                derived_series, '+localpackagediffs')
            self.assertTrue(view.canPerformSync())

    # XXX 2010-10-29 michaeln bug=668334
    # The following three tests pass locally but there is a bug with
    # per-thread features when running with a larger subset of tests.
    # These should be re-enabled once the above bug is fixed.
    def disabled_test_sync_notification_on_success(self):
        # Syncing one or more diffs results in a stub notification.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        difference = self.factory.makeDistroSeriesDifference(
            source_package_name_str='my-src-name',
            derived_series=derived_series)

        set_derived_series_ui_feature_flag(self)
        with person_logged_in(derived_series.owner):
            view = create_initialized_view(
                derived_series, '+localpackagediffs',
                method='POST', form={
                    'field.selected_differences': [
                        difference.source_package_name.name,
                        ],
                    'field.actions.sync': 'Sync',
                    })

        self.assertEqual(0, len(view.errors))
        notifications = view.request.response.notifications
        self.assertEqual(1, len(notifications))
        self.assertEqual(
            "The following sources would have been synced if this wasn't "
            "just a stub operation: my-src-name",
            notifications[0].message)
        self.assertEqual(302, view.request.response.getStatus())

    def disabled_test_sync_error_nothing_selected(self):
        # An error is raised when a sync is requested without any selection.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        difference = self.factory.makeDistroSeriesDifference(
            source_package_name_str='my-src-name',
            derived_series=derived_series)

        set_derived_series_ui_feature_flag(self)
        with person_logged_in(derived_series.owner):
            view = create_initialized_view(
                derived_series, '+localpackagediffs',
                method='POST', form={
                    'field.selected_differences': [],
                    'field.actions.sync': 'Sync',
                    })

        self.assertEqual(1, len(view.errors))
        self.assertEqual(
            'No differences selected.', view.errors[0])

    def disabled_test_sync_error_invalid_selection(self):
        # An error is raised when an invalid difference is selected.
        derived_series = self.factory.makeDistroSeries(
            name='derilucid', parent_series=self.factory.makeDistroSeries(
                name='lucid'))
        difference = self.factory.makeDistroSeriesDifference(
            source_package_name_str='my-src-name',
            derived_series=derived_series)

        set_derived_series_ui_feature_flag(self)
        with person_logged_in(derived_series.owner):
            view = create_initialized_view(
                derived_series, '+localpackagediffs',
                method='POST', form={
                    'field.selected_differences': ['some-other-name'],
                    'field.actions.sync': 'Sync',
                    })

        self.assertEqual(2, len(view.errors))
        self.assertEqual(
            'No differences selected.', view.errors[0])
        self.assertEqual(
            'Invalid value', view.errors[1].error_name)


class TestMilestoneBatchNavigatorAttribute(TestCaseWithFactory):
    """Test the series.milestone_batch_navigator attribute."""

    layer = LaunchpadZopelessLayer

    def test_distroseries_milestone_batch_navigator(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distroseries = self.factory.makeDistroSeries(distribution=ubuntu)
        for name in ('a', 'b', 'c', 'd'):
            distroseries.newMilestone(name)
        view = create_initialized_view(distroseries, name='+index')
        self._check_milestone_batch_navigator(view)

    def test_productseries_milestone_batch_navigator(self):
        product = self.factory.makeProduct()
        for name in ('a', 'b', 'c', 'd'):
            product.development_focus.newMilestone(name)

        view = create_initialized_view(
            product.development_focus, name='+index')
        self._check_milestone_batch_navigator(view)

    def _check_milestone_batch_navigator(self, view):
        config.push('default-batch-size', """
        [launchpad]
        default_batch_size: 2
        """)
        self.assert_(
            isinstance(view.milestone_batch_navigator, BatchNavigator),
            'milestone_batch_navigator is not a BatchNavigator object: %r'
            % view.milestone_batch_navigator)
        self.assertEqual(4, view.milestone_batch_navigator.batch.total())
        expected = [
            'd',
            'c',
            ]
        milestone_names = [
            item.name
            for item in view.milestone_batch_navigator.currentBatch()]
        self.assertEqual(expected, milestone_names)
        config.pop('default-batch-size')


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
