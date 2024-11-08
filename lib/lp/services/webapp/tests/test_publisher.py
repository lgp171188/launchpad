# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import io
import json
from doctest import ELLIPSIS, DocTestSuite
from unittest import TestLoader, TestSuite

from lazr.restful.interfaces import IJSONRequestCache
from zope.component import getUtility
from zope.interface import implementer

from lp.app.interfaces.launchpad import IPrivacy
from lp.services.features.flags import flag_info
from lp.services.features.testing import FeatureFixture
from lp.services.webapp import publisher
from lp.services.webapp.publisher import (
    FakeRequest,
    LaunchpadView,
    RedirectionView,
)
from lp.services.webapp.servers import (
    LaunchpadTestRequest,
    WebServiceClientRequest,
)
from lp.services.worlddata.interfaces.country import ICountrySet
from lp.testing import (
    TestCase,
    TestCaseWithFactory,
    login_as,
    person_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer


class TestLaunchpadView(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        flag_info.append(
            (
                "test_feature",
                "boolean",
                "documentation",
                "default_value_1",
                "title",
                "http://wiki.lp.dev/LEP/sample",
            )
        )
        flag_info.append(
            (
                "test_feature_2",
                "boolean",
                "documentation",
                "default_value_2",
                "title",
                "http://wiki.lp.dev/LEP/sample2",
            )
        )

    def tearDown(self):
        flag_info.pop()
        flag_info.pop()
        super().tearDown()

    def test_getCacheJSON_non_resource_context(self):
        view = LaunchpadView(object(), LaunchpadTestRequest())
        self.assertEqual(
            {"related_features": {}}, json.loads(view.getCacheJSON())
        )

    @staticmethod
    def getCanada():
        return getUtility(ICountrySet)["CA"]

    def assertIsCanada(self, json_dict):
        self.assertIs(None, json_dict["description"])
        self.assertEqual("CA", json_dict["iso3166code2"])
        self.assertEqual("CAN", json_dict["iso3166code3"])
        self.assertEqual("Canada", json_dict["name"])
        self.assertIs(None, json_dict["title"])
        self.assertContentEqual(
            [
                "description",
                "http_etag",
                "iso3166code2",
                "iso3166code3",
                "name",
                "resource_type_link",
                "self_link",
                "title",
            ],
            json_dict.keys(),
        )

    def test_getCacheJSON_resource_context(self):
        view = LaunchpadView(self.getCanada(), LaunchpadTestRequest())
        json_dict = json.loads(view.getCacheJSON())["context"]
        self.assertIsCanada(json_dict)

    def test_getCacheJSON_non_resource_object(self):
        request = LaunchpadTestRequest()
        view = LaunchpadView(object(), request)
        IJSONRequestCache(request).objects["my_bool"] = True
        with person_logged_in(self.factory.makePerson()):
            self.assertEqual(
                {"related_features": {}, "my_bool": True},
                json.loads(view.getCacheJSON()),
            )

    def test_getCacheJSON_resource_object(self):
        request = LaunchpadTestRequest()
        view = LaunchpadView(object(), request)
        IJSONRequestCache(request).objects["country"] = self.getCanada()
        with person_logged_in(self.factory.makePerson()):
            json_dict = json.loads(view.getCacheJSON())["country"]
        self.assertIsCanada(json_dict)

    def test_getCacheJSON_context_overrides_objects(self):
        request = LaunchpadTestRequest()
        view = LaunchpadView(self.getCanada(), request)
        IJSONRequestCache(request).objects["context"] = True
        with person_logged_in(self.factory.makePerson()):
            json_dict = json.loads(view.getCacheJSON())["context"]
        self.assertIsCanada(json_dict)

    def test_getCache_anonymous(self):
        request = LaunchpadTestRequest()
        view = LaunchpadView(self.getCanada(), request)
        self.assertIs(None, view.user)
        IJSONRequestCache(request).objects["my_bool"] = True
        json_dict = json.loads(view.getCacheJSON())
        self.assertIsCanada(json_dict["context"])
        self.assertIn("my_bool", json_dict)

    def test_getCache_anonymous_obfuscated(self):
        request = LaunchpadTestRequest()
        branch = self.factory.makeBranch(name="user@domain")
        login_as(None)
        view = LaunchpadView(branch, request)
        self.assertIs(None, view.user)
        self.assertNotIn("user@domain", view.getCacheJSON())

    def test_getCache_redirected_view_default(self):
        # A redirection view by default provides no json cache data.
        request = LaunchpadTestRequest()
        view = RedirectionView(None, request)
        json_dict = json.loads(view.getCacheJSON())
        self.assertEqual({}, json_dict)

    def test_getCache_redirected_view(self):
        # A redirection view may be provided with a target view instance from
        # which json cache data is obtained.

        class TestView(LaunchpadView):
            pass

        request = LaunchpadTestRequest()
        test_view = TestView(self.getCanada(), request)
        view = RedirectionView(None, request, cache_view=test_view)
        IJSONRequestCache(request).objects["my_bool"] = True
        json_dict = json.loads(view.getCacheJSON())
        self.assertIsCanada(json_dict["context"])
        self.assertIn("my_bool", json_dict)

    def test_isRedirected_status_codes(self):
        request = LaunchpadTestRequest()
        view = LaunchpadView(object(), request)
        for code in view.REDIRECTED_STATUSES:
            request.response.setStatus(code)
            self.assertTrue(view._isRedirected())
        for code in [100, 200, 403, 404, 500]:
            request.response.setStatus(code)
            self.assertFalse(view._isRedirected())

    def test_call_render_with_isRedirected(self):
        class TestView(LaunchpadView):
            def render(self):
                return "rendered"

        request = LaunchpadTestRequest()
        view = TestView(object(), request)
        request.response.setStatus(200)
        self.assertEqual("rendered", view())
        request.response.setStatus(301)
        self.assertEqual("", view())

    def test_related_feature_info__default(self):
        # By default, LaunchpadView.related_feature_info is empty.
        request = LaunchpadTestRequest()
        view = LaunchpadView(object(), request)
        self.assertEqual(0, len(view.related_feature_info))

    def test_related_feature_info__with_related_feature_nothing_enabled(self):
        # If a view has a non-empty sequence of related feature flags but if
        # no matching feature rules are defined, is_beta is False.
        request = LaunchpadTestRequest()
        view = LaunchpadView(object(), request)
        view.related_features = {"test_feature": False}
        self.assertEqual(
            {
                "test_feature": {
                    "is_beta": False,
                    "title": "title",
                    "url": "http://wiki.lp.dev/LEP/sample",
                    "value": None,
                }
            },
            view.related_feature_info,
        )

    def test_related_feature_info__default_scope_only(self):
        # If a view has a non-empty sequence of related feature flags but if
        # only a default scope is defined, it is not considered beta.
        self.useFixture(
            FeatureFixture(
                {},
                (
                    {
                        "flag": "test_feature",
                        "scope": "default",
                        "priority": 0,
                        "value": "on",
                    },
                ),
            )
        )
        request = LaunchpadTestRequest()
        view = LaunchpadView(object(), request)
        view.related_features = {"test_feature": False}
        self.assertEqual(
            {
                "test_feature": {
                    "is_beta": False,
                    "title": "title",
                    "url": "http://wiki.lp.dev/LEP/sample",
                    "value": "on",
                }
            },
            view.related_feature_info,
        )

    def test_active_related_features__enabled_feature(self):
        # If a view has a non-empty sequence of related feature flags and if
        # only a non-default scope is defined and active, the property
        # active_related_features contains this feature flag.
        self.useFixture(
            FeatureFixture(
                {},
                (
                    {
                        "flag": "test_feature",
                        "scope": "pageid:foo",
                        "priority": 0,
                        "value": "on",
                    },
                ),
                override_scope_lookup=lambda scope_name: True,
            )
        )
        request = LaunchpadTestRequest()
        view = LaunchpadView(object(), request)
        view.related_features = {"test_feature": False}
        self.assertEqual(
            {
                "test_feature": {
                    "is_beta": True,
                    "title": "title",
                    "url": "http://wiki.lp.dev/LEP/sample",
                    "value": "on",
                }
            },
            view.related_feature_info,
        )

    def makeFeatureFlagDictionaries(self, default_value, scope_value):
        # Return two dictionaries describing a feature for each test feature.
        # One dictionary specifies the default value, the other specifies
        # a more restricted scope.
        def makeFeatureDict(flag, value, scope, priority):
            return {
                "flag": flag,
                "scope": scope,
                "priority": priority,
                "value": value,
            }

        return (
            makeFeatureDict("test_feature", default_value, "default", 0),
            makeFeatureDict("test_feature", scope_value, "pageid:foo", 10),
            makeFeatureDict("test_feature_2", default_value, "default", 0),
            makeFeatureDict("test_feature_2", scope_value, "pageid:bar", 10),
        )

    def test_related_features__enabled_feature_with_default(self):
        # If a view
        #   * has a non-empty sequence of related feature flags,
        #   * the default scope and a non-default scope are defined
        #     but have different values,
        # then the property related_feature_info contains this feature flag.
        self.useFixture(
            FeatureFixture(
                {},
                self.makeFeatureFlagDictionaries("", "on"),
                override_scope_lookup=lambda scope_name: True,
            )
        )
        request = LaunchpadTestRequest()
        view = LaunchpadView(object(), request)
        view.related_features = {"test_feature": False}
        self.assertEqual(
            {
                "test_feature": {
                    "is_beta": True,
                    "title": "title",
                    "url": "http://wiki.lp.dev/LEP/sample",
                    "value": "on",
                }
            },
            view.related_feature_info,
        )

    def test_related_feature_info__enabled_feature_with_default_same_value(
        self,
    ):
        # If a view
        #   * has a non-empty sequence of related feature flags,
        #   * the default scope and a non-default scope are defined
        #     and have the same values,
        # then is_beta is false.
        # Unless related_features forces it to always be beta, and the
        # flag is set.
        self.useFixture(
            FeatureFixture(
                {},
                self.makeFeatureFlagDictionaries("on", "on"),
                override_scope_lookup=lambda scope_name: True,
            )
        )
        request = LaunchpadTestRequest()
        view = LaunchpadView(object(), request)
        view.related_features = {"test_feature": False}
        self.assertEqual(
            {
                "test_feature": {
                    "is_beta": False,
                    "title": "title",
                    "url": "http://wiki.lp.dev/LEP/sample",
                    "value": "on",
                }
            },
            view.related_feature_info,
        )

        view.related_features["test_feature"] = True
        self.assertEqual(
            {
                "test_feature": {
                    "is_beta": True,
                    "title": "title",
                    "url": "http://wiki.lp.dev/LEP/sample",
                    "value": "on",
                }
            },
            view.related_feature_info,
        )

        self.useFixture(
            FeatureFixture(
                {},
                self.makeFeatureFlagDictionaries("on", ""),
                override_scope_lookup=lambda scope_name: True,
            )
        )
        self.assertEqual(
            {
                "test_feature": {
                    "is_beta": False,
                    "title": "title",
                    "url": "http://wiki.lp.dev/LEP/sample",
                    "value": "",
                }
            },
            view.related_feature_info,
        )

    def test_json_cache_has_related_features(self):
        # The property related_features is copied into the JSON cache.
        class TestView(LaunchpadView):
            related_features = {"test_feature": False}

        self.useFixture(
            FeatureFixture(
                {},
                self.makeFeatureFlagDictionaries("", "on"),
                override_scope_lookup=lambda scope_name: True,
            )
        )
        request = LaunchpadTestRequest()
        view = TestView(object(), request)
        with person_logged_in(self.factory.makePerson()):
            self.assertEqual(
                {
                    "related_features": {
                        "test_feature": {
                            "is_beta": True,
                            "title": "title",
                            "url": "http://wiki.lp.dev/LEP/sample",
                            "value": "on",
                        },
                    },
                },
                json.loads(view.getCacheJSON()),
            )

    def test_json_cache_collects_related_features_from_all_views(self):
        # A typical page includes data from more than one view,
        # for example, from macros. Related features from these sub-views
        # are included in the JSON cache.
        class TestView(LaunchpadView):
            related_features = {"test_feature": False}

        class TestView2(LaunchpadView):
            related_features = {"test_feature_2": False}

        self.useFixture(
            FeatureFixture(
                {},
                self.makeFeatureFlagDictionaries("", "on"),
                override_scope_lookup=lambda scope_name: True,
            )
        )
        request = LaunchpadTestRequest()
        view = TestView(object(), request)
        TestView2(object(), request)
        with person_logged_in(self.factory.makePerson()):
            self.assertEqual(
                {
                    "related_features": {
                        "test_feature": {
                            "is_beta": True,
                            "title": "title",
                            "url": "http://wiki.lp.dev/LEP/sample",
                            "value": "on",
                        },
                        "test_feature_2": {
                            "is_beta": True,
                            "title": "title",
                            "url": "http://wiki.lp.dev/LEP/sample2",
                            "value": "on",
                        },
                    },
                },
                json.loads(view.getCacheJSON()),
            )

    def test_view_creation_with_fake_or_none_request(self):
        # LaunchpadView.__init__() does not crash with a FakeRequest.
        LaunchpadView(object(), FakeRequest())
        # Or when no request at all is passed.
        LaunchpadView(object(), None)

    def test_view_privacy(self):
        # View privacy is based on the context.
        @implementer(IPrivacy)
        class PrivateObject:
            def __init__(self, private):
                self.private = private

        view = LaunchpadView(PrivateObject(True), FakeRequest())
        self.assertTrue(view.private)

        view = LaunchpadView(PrivateObject(False), FakeRequest())
        self.assertFalse(view.private)

    def test_view_beta_features_simple(self):
        class TestView(LaunchpadView):
            related_features = {"test_feature": False}

        self.useFixture(
            FeatureFixture(
                {},
                self.makeFeatureFlagDictionaries("", "on"),
                override_scope_lookup=lambda scope_name: True,
            )
        )
        request = LaunchpadTestRequest()
        view = TestView(object(), request)
        expected_beta_features = [
            {
                "url": "http://wiki.lp.dev/LEP/sample",
                "is_beta": True,
                "value": "on",
                "title": "title",
            }
        ]
        self.assertEqual(expected_beta_features, view.beta_features)

    def test_view_beta_features_mixed(self):
        # With multiple related features, only those in a beta condition are
        # reported as beta features.
        class TestView(LaunchpadView):
            related_features = {"test_feature": False, "test_feature2": False}

        # Select one flag on 'default', one flag not on 'default. 'default'
        # setting determines whether flags correspond to 'beta' features.
        raw_flag_dicts = self.makeFeatureFlagDictionaries("", "on")
        flag_dicts = [raw_flag_dicts[1], raw_flag_dicts[2]]

        self.useFixture(
            FeatureFixture(
                {}, flag_dicts, override_scope_lookup=lambda scope_name: True
            )
        )
        request = LaunchpadTestRequest()
        view = TestView(object(), request)
        expected_beta_features = [
            {
                "url": "http://wiki.lp.dev/LEP/sample",
                "is_beta": True,
                "value": "on",
                "title": "title",
            }
        ]
        self.assertEqual(expected_beta_features, view.beta_features)

    def test_request_form_sanitizes_html(self):
        """Test that HTML in form parameters is properly escaped."""
        request = LaunchpadTestRequest(
            form={"resize_frame": "<script>alert(1)</script>"}
        )
        LaunchpadView(object(), request)
        self.assertEqual(
            request.form["resize_frame"],
            "&lt;script&gt;alert(1)&lt;/script&gt;",
        )

    def test_request_form_preserves_safe_values(self):
        """Test that safe form values are not modified."""
        request = LaunchpadTestRequest(
            form={"resize_frame": "normal123-value.text"}
        )
        LaunchpadView(object(), request)
        self.assertEqual(request.form["resize_frame"], "normal123-value.text")

    def test_request_form_sanitizes_multiple_values(self):
        """Test that multiple form values containing HTML are escaped."""
        request = LaunchpadTestRequest(
            form={
                "field1": "<p>test</p>",
                "field2": "'); test //",
            }
        )
        LaunchpadView(object(), request)
        self.assertEqual(request.form["field1"], "&lt;p&gt;test&lt;/p&gt;")
        self.assertEqual(request.form["field2"], "&#x27;); test //")

    def test_request_form_handles_non_string_values(self):
        """Test that non-string form values are not modified."""
        request = LaunchpadTestRequest(form={"number": 123, "boolean": True})
        LaunchpadView(object(), request)
        self.assertEqual(request.form["number"], 123)
        self.assertEqual(request.form["boolean"], True)

    def test_request_form_handles_empty_values(self):
        """Test that empty or None form values are handled properly."""
        request = LaunchpadTestRequest(form={"empty": "", "none": None})
        LaunchpadView(object(), request)
        self.assertEqual(request.form["empty"], "")
        self.assertIsNone(request.form["none"])


class TestRedirectionView(TestCase):
    layer = DatabaseFunctionalLayer

    def test_redirect_to_non_launchpad_objects(self):
        request = WebServiceClientRequest(io.BytesIO(b""), {})
        view = RedirectionView("http://canonical.com", request)
        expected_msg = (
            "RedirectionView.context is only supported for URLs served by the "
            "main Launchpad application, not 'http://canonical.com'."
        )
        self.assertRaisesWithContent(
            AttributeError, expected_msg, getattr, view, "context"
        )


def test_suite():
    suite = TestSuite()
    suite.addTest(DocTestSuite(publisher, optionflags=ELLIPSIS))
    suite.addTest(TestLoader().loadTestsFromName(__name__))
    return suite
