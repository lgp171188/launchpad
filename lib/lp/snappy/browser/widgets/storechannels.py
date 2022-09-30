# Copyright 2017-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "StoreChannelsWidget",
]

from zope.browserpage import ViewPageTemplateFile
from zope.formlib.interfaces import IInputWidget, WidgetInputError
from zope.formlib.utility import setUpWidget
from zope.formlib.widget import BrowserWidget, InputErrors, InputWidget
from zope.interface import implementer
from zope.schema import Bool, Choice, TextLine

from lp.app.errors import UnexpectedFormData
from lp.app.validators import LaunchpadValidationError
from lp.charms.interfaces.charmrecipe import ICharmRecipe
from lp.registry.enums import StoreRisk
from lp.services.channels import (
    CHANNEL_COMPONENTS_DELIMITER,
    channel_list_to_string,
    channel_string_to_list,
)
from lp.services.webapp.interfaces import (
    IAlwaysSubmittedWidget,
    ISingleLineWidgetLayout,
)
from lp.snappy.interfaces.snap import ISnap


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

    def _getFieldName(self, name, channel_index):
        return "%s_%d" % (name, channel_index)

    def is_edit(self):
        if ICharmRecipe.providedBy(self.context.context) or ISnap.providedBy(
            self.context.context
        ):
            if len(self.context.context.store_channels) >= 1:
                return True

    def setUpSubWidgets(self):
        if self._widgets_set_up:
            return
        fields = []
        fields.append(
            [
                TextLine(
                    __name__="add_track",
                    title="Track",
                    required=False,
                ),
                Choice(
                    __name__="add_risk",
                    title="Risk",
                    required=False,
                    default=StoreRisk.EDGE,
                    vocabulary="SnapStoreChannel",
                ),
                TextLine(
                    __name__="add_branch",
                    title="Branch",
                    required=False,
                ),
            ]
        )
        if self.is_edit():
            for index in range(len(self.context.context.store_channels)):
                fields.append(
                    [
                        TextLine(
                            __name__=self._getFieldName("track", index),
                            required=False,
                        ),
                        Choice(
                            __name__=self._getFieldName("risk", index),
                            required=False,
                            default=StoreRisk.EDGE,
                            vocabulary="SnapStoreChannel",
                        ),
                        TextLine(
                            __name__=self._getFieldName("branch", index),
                            required=False,
                        ),
                        Bool(
                            __name__=self._getFieldName("delete", index),
                            required=False,
                            default=False,
                        ),
                    ]
                )

        for i in range(0, len(fields)):
            for j in range(0, len(fields[i])):
                setUpWidget(
                    self,
                    fields[i][j].__name__,
                    fields[i][j],
                    IInputWidget,
                    prefix=self.name,
                )

        self._widgets_set_up = True

    def setRenderedValue(self, value):
        """See `IWidget`."""
        self.setUpSubWidgets()
        if value:
            for i in range(0, len(value)):
                track, risk, branch = channel_string_to_list(value[i])
                track_widget = getattr(self, "track_%s_widget" % i)
                track_widget.setRenderedValue(track)
                track_widget.display_label = False
                risk_widget = getattr(self, "risk_%s_widget" % i)
                risk_widget.setRenderedValue(risk)
                risk_widget.display_label = False
                branch_widget = getattr(self, "branch_%s_widget" % i)
                branch_widget.setRenderedValue(branch)
                branch_widget.display_label = False
                delete_widget = getattr(self, "delete_%s_widget" % i)
                delete_widget.setRenderedValue(False)
                delete_widget.display_label = False
        else:
            self.add_track_widget.setRenderedValue(None)
            self.add_risk_widget.setRenderedValue(None)
            self.add_branch_widget.setRenderedValue(None)

    def hasInput(self):
        """See `IInputWidget`."""
        return ("%s.add_risk" % self.name) in self.request.form

    def hasValidInput(self):
        """See `IInputWidget`."""
        try:
            self.getInputValue()
            return True
        except InputErrors:
            return False
        except UnexpectedFormData:
            return False

    def get_list(self, track, risk, branch):
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
        return channel_list_to_string(track, risk, branch)

    def getInputValue(self):
        """See `IInputWidget`."""
        self.setUpSubWidgets()
        store_channels = []
        track = self.add_track_widget.getInputValue()
        risk = self.add_risk_widget.getInputValue()
        branch = self.add_branch_widget.getInputValue()
        add_row = self.get_list(track, risk, branch)
        if add_row:
            store_channels.append(add_row)

        if self.is_edit():
            for index in range(len(self.context.context.store_channels)):
                track = getattr(
                    self, "track_%s_widget" % index
                ).getInputValue()
                risk = getattr(self, "risk_%s_widget" % index).getInputValue()
                branch = getattr(
                    self, "branch_%s_widget" % index
                ).getInputValue()
                delete = getattr(
                    self, "delete_%s_widget" % index
                ).getInputValue()
                if not delete:
                    store_channels.append(self.get_list(track, risk, branch))

        return store_channels

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
