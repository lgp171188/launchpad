# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import re

from zope.browserpage import ViewPageTemplateFile
from zope.formlib.textwidgets import TextAreaWidget, TextWidget

from lp.app.errors import UnexpectedFormData


class StrippedTextWidget(TextWidget):
    """A widget that strips leading and trailing whitespaces."""

    def _toFieldValue(self, input):
        return TextWidget._toFieldValue(self, input.strip())


class LowerCaseTextWidget(StrippedTextWidget):
    """A widget that converts text to lower case."""

    cssClass = "lowerCaseText"

    def _toFieldValue(self, input):
        return StrippedTextWidget._toFieldValue(self, input.lower())


class TokensTextWidget(StrippedTextWidget):
    """A widget that normalises the space between words.

    Punctuation is removed, and extra whitespace is stripped.
    """

    def _toFieldValue(self, input):
        """See `SimpleInputWidget`.

        Accept only alphanumeric characters and '-'.  Everything
        else is replaced with a single space.
        """
        normalised_text = re.sub(r"[^\w-]+", " ", input)
        return super()._toFieldValue(normalised_text)


class NoneableTextWidget(StrippedTextWidget):
    """A widget that that is None if it's value is empty or whitespace."""

    def _toFieldValue(self, input):
        value = super()._toFieldValue(input)
        if value == "":
            return None
        else:
            return value


class URIWidget(StrippedTextWidget):
    """A widget that represents a URI."""

    displayWidth = 44
    cssClass = "urlTextType"

    def __init__(self, field, request):
        super().__init__(field, request)
        self.field = field

    def _toFieldValue(self, input):
        if isinstance(input, list):
            raise UnexpectedFormData("Only a single value is expected")
        return super()._toFieldValue(input)


class URIComponentWidget(LowerCaseTextWidget):
    """A text input widget that looks like a URL path component entry."""

    template = ViewPageTemplateFile("templates/uri-component.pt")
    read_only = False

    def __call__(self):
        return self.template()

    @property
    def base_url(self):
        raise NotImplementedError()

    @property
    def current_name(self):
        return self._getFormValue().lower()

    @property
    def widget_type(self):
        if self.read_only:
            return "hidden"
        else:
            return "text"


class DelimitedListWidget(TextAreaWidget):
    """A widget that represents a list as whitespace-delimited text.

    The delimiting methods can be easily overridden to work with
    comma, semi-colon, or other delimiters.
    """

    def __init__(self, field, value_type, request):
        # We don't use value_type.
        super().__init__(field, request)

    # The default splitting function, which splits on
    # white-space. Subclasses can override this if different
    # delimiting rules are needed.
    split = staticmethod(str.split)

    # The default joining function, which simply separates each list
    # item with a newline. Subclasses can override this if different
    # delimiters are needed.
    join = staticmethod("\n".join)

    def _toFormValue(self, value):
        """Converts a list to a newline separated string.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__="foo", title="Foo")
          >>> widget = DelimitedListWidget(field, None, TestRequest())

        The 'missing' value is converted to an empty string:

          >>> print(widget._toFormValue(field.missing_value))
          <BLANKLINE>

        By default, lists are displayed one item on a line:

          >>> names = ["fred", "bob", "harry"]
          >>> widget._toFormValue(names)
          'fred\\r\\nbob\\r\\nharry'
        """
        if value == self.context.missing_value:
            value = self._missing
        elif value is None:
            value = self._missing
        else:
            value = self.join(value)
        return super()._toFormValue(value)

    def _toFieldValue(self, value):
        """Convert the input string into a list.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__="foo", title="Foo")
          >>> widget = DelimitedListWidget(field, None, TestRequest())

        The widget converts an empty string to the missing value:

          >>> widget._toFieldValue("") == field.missing_value
          True

        By default, lists are split by whitespace:

          >>> for item in widget._toFieldValue("fred\\nbob harry"):
          ...     print("'%s'" % item)
          ...
          'fred'
          'bob'
          'harry'
        """
        value = super()._toFieldValue(value)
        if value == self.context.missing_value:
            return value
        else:
            return self.split(value)


class TitleWidget(StrippedTextWidget):
    """A launchpad title widget; a little wider than a normal Textline."""

    displayWidth = 44


class SummaryWidget(TextAreaWidget):
    """A widget to capture a summary."""

    width = 44
    height = 3


class DescriptionWidget(TextAreaWidget):
    """A widget to capture a description."""

    width = 44
    height = 15


class NoneableDescriptionWidget(DescriptionWidget):
    """A widget that is None if it's value is empty or whitespace.."""

    def _toFieldValue(self, input):
        value = super()._toFieldValue(input.strip())
        if value == "":
            return None
        else:
            return value


class WhiteboardWidget(TextAreaWidget):
    """A widget to capture a whiteboard."""

    width = 44
    height = 5
