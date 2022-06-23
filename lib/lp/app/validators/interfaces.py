#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).
from zope.formlib.interfaces import IWidgetInputError
from zope.interface import Interface


class ILaunchpadValidationError(IWidgetInputError):
    def snippet():
        """Render as an HTML error message, as per IWidgetInputErrorView"""


class ILaunchpadWidgetInputErrorView(Interface):
    def snippet():
        """Convert a widget input error to an html snippet

        If the error implements provides a snippet() method, just return it.
        Otherwise, fall back to the default Z3 mechanism
        """
