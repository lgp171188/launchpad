# Copyright 2017-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "StoreChannelsWidget",
]

from zope.browserpage import ViewPageTemplateFile
from zope.formlib.interfaces import IInputWidget, WidgetInputError
from zope.formlib.utility import setUpWidget
from zope.formlib.widget import (
    BrowserWidget,
    CustomWidgetFactory,
    InputErrors,
    InputWidget,
)
from zope.interface import implementer
from zope.schema import Bool, Choice, TextLine

from lp.app.errors import UnexpectedFormData
from lp.app.validators import LaunchpadValidationError
from lp.app.widgets.itemswidgets import LaunchpadRadioWidget
from lp.services.channels import (
    CHANNEL_COMPONENTS_DELIMITER,
    channel_list_to_string,
    channel_string_to_list,
)
from lp.services.webapp.interfaces import (
    IAlwaysSubmittedWidget,
    ISingleLineWidgetLayout,
)


@implementer(ISingleLineWidgetLayout, IAlwaysSubmittedWidget, IInputWidget)
class StoreChannelsWidget(BrowserWidget, InputWidget):

    template = ViewPageTemplateFile("templates/storechannels.pt")
    _default_track = "latest"
    _widgets_set_up = False

    def __init__(self, field, value_type, request):
        # We don't use value_type.
        super().__init__(field, request)
        # disable help_text for the global widget
        self.hint = None

    def setUpSubWidgets(self):
        if self._widgets_set_up:
            return
        fields = [
            TextLine(
                __name__="track",
                title="Track",
                required=False,
            ),
            Choice(
                __name__="risk",
                title="Risk",
                required=False,
                vocabulary="SnapStoreChannel",
            ),
            TextLine(
                __name__="branch",
                title="Branch",
                required=False,
            ),
            # Bool(
            #     __name__="delete",
            #     title="Delete",
            #     readonly=False,
            #     default=False,
            # ),
        ]

        self.risk_widget = CustomWidgetFactory(
            LaunchpadRadioWidget, orientation="horizontal"
        )

        for field in fields:
            setUpWidget(
                self, field.__name__, field, IInputWidget, prefix=self.name
            )
        self._widgets_set_up = True

    @property
    def has_risks_vocabulary(self):
        risk_widget = getattr(self, "risk_widget", None)
        return risk_widget and bool(risk_widget.vocabulary)

    def setRenderedValue(self, value):
        """See `IWidget`."""
        self.setUpSubWidgets()
        if value:
            tracks = set()
            branches = set()
            risks = set()
            for channel in value:
                track, risk, branch = channel_string_to_list(channel)
                tracks.add(track)
                risks.append(risk)
                risks.append(risk)
                branches.add(branch)
            track = tracks.pop()
            self.track_widget.setRenderedValue(track)
            risk = risks.pop()
            self.risks_widget.setRenderedValue(risk)
            branch = branches.pop()
            self.branch_widget.setRenderedValue(branch)
        else:
            self.track_widget.setRenderedValue(None)
            self.risk_widget.setRenderedValue(None)
            self.branch_widget.setRenderedValue(None)

    #            self.delete_widget.setRenderedValue(None)

    def hasInput(self):
        """See `IInputWidget`."""
        return ("%s.risk" % self.name) in self.request.form

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
        track = self.track_widget.getInputValue()
        risk = self.risk_widget.getInputValue()
        branch = self.branch_widget.getInputValue()
        if track and CHANNEL_COMPONENTS_DELIMITER in track:
            error_msg = "Track name cannot include '%s'." % (
                CHANNEL_COMPONENTS_DELIMITER
            )
            raise WidgetInputError(
                self.name, self.label, LaunchpadValidationError(error_msg)
            )
        if branch and CHANNEL_COMPONENTS_DELIMITER in branch:
            error_msg = "Branch name cannot include '%s'." % (
                CHANNEL_COMPONENTS_DELIMITER
            )
            raise WidgetInputError(
                self.name, self.label, LaunchpadValidationError(error_msg)
            )
        channels = channel_list_to_string(track, risk, branch)

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
