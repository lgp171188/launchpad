# Copyright 2018-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A widget for selecting source snap channels for builds."""

__all__ = [
    "SnapBuildChannelsWidget",
]

from zope.browserpage import ViewPageTemplateFile
from zope.formlib.interfaces import IInputWidget
from zope.formlib.utility import setUpWidget
from zope.formlib.widget import BrowserWidget, InputErrors, InputWidget
from zope.interface import implementer
from zope.schema import TextLine
from zope.security.proxy import isinstance as zope_isinstance

from lp.app.errors import UnexpectedFormData
from lp.services.webapp.interfaces import (
    IAlwaysSubmittedWidget,
    ISingleLineWidgetLayout,
)


@implementer(ISingleLineWidgetLayout, IAlwaysSubmittedWidget, IInputWidget)
class SnapBuildChannelsWidget(BrowserWidget, InputWidget):

    template = ViewPageTemplateFile("templates/snapbuildchannels.pt")
    hint = False
    _widgets_set_up = False

    @property
    def snap_names(self):
        return sorted(term.value for term in self.context.key_type.vocabulary)

    def setUpSubWidgets(self):
        if self._widgets_set_up:
            return
        fields = [
            TextLine(
                __name__=snap_name,
                title="%s channel" % snap_name,
                required=False,
            )
            for snap_name in self.snap_names
        ]
        for field in fields:
            setUpWidget(
                self, field.__name__, field, IInputWidget, prefix=self.name
            )
        self.widgets = {
            snap_name: getattr(self, "%s_widget" % snap_name)
            for snap_name in self.snap_names
        }
        self._widgets_set_up = True

    def setRenderedValue(self, value):
        """See `IWidget`."""
        self.setUpSubWidgets()
        if not zope_isinstance(value, dict):
            value = {}
        for snap_name in self.snap_names:
            self.widgets[snap_name].setRenderedValue(value.get(snap_name))

    def hasInput(self):
        """See `IInputWidget`."""
        return any(
            "%s.%s" % (self.name, snap_name) in self.request.form
            for snap_name in self.snap_names
        )

    def hasValidInput(self):
        """See `IInputWidget`."""
        try:
            self.getInputValue()
            return True
        except InputErrors:
            return False
        except UnexpectedFormData:
            return False

    def getInputValue(self):
        """See `IInputWidget`."""
        self.setUpSubWidgets()
        channels = {}
        for snap_name in self.snap_names:
            channel = self.widgets[snap_name].getInputValue()
            if channel:
                channels[snap_name] = channel
        return channels

    def error(self):
        """See `IBrowserWidget`."""
        try:
            if self.hasInput():
                self.getInputValue()
        except InputErrors as error:
            self._error = error
        return super().error()

    def __call__(self):
        """See `IBrowserWidget`."""
        self.setUpSubWidgets()
        return self.template()
