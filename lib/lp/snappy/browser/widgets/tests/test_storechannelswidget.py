# Copyright 2017-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import re

from zope.formlib.interfaces import (
    IBrowserWidget,
    IInputWidget,
    WidgetInputError,
)
from zope.schema import List

from lp.app.validators import LaunchpadValidationError
from lp.registry.enums import StoreRisk
from lp.services.beautifulsoup import BeautifulSoup
from lp.services.webapp.escaping import html_escape
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.snappy.browser.widgets.storechannels import StoreChannelsWidget
from lp.testing import TestCaseWithFactory, verifyObject
from lp.testing.layers import DatabaseFunctionalLayer


class TestStoreChannelsWidget(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        field = List(__name__="channels", title="Store channels")
        self.new_snap = self.factory.makeSnap(store_channels=[])
        field = field.bind(self.new_snap)
        request = LaunchpadTestRequest()
        self.new_widget = StoreChannelsWidget(field, None, request)

        self.edit_snap = self.factory.makeSnap(
            store_channels=["track1/stable/branch1", "track2/edge/branch1"]
        )
        field = field.bind(self.edit_snap)
        self.edit_widget = StoreChannelsWidget(field, None, request)

    def test_implements(self):
        self.assertTrue(verifyObject(IBrowserWidget, self.new_widget))
        self.assertTrue(verifyObject(IInputWidget, self.new_widget))

    def test_template(self):
        self.assertTrue(
            self.new_widget.template.filename.endswith("storechannels.pt"),
            "Template was not set up.",
        )

    def test_setUpSubWidgets_first_call(self):
        # The subwidgets are set up and a flag is set.
        self.new_widget.setUpSubWidgets()
        self.assertTrue(self.new_widget._widgets_set_up)
        self.assertIsNotNone(
            getattr(self.new_widget, "add_track_widget", None)
        )
        self.assertIsNotNone(
            getattr(self.new_widget, "add_branch_widget", None)
        )

    def test_setUpSubWidgets_second_call(self):
        # The setUpSubWidgets method exits early if a flag is set to
        # indicate that the widgets were set up.
        self.new_widget._widgets_set_up = True
        self.new_widget.setUpSubWidgets()
        self.assertIsNone(getattr(self.new_widget, "add_track_widget", None))
        self.assertIsNone(getattr(self.new_widget, "add_risk_widget", None))
        self.assertIsNone(getattr(self.new_widget, "add_branch_widget", None))

    def test_setRenderedValue_empty(self):
        self.new_widget.setRenderedValue([])
        self.assertIsNone(self.new_widget.add_track_widget._getCurrentValue())
        self.assertIsNone(self.new_widget.add_risk_widget._getCurrentValue())

    def test_setRenderedValue_no_track_or_branch(self):
        # Channel does not include a track or branch
        channels = ["/edge/"]
        self.edit_widget.setRenderedValue(channels)
        self.assertIsNone(self.edit_widget.add_track_widget._getCurrentValue())
        self.assertEqual(
            StoreRisk.EDGE, self.edit_widget.add_risk_widget._getCurrentValue()
        )
        self.assertIsNone(
            self.edit_widget.add_branch_widget._getCurrentValue()
        )

    def test_setRenderedValue_with_track(self):
        # Channels including a track
        channels = ["2.2/candidate", "2.2/edge"]
        self.edit_widget.setRenderedValue(channels)
        self.assertEqual(
            "2.2", self.edit_widget.track_0_widget._getCurrentValue()
        )
        self.assertEqual(
            "candidate", self.edit_widget.risk_0_widget._getCurrentValue()
        )
        self.assertIsNone(self.edit_widget.branch_0_widget._getCurrentValue())

        self.assertEqual(
            "2.2", self.edit_widget.track_1_widget._getCurrentValue()
        )
        self.assertEqual(
            "edge", self.edit_widget.risk_1_widget._getCurrentValue()
        )
        self.assertIsNone(self.edit_widget.branch_1_widget._getCurrentValue())

    def test_setRenderedValue_with_branch(self):
        # Channels including a branch
        channels = ["candidate/fix-123", "edge/fix-123"]
        self.edit_widget.setRenderedValue(channels)
        self.assertIsNone(self.edit_widget.track_0_widget._getCurrentValue())
        self.assertEqual(
            "candidate", self.edit_widget.risk_0_widget._getCurrentValue()
        )
        self.assertEqual(
            "fix-123", self.edit_widget.branch_0_widget._getCurrentValue()
        )

        self.assertIsNone(self.edit_widget.track_1_widget._getCurrentValue())
        self.assertEqual(
            "edge", self.edit_widget.risk_1_widget._getCurrentValue()
        )
        self.assertEqual(
            "fix-123", self.edit_widget.branch_1_widget._getCurrentValue()
        )

    def test_setRenderedValue_with_track_and_branch(self):
        # Channels including a track and branch
        channels = ["2.2/candidate/fix-123", "2.2/edge/fix-123"]
        self.edit_widget.setRenderedValue(channels)
        self.assertEqual(
            "2.2", self.edit_widget.track_0_widget._getCurrentValue()
        )
        self.assertEqual(
            "candidate", self.edit_widget.risk_0_widget._getCurrentValue()
        )
        self.assertEqual(
            "fix-123", self.edit_widget.branch_0_widget._getCurrentValue()
        )
        self.assertEqual(
            "2.2", self.edit_widget.track_1_widget._getCurrentValue()
        )
        self.assertEqual(
            "edge", self.edit_widget.risk_1_widget._getCurrentValue()
        )
        self.assertEqual(
            "fix-123", self.edit_widget.branch_1_widget._getCurrentValue()
        )

    def test_setRenderedValue_invalid_value(self):
        # We allow multiple channels, different tracks or branches.
        # We don't raise ValueError exceptions on these.
        self.edit_widget.setRenderedValue(["2.2/candidate", "2.1/edge"])
        self.edit_widget.setRenderedValue(
            ["candidate/fix-123", "edge/fix-124"]
        )
        self.edit_widget.setRenderedValue(["2.2/candidate", "edge/fix-123"])

    def test_hasInput_false(self):
        # hasInput is false when there is no risk set in the form data.
        self.new_widget.request = LaunchpadTestRequest(
            form={"field.channels.track": "track"}
        )
        self.assertFalse(self.new_widget.hasInput())

    def test_hasInput_true(self):
        # hasInput is true if there are risks set in the form data.
        self.new_widget.request = LaunchpadTestRequest(
            form={"field.channels.add_risk": ["beta"]}
        )
        self.assertTrue(self.new_widget.hasInput())

    def test_hasValidInput_false(self):
        # The field input is invalid if any of the submitted parts are
        # invalid.
        form = {
            "field.channels.add_track": "",
            "field.channels.add_risk": ["invalid"],
            "field.channels.add_branch": "",
        }
        self.new_widget.request = LaunchpadTestRequest(form=form)
        self.assertFalse(self.new_widget.hasValidInput())

    def test_hasValidInput_true(self):
        field = List(__name__="channels", title="Store channels")
        self.context = self.new_snap
        field.bind(self.context)

        # The field input is valid when all submitted parts are valid.
        form = {
            "field.channels.add_track": "track",
            "field.channels.add_risk": "stable",
            "field.channels.add_branch": "branch",
        }

        request = LaunchpadTestRequest(form=form)
        self.new_widget = StoreChannelsWidget(field, None, request)
        self.assertTrue(self.new_widget.hasValidInput())

    def assertGetInputValueError(self, form, message):
        self.new_widget.request = LaunchpadTestRequest(form=form)
        e = self.assertRaises(WidgetInputError, self.new_widget.getInputValue)
        self.assertEqual(LaunchpadValidationError(message), e.errors)
        self.assertEqual(html_escape(message), self.new_widget.error())

    def test_getInputValue_invalid_track(self):
        # An error is raised when the track includes a '/'.
        form = {
            "field.channels.add_track": "tra/ck",
            "field.channels.add_risk": "beta",
            "field.channels.add_branch": "",
        }
        self.assertGetInputValueError(form, "Track name cannot include '/'.")

    def test_getInputValue_invalid_branch(self):
        # An error is raised when the branch includes a '/'.
        form = {
            "field.channels.add_track": "",
            "field.channels.add_risk": "beta",
            "field.channels.add_branch": "bra/nch",
        }
        self.assertGetInputValueError(form, "Branch name cannot include '/'.")

    def test_getInputValue_no_track_or_branch(self):
        self.new_widget.request = LaunchpadTestRequest(
            form={
                "field.channels.add_track": "",
                "field.channels.add_risk": "edge",
                "field.channels.add_branch": "",
            }
        )
        expected = ["edge"]
        self.assertEqual(expected, self.new_widget.getInputValue())

    def test_getInputValue_with_track(self):
        self.new_widget.request = LaunchpadTestRequest(
            form={
                "field.channels.add_track": "track",
                "field.channels.add_risk": "beta",
                "field.channels.add_branch": "",
            }
        )
        expected = ["track/beta"]
        self.assertEqual(expected, self.new_widget.getInputValue())

    def test_getInputValue_with_branch(self):
        self.new_widget.request = LaunchpadTestRequest(
            form={
                "field.channels.add_track": "",
                "field.channels.add_risk": "beta",
                "field.channels.add_branch": "fix-123",
            }
        )
        expected = ["beta/fix-123"]
        self.assertEqual(expected, self.new_widget.getInputValue())

    def test_getInputValue_with_track_and_branch(self):
        self.new_widget.request = LaunchpadTestRequest(
            form={
                "field.channels.add_track": "track",
                "field.channels.add_risk": "beta",
                "field.channels.add_branch": "fix-123",
            }
        )
        expected = ["track/beta/fix-123"]
        self.assertEqual(expected, self.new_widget.getInputValue())

    def test_call(self):
        # The __call__ method sets up the widgets.
        markup = self.new_widget()
        self.assertIsNotNone(self.new_widget.add_track_widget)
        self.assertIsNotNone(self.new_widget.add_risk_widget)
        self.assertIsNotNone(self.new_widget.add_branch_widget)

        soup = BeautifulSoup(markup)
        fields = soup.find_all(["input", "select"], {"id": re.compile(".*")})
        expected_ids = [
            "field.channels.add_risk",
            "field.channels.add_track",
            "field.channels.add_branch",
        ]

        ids = [field["id"] for field in fields]
        self.assertContentEqual(expected_ids, ids)
