# Copyright 2018-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A widget for selecting source snap channels for builds."""

__all__ = [
    'SnapBuildChannelsWidget',
    ]

from zope.browserpage import ViewPageTemplateFile
from zope.formlib.interfaces import IInputWidget
from zope.formlib.utility import setUpWidget
from zope.formlib.widget import (
    BrowserWidget,
    InputErrors,
    InputWidget,
    )
from zope.interface import implementer
from zope.schema import TextLine
from zope.security.proxy import isinstance as zope_isinstance

from lp.app.errors import UnexpectedFormData
from lp.services.features import getFeatureFlag
from lp.services.webapp.interfaces import (
    IAlwaysSubmittedWidget,
    ISingleLineWidgetLayout,
    )
from lp.snappy.interfaces.snap import SNAP_SNAPCRAFT_CHANNEL_FEATURE_FLAG


@implementer(ISingleLineWidgetLayout, IAlwaysSubmittedWidget, IInputWidget)
class SnapBuildChannelsWidget(BrowserWidget, InputWidget):

    template = ViewPageTemplateFile("templates/snapbuildchannels.pt")
    hint = False
    snap_names = ["core", "core18", "core20", "core22", "snapcraft"]
    _widgets_set_up = False

    def __init__(self, context, request):
        super().__init__(context, request)
        self.hint = (
            'The channels to use for build tools when building the snap '
            'package.\n')
        default_snapcraft_channel = (
            getFeatureFlag(SNAP_SNAPCRAFT_CHANNEL_FEATURE_FLAG) or "apt")
        if default_snapcraft_channel == "apt":
            self.hint += (
                'If unset, or if the channel for snapcraft is set to "apt", '
                'the default is to install snapcraft from the source archive '
                'using apt.')
        else:
            self.hint += (
                'If unset, the default is to install snapcraft from the "%s" '
                'channel.  Setting the channel for snapcraft to "apt" causes '
                'snapcraft to be installed from the source archive using '
                'apt.' % default_snapcraft_channel)

    def setUpSubWidgets(self):
        if self._widgets_set_up:
            return
        fields = [
            TextLine(
                __name__=snap_name, title="%s channel" % snap_name,
                required=False)
            for snap_name in self.snap_names
            ]
        for field in fields:
            setUpWidget(
                self, field.__name__, field, IInputWidget, prefix=self.name)
        self._widgets_set_up = True

    def setRenderedValue(self, value):
        """See `IWidget`."""
        self.setUpSubWidgets()
        if not zope_isinstance(value, dict):
            value = {}
        for snap_name in self.snap_names:
            getattr(self, "%s_widget" % snap_name).setRenderedValue(
                value.get(snap_name))

    def hasInput(self):
        """See `IInputWidget`."""
        return any(
            "%s.%s" % (self.name, snap_name) in self.request.form
            for snap_name in self.snap_names)

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
            widget = getattr(self, snap_name + "_widget")
            channel = widget.getInputValue()
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
