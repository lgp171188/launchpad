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
from zope.schema import Choice, List, TextLine

from lp import _
from lp.app.errors import UnexpectedFormData
from lp.app.validators import LaunchpadValidationError
from lp.app.widgets.itemswidgets import LabeledMultiCheckBoxWidget
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
                description=_(
                    "Track defines a series for your software. "
                    "If not specified, the default track ('latest') is "
                    "assumed."
                ),
            ),
            List(
                __name__="risks",
                title="Risk",
                required=False,
                value_type=Choice(vocabulary="SnapStoreChannel"),
                description=_("Risks denote the stability of your software."),
            ),
            TextLine(
                __name__="branch",
                title="Branch",
                required=False,
                description=_(
                    "Branches provide users with an easy way to test bug "
                    "fixes.  They are temporary and created on demand.  If "
                    "not specified, no branch is used."
                ),
            ),
        ]

        self.risks_widget = CustomWidgetFactory(LabeledMultiCheckBoxWidget)
        for field in fields:
            setUpWidget(
                self, field.__name__, field, IInputWidget, prefix=self.name
            )
        self.risks_widget.orientation = "horizontal"
        self._widgets_set_up = True

    @property
    def has_risks_vocabulary(self):
        risks_widget = getattr(self, "risks_widget", None)
        return risks_widget and bool(risks_widget.vocabulary)

    def setRenderedValue(self, value):
        """See `IWidget`."""
        self.setUpSubWidgets()
        if value:
            # NOTE: atm target channels must belong to the same track and
            # branch
            tracks = set()
            branches = set()
            risks = []
            for channel in value:
                track, risk, branch = channel_string_to_list(channel)
                tracks.add(track)
                risks.append(risk)
                branches.add(branch)
            if len(tracks) != 1:
                raise ValueError(
                    "Channels belong to different tracks: %r" % value
                )
            if len(branches) != 1:
                raise ValueError(
                    "Channels belong to different branches: %r" % value
                )
            track = tracks.pop()
            self.track_widget.setRenderedValue(track)
            self.risks_widget.setRenderedValue(risks)
            branch = branches.pop()
            self.branch_widget.setRenderedValue(branch)
        else:
            self.track_widget.setRenderedValue(None)
            self.risks_widget.setRenderedValue(None)
            self.branch_widget.setRenderedValue(None)

    def hasInput(self):
        """See `IInputWidget`."""
        return ("%s.risks" % self.name) in self.request.form

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
        risks = self.risks_widget.getInputValue()
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
        channels = [
            channel_list_to_string(track, risk, branch) for risk in risks
        ]
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
