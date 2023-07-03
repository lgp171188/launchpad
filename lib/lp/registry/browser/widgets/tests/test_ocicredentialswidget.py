# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCICredentialsWidget"""

from lazr.restful.fields import Reference
from zope.formlib.interfaces import (
    IBrowserWidget,
    IInputWidget,
    WidgetInputError,
)
from zope.interface import Interface
from zope.schema import ValidationError

from lp.app.validators import LaunchpadValidationError
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.registry.browser.widgets.ocicredentialswidget import (
    OCICredentialsWidget,
)
from lp.services.webapp.escaping import html_escape
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import TestCaseWithFactory, person_logged_in, verifyObject
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCICredentialsWidget(OCIConfigHelperMixin, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.setConfig()
        field = Reference(
            __name__="oci_registry_credentials",
            schema=Interface,
            title="OCI Registry Credentials",
        )
        self.context = self.factory.makeDistribution()
        field = field.bind(self.context)
        request = LaunchpadTestRequest()
        self.widget = OCICredentialsWidget(field, request)
        self.owner = self.factory.makePerson()
        self.credentials = self.factory.makeOCIRegistryCredentials(
            registrant=self.owner, owner=self.owner
        )

    def test_implements(self):
        self.assertTrue(verifyObject(IBrowserWidget, self.widget))
        self.assertTrue(verifyObject(IInputWidget, self.widget))

    def test_template(self):
        self.assertTrue(
            self.widget.template.filename.endswith("ocicredentialswidget.pt"),
            "Template was not set up.",
        )

    def test_setUpSubWidgets_first_call(self):
        # The subwidgets are set up and a flag is set.
        self.widget.setUpSubWidgets()
        self.assertTrue(self.widget._widgets_set_up)
        self.assertIsNotNone(self.widget.url_widget)

    def test_setUpSubWidgets_second_call(self):
        # The setUpSubWidgets method exits early if a flag is set to
        # indicate that the widgets were set up.
        self.widget._widgets_set_up = True
        self.widget.setUpSubWidgets()
        self.assertIsNone(getattr(self.widget, "url_widget", None))

    def test_setRenderedValue(self):
        self.widget.setUpSubWidgets()
        with person_logged_in(self.owner):
            self.widget.setRenderedValue(self.credentials)
            self.assertEqual(
                self.credentials.url, self.widget.url_widget._getCurrentValue()
            )
            self.assertEqual(
                self.credentials.region,
                self.widget.region_widget._getCurrentValue(),
            )
            self.assertEqual(
                self.credentials.username,
                self.widget.username_widget._getCurrentValue(),
            )
            # Password should never be rendered
            self.assertIsNone(self.widget.password_widget._getCurrentValue())

    def test_hasInput_false(self):
        # hasInput is false when the widget's name is not in the form data.
        self.widget.request = LaunchpadTestRequest(form={})
        self.assertFalse(self.widget.hasInput())

    def test_hasInput_true(self):
        # hasInput is true when the subwidgets are in the form data.
        form = {
            "field.oci_registry_credentials.url": "http://launchpad.test",
            "field.oci_registry_credentials.region": "",
            "field.oci_registry_credentials.username": "",
            "field.oci_registry_credentials.password": "",
            "field.oci_registry_credentials.confirm_password": "",
            "field.oci_registry_credentials.delete": "",
        }
        self.widget.request = LaunchpadTestRequest(form=form)
        self.assertEqual("field.oci_registry_credentials", self.widget.name)
        self.assertTrue(self.widget.hasInput())

    def assertGetInputValueError(self, form, message):
        self.widget.request = LaunchpadTestRequest(form=form)
        e = self.assertRaises(WidgetInputError, self.widget.getInputValue)
        self.assertEqual(LaunchpadValidationError(message), e.errors)
        self.assertEqual(html_escape(message), self.widget.error())

    def assertValidationError(self, form, message):
        self.widget.request = LaunchpadTestRequest(form=form)
        e = self.assertRaises(WidgetInputError, self.widget.getInputValue)
        self.assertIsInstance(e.errors, ValidationError)
        self.assertEqual(html_escape(message), self.widget.error())

    def test_getInputValue_url_missing(self):
        form = {
            "field.oci_registry_credentials.url": "",
            "field.oci_registry_credentials.region": "",
            "field.oci_registry_credentials.username": "test",
            "field.oci_registry_credentials.password": "",
            "field.oci_registry_credentials.confirm_password": "",
            "field.oci_registry_credentials.delete": "",
        }
        self.assertGetInputValueError(form, "A URL is required.")

    def test_getInputValue_url_invalid(self):
        form = {
            "field.oci_registry_credentials.url": "not-a-valid-url",
            "field.oci_registry_credentials.region": "",
            "field.oci_registry_credentials.username": "test",
            "field.oci_registry_credentials.password": "",
            "field.oci_registry_credentials.confirm_password": "",
            "field.oci_registry_credentials.delete": "",
        }
        self.assertGetInputValueError(form, "The entered URL is not valid.")

    def test_getInputValue_password_mismatch(self):
        form = {
            "field.oci_registry_credentials.url": "http://launchpad.test",
            "field.oci_registry_credentials.region": "",
            "field.oci_registry_credentials.username": "test",
            "field.oci_registry_credentials.password": "test",
            "field.oci_registry_credentials.confirm_password": "nottest",
            "field.oci_registry_credentials.delete": "",
        }
        self.assertGetInputValueError(form, "Passwords must match.")

    def test_getInputValue_no_oci_project_admin(self):
        form = {
            "field.oci_registry_credentials.url": "http://launchpad.test",
            "field.oci_registry_credentials.region": "",
            "field.oci_registry_credentials.username": "test",
            "field.oci_registry_credentials.password": "test",
            "field.oci_registry_credentials.confirm_password": "test",
            "field.oci_registry_credentials.delete": "",
        }
        self.assertGetInputValueError(
            form, "There is no OCI Project Admin for this distribution."
        )

    def test_getInputValue_valid(self):
        field = Reference(
            __name__="oci_registry_credentials",
            schema=Interface,
            title="OCI Registry Credentials",
        )
        self.context = self.factory.makeDistribution(
            oci_project_admin=self.owner
        )
        field = field.bind(self.context)
        request = LaunchpadTestRequest()
        self.widget = OCICredentialsWidget(field, request)
        url = "http://launchpad.test"
        form = {
            "field.oci_registry_credentials.url": url,
            "field.oci_registry_credentials.region": "",
            "field.oci_registry_credentials.username": "test",
            "field.oci_registry_credentials.password": "test",
            "field.oci_registry_credentials.confirm_password": "test",
            "field.oci_registry_credentials.delete": "",
        }
        self.widget.request = LaunchpadTestRequest(form=form)
        created_credentials = self.widget.getInputValue()
        with person_logged_in(self.owner):
            self.assertEqual(created_credentials.url, url)
