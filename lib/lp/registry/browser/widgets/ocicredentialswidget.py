# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser widget for handling a single `IOCICredentials`."""

__all__ = [
    "OCICredentialsWidget",
]

from zope.browserpage import ViewPageTemplateFile
from zope.component import getUtility
from zope.formlib.interfaces import IInputWidget, WidgetInputError
from zope.formlib.utility import setUpWidget
from zope.formlib.widget import BrowserWidget, InputErrors, InputWidget
from zope.interface import implementer
from zope.schema import Bool, Password, TextLine

from lp.app.errors import UnexpectedFormData
from lp.app.validators import LaunchpadValidationError
from lp.app.validators.url import validate_url
from lp.oci.interfaces.ociregistrycredentials import (
    IOCIRegistryCredentials,
    IOCIRegistryCredentialsSet,
)
from lp.registry.interfaces.distribution import IDistribution
from lp.services.webapp.interfaces import ISingleLineWidgetLayout


@implementer(ISingleLineWidgetLayout, IInputWidget)
class OCICredentialsWidget(BrowserWidget, InputWidget):
    template = ViewPageTemplateFile("templates/ocicredentialswidget.pt")
    _widgets_set_up = False

    def setUpSubWidgets(self):
        if self._widgets_set_up:
            return
        fields = [
            TextLine(
                __name__="url",
                title="Registry URL",
                description=("URL for the OCI registry to upload images to."),
                required=False,
            ),
            TextLine(
                __name__="region",
                title="Region",
                description="Region for the OCI Registry.",
                required=False,
            ),
            TextLine(
                __name__="username",
                title="Username",
                description="Username for the OCI Registry.",
                required=False,
            ),
            Password(
                __name__="password",
                title="Password",
                description="Password for the OCI Registry.",
                required=False,
            ),
            Password(
                __name__="confirm_password",
                title="Confirm password",
                required=False,
            ),
            Bool(
                __name__="delete",
                title="Delete",
                description="Delete these credentials.",
                required=False,
            ),
        ]
        for field in fields:
            setUpWidget(
                self, field.__name__, field, IInputWidget, prefix=self.name
            )
        self._widgets_set_up = True

    def hasInput(self):
        """See `IInputWidget`."""
        field_names = [
            "{}.url".format(self.name),
            "{}.region".format(self.name),
            "{}.username".format(self.name),
            "{}.password".format(self.name),
            "{}.confirm_password".format(self.name),
            "{}.delete".format(self.name),
        ]
        return any(self.request.form.get(x) for x in field_names)

    def hasValidInput(self):
        """See `IInputWidget`."""
        try:
            self.getInputValue()
            return True
        except InputErrors:
            return False
        except UnexpectedFormData:
            return False

    def error(self):
        """See `IBrowserWidget`."""
        try:
            if self.hasInput():
                self.getInputValue()
        except InputErrors as error:
            self._error = error
        return super().error()

    def setRenderedValue(self, value):
        """See `IInputWidget`."""
        self.setUpSubWidgets()
        if value is None:
            return
        self.url_widget.setRenderedValue(value.url)
        self.region_widget.setRenderedValue(value.region)
        self.username_widget.setRenderedValue(value.username)

    def getInputValue(self):
        """See `IInputWidget`."""
        self.setUpSubWidgets()
        # if we're deleting credentials, we don't need to validate
        if self.delete_widget.getInputValue():
            return None
        url = self.url_widget.getInputValue()
        if not url:
            raise WidgetInputError(
                self.name,
                self.label,
                LaunchpadValidationError("A URL is required."),
            )
        valid_url = validate_url(
            url, IOCIRegistryCredentials["url"].allowed_schemes
        )
        if not valid_url:
            raise WidgetInputError(
                self.name,
                self.label,
                LaunchpadValidationError("The entered URL is not valid."),
            )
        username = self.username_widget.getInputValue()
        region = self.region_widget.getInputValue()
        password = self.password_widget.getInputValue()
        confirm_password = self.confirm_password_widget.getInputValue()
        if password != confirm_password:
            raise WidgetInputError(
                self.name,
                self.label,
                LaunchpadValidationError("Passwords must match."),
            )
        credentials_set = getUtility(IOCIRegistryCredentialsSet)
        person = getattr(
            self.request.principal, "person", self.request.principal
        )

        # Distribution context allows the distro admin to create
        # credentials assigned to the oci_project_admin
        in_distribution = IDistribution.providedBy(self.context.context)
        if not in_distribution:
            raise AssertionError(
                "Attempting to set OCI registry "
                "credentials outside of a Distribution."
            )
        admin = self.context.context.oci_project_admin
        if in_distribution and not admin:
            raise WidgetInputError(
                self.name,
                self.label,
                LaunchpadValidationError(
                    "There is no OCI Project Admin for this distribution."
                ),
            )
        credentials = credentials_set.getOrCreate(
            person,
            admin,
            url,
            {"username": username, "password": password, "region": region},
            override_owner=in_distribution,
        )
        return credentials

    def __call__(self):
        """See `IBrowserWidget`."""
        self.setUpSubWidgets()
        return self.template()
