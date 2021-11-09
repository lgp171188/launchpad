# Copyright 2018-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import re

from zope.formlib.interfaces import IBrowserWidget, IInputWidget

from lp.app.widgets.snapbuildchannels import SnapBuildChannelsWidget
from lp.services.beautifulsoup import BeautifulSoup
from lp.services.fields import SnapBuildChannelsField
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import TestCaseWithFactory, verifyObject
from lp.testing.layers import DatabaseFunctionalLayer


class TestSnapBuildChannelsWidget(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        field = SnapBuildChannelsField(
            __name__="auto_build_channels",
            title="Source snap channels for automatic builds",
            extra_snap_names=["snapcraft"],
        )
        self.context = self.factory.makeSnap()
        self.field = field.bind(self.context)
        self.request = LaunchpadTestRequest()
        self.widget = SnapBuildChannelsWidget(self.field, self.request)

    def test_implements(self):
        self.assertTrue(verifyObject(IBrowserWidget, self.widget))
        self.assertTrue(verifyObject(IInputWidget, self.widget))

    def test_template(self):
        self.assertTrue(
            self.widget.template.filename.endswith("snapbuildchannels.pt"),
            "Template was not set up.",
        )

    def test_setUpSubWidgets_first_call(self):
        # The subwidgets are set up and a flag is set.
        self.widget.setUpSubWidgets()
        self.assertTrue(self.widget._widgets_set_up)
        self.assertIsNotNone(getattr(self.widget, "core_widget", None))
        self.assertIsNotNone(getattr(self.widget, "core18_widget", None))
        self.assertIsNotNone(getattr(self.widget, "core20_widget", None))
        self.assertIsNotNone(getattr(self.widget, "core22_widget", None))
        self.assertIsNotNone(getattr(self.widget, "snapcraft_widget", None))

    def test_setUpSubWidgets_second_call(self):
        # The setUpSubWidgets method exits early if a flag is set to
        # indicate that the widgets were set up.
        self.widget._widgets_set_up = True
        self.widget.setUpSubWidgets()
        self.assertIsNone(getattr(self.widget, "core_widget", None))
        self.assertIsNone(getattr(self.widget, "core18_widget", None))
        self.assertIsNone(getattr(self.widget, "core20_widget", None))
        self.assertIsNone(getattr(self.widget, "core22_widget", None))
        self.assertIsNone(getattr(self.widget, "snapcraft_widget", None))

    def test_setRenderedValue_None(self):
        self.widget.setRenderedValue(None)
        self.assertIsNone(self.widget.core_widget._getCurrentValue())
        self.assertIsNone(self.widget.core18_widget._getCurrentValue())
        self.assertIsNone(self.widget.core20_widget._getCurrentValue())
        self.assertIsNone(self.widget.core22_widget._getCurrentValue())
        self.assertIsNone(self.widget.snapcraft_widget._getCurrentValue())

    def test_setRenderedValue_empty(self):
        self.widget.setRenderedValue({})
        self.assertIsNone(self.widget.core_widget._getCurrentValue())
        self.assertIsNone(self.widget.core18_widget._getCurrentValue())
        self.assertIsNone(self.widget.core20_widget._getCurrentValue())
        self.assertIsNone(self.widget.core22_widget._getCurrentValue())
        self.assertIsNone(self.widget.snapcraft_widget._getCurrentValue())

    def test_setRenderedValue_one_channel(self):
        self.widget.setRenderedValue({"snapcraft": "stable"})
        self.assertIsNone(self.widget.core_widget._getCurrentValue())
        self.assertIsNone(self.widget.core18_widget._getCurrentValue())
        self.assertIsNone(self.widget.core20_widget._getCurrentValue())
        self.assertIsNone(self.widget.core20_widget._getCurrentValue())
        self.assertIsNone(self.widget.core22_widget._getCurrentValue())
        self.assertEqual(
            "stable", self.widget.snapcraft_widget._getCurrentValue()
        )

    def test_setRenderedValue_all_channels(self):
        self.widget.setRenderedValue(
            {
                "core": "candidate",
                "core18": "beta",
                "core20": "edge",
                "core22": "edge/feature",
                "snapcraft": "stable",
            }
        )
        self.assertEqual(
            "candidate", self.widget.core_widget._getCurrentValue()
        )
        self.assertEqual("beta", self.widget.core18_widget._getCurrentValue())
        self.assertEqual("edge", self.widget.core20_widget._getCurrentValue())
        self.assertEqual(
            "edge/feature", self.widget.core22_widget._getCurrentValue()
        )
        self.assertEqual(
            "stable", self.widget.snapcraft_widget._getCurrentValue()
        )

    def test_hasInput_false(self):
        # hasInput is false when there are no channels in the form data.
        self.widget.request = LaunchpadTestRequest(form={})
        self.assertFalse(self.widget.hasInput())

    def test_hasInput_true(self):
        # hasInput is true when there are channels in the form data.
        self.widget.request = LaunchpadTestRequest(
            form={"field.auto_build_channels.snapcraft": "stable"}
        )
        self.assertTrue(self.widget.hasInput())

    def test_hasValidInput_true(self):
        # The field input is valid when all submitted channels are valid.
        # (At the moment, individual channel names are not validated, so
        # there is no "false" counterpart to this test.)
        form = {
            "field.auto_build_channels.core": "",
            "field.auto_build_channels.core18": "beta",
            "field.auto_build_channels.core20": "edge",
            "field.auto_build_channels.core22": "edge/feature",
            "field.auto_build_channels.snapcraft": "stable",
        }
        self.widget.request = LaunchpadTestRequest(form=form)
        self.assertTrue(self.widget.hasValidInput())

    def test_getInputValue(self):
        form = {
            "field.auto_build_channels.core": "",
            "field.auto_build_channels.core18": "beta",
            "field.auto_build_channels.core20": "edge",
            "field.auto_build_channels.core22": "edge/feature",
            "field.auto_build_channels.snapcraft": "stable",
        }
        self.widget.request = LaunchpadTestRequest(form=form)
        self.assertEqual(
            {
                "core18": "beta",
                "core20": "edge",
                "core22": "edge/feature",
                "snapcraft": "stable",
            },
            self.widget.getInputValue(),
        )

    def test_call(self):
        # The __call__ method sets up the widgets.
        markup = self.widget()
        self.assertIsNotNone(self.widget.core_widget)
        self.assertIsNotNone(self.widget.core18_widget)
        self.assertIsNotNone(self.widget.core20_widget)
        self.assertIsNotNone(self.widget.core22_widget)
        self.assertIsNotNone(self.widget.snapcraft_widget)
        soup = BeautifulSoup(markup)
        fields = soup.find_all(["input"], {"id": re.compile(".*")})
        expected_ids = [
            "field.auto_build_channels.core",
            "field.auto_build_channels.core18",
            "field.auto_build_channels.core20",
            "field.auto_build_channels.core22",
            "field.auto_build_channels.snapcraft",
        ]
        ids = [field["id"] for field in fields]
        self.assertContentEqual(expected_ids, ids)
