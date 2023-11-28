# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""These widgets use the a YUI2 calendar widget to allow for
date and datetime selection.

To avoid adding the YUI2 page-weight to launchpad.js, the relevant files
need to be included on the individual pages using the widget. See
templates/archive-subscribers.pt for an example.

We should investigate zc.datewidget available from the Z3 SVN repository.
"""

__all__ = [
    "DateTimeWidget",
    "DateWidget",
    "DatetimeDisplayWidget",
]

from datetime import datetime, timezone, tzinfo
from typing import Optional

from dateutil import tz
from zope.browserpage import ViewPageTemplateFile
from zope.component import getUtility
from zope.datetime import DateTimeError, parse
from zope.formlib.interfaces import (
    ConversionError,
    InputErrors,
    WidgetInputError,
)
from zope.formlib.textwidgets import TextWidget
from zope.formlib.widget import DisplayWidget

from lp.app.validators import LaunchpadValidationError
from lp.services.compat import tzname
from lp.services.utils import round_half_up
from lp.services.webapp.escaping import html_escape
from lp.services.webapp.interfaces import ILaunchBag


class DateTimeWidget(TextWidget):
    """A date and time selection widget with popup selector.

      >>> from zope.schema import Field
      >>> from lp.services.webapp.servers import LaunchpadTestRequest
      >>> field = Field(__name__="foo", title="Foo")
      >>> widget = DateTimeWidget(field, LaunchpadTestRequest())

    The datetime popup widget shows the time zone in which it will return
    the time:

      >>> print(widget())  # doctest: +ELLIPSIS
      <BLANKLINE>
      <...in time zone: UTC...

    The datetime popup widget links to the page which allows the user to
    change their system time zone.

      >>> print(widget())  # doctest: +ELLIPSIS
      <BLANKLINE>
      <...<a href="/people/+me/+editlocation">...

    If there is a required time zone, then that overrides the user or system
    default, and the user is not invited to change the time zone:

      >>> widget.required_time_zone_name = "America/Los_Angeles"
      >>> print(widget())  # doctest: +ELLIPSIS
      <BLANKLINE>
      <...in time zone: America/Los_Angeles...
      >>> "change time zone" not in widget()
      True
      >>> "login to set time zone" not in widget()
      True

    If there is a from_date then the date provided must be later than that.
    If an earlier date is provided, then getInputValue will raise
    WidgetInputError. The message gives the required date/time in the widget
    time zone even if the date provided was in a different time zone.

      >>> widget.request.form[widget.name] = "2005-07-03"
      >>> widget.from_date = datetime(2006, 5, 23, tzinfo=timezone.utc)
      >>> print(widget.getInputValue())
      ... # doctest: +NORMALIZE_WHITESPACE,+ELLIPSIS
      Traceback (most recent call last):
      ...
      zope.formlib.interfaces.WidgetInputError:
      (...Please pick a date after 2006-05-22 17:00:00...)

    If the date provided is greater than from_date then the widget works as
    expected.

      >>> widget.request.form[widget.name] = "2009-09-14"
      >>> print(widget.getInputValue())  # doctest: +ELLIPSIS
      2009-09-14 00:00:00-07:00

    If to_date is provided then getInputValue() will enforce this too.

      >>> widget.to_date = datetime(2008, 1, 26, tzinfo=timezone.utc)
      >>> print(widget.getInputValue())
      ... # doctest: +NORMALIZE_WHITESPACE,+ELLIPSIS
      Traceback (most recent call last):
      ...
      zope.formlib.interfaces.WidgetInputError:
      (...Please pick a date before 2008-01-25 16:00:00...)

    A datetime picker can be disabled initially:

      >>> "disabled" in widget()
      False
      >>> widget.disabled = True
      >>> "disabled" in widget()
      True

    """

    timeformat = "%Y-%m-%d %H:%M:%S"
    required_time_zone_name: Optional[str] = None
    display_zone = True
    from_date = None
    to_date = None
    disabled = False

    # ZPT that renders our widget
    __call__ = ViewPageTemplateFile("templates/datetime.pt")

    def __init__(self, context, request):
        super().__init__(context, request)
        launchbag = getUtility(ILaunchBag)
        self.system_time_zone_name = launchbag.time_zone_name

    @property
    def supported_input_formats(self):
        date_formats = [
            "%Y-%m-%d",
            "%m-%d-%Y",
            "%m-%d-%y",
            "%m/%d/%Y",
            "%m/%d/%y",
            "%d %b, %Y",
            "%d %b %Y",
            "%b %d, %Y",
            "%b %d %Y",
            "%d %B, %Y",
            "%d %B %Y",
            "%B %d, %Y",
            "B% %d %Y",
        ]

        time_formats = [
            "%H:%M:%S",
            "%H:%M",
            "",
        ]
        outputs = []
        for fmt in time_formats:
            outputs.extend(["%s %s" % (d, fmt) for d in date_formats])

        return [o.strip() for o in outputs]

    @property
    def time_zone_name(self) -> str:
        """The name of the widget time zone for display in the widget."""
        if self.required_time_zone_name is not None:
            return self.required_time_zone_name
        assert (
            self.system_time_zone_name is not None
        ), "DateTime widget needs a time zone."
        return self.system_time_zone_name

    @property
    def time_zone(self) -> tzinfo:
        """The widget time zone.

        This will either give you the user's time zone, or the system
        default time zone of 'UTC',  or a specific "required time zone"
        in cases where this widget is being used to pick a time in an
        externally-defined time zone. For example, when a person will join a
        conference in the time zone in which the conference is being held.

          >>> from datetime import tzinfo
          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__="foo", title="Foo")
          >>> widget = DateTimeWidget(field, TestRequest())

        The time zone is a time zone object, not the string representation
        of that.

          >>> isinstance(widget.time_zone, tzinfo)
          True

        The widget required_time_zone_name is None by default.

          >>> print(widget.required_time_zone_name)
          None

        The widget "system time zone" is generally UTC. It is the logged in
        users time zone, with a fallback to UTC if there is no logged in
        user. Although this isn't used directly, it influences the outcome
        of widget.time_zone.

          >>> print(widget.system_time_zone_name)
          UTC

        When there is no required_time_zone_name, then we get the system
        time zone.

          >>> print(widget.required_time_zone_name)
          None
          >>> print(widget.time_zone_name)
          UTC
          >>> print(repr(widget.time_zone))
          datetime.timezone.utc

        When there is a required_time_zone_name, we get it:

          >>> widget.required_time_zone_name = "Africa/Maseru"
          >>> print(widget.time_zone_name)
          Africa/Maseru
          >>> print(widget.time_zone)  # doctest: +ELLIPSIS
          tzfile('.../Africa/Maseru')

        When the required_time_zone_name is invalid, we fall back to UTC.

          >>> widget.required_time_zone_name = "Some/Nonsense"
          >>> print(widget.time_zone_name)
          Some/Nonsense
          >>> print(repr(widget.time_zone))
          datetime.timezone.utc

        """
        if self.time_zone_name == "UTC":
            return timezone.utc
        else:
            zone = tz.gettz(self.time_zone_name)
            return zone if zone is not None else timezone.utc

    def _align_date_constraints_with_time_zone(self):
        """Ensure that from_date and to_date use the widget time zone."""
        if isinstance(self.from_date, datetime):
            if self.from_date.tzinfo is None:
                # Timezone-naive constraint is interpreted as being in the
                # widget time zone.
                self.from_date = self.from_date.replace(tzinfo=self.time_zone)
            else:
                self.from_date = self.from_date.astimezone(self.time_zone)
        if isinstance(self.to_date, datetime):
            if self.to_date.tzinfo is None:
                # Timezone-naive constraint is interpreted as being in the
                # widget time zone.
                self.to_date = self.to_date.replace(tzinfo=self.time_zone)
            else:
                self.to_date = self.to_date.astimezone(self.time_zone)

    @property
    def disabled_flag(self):
        """Return a string to make the form input disabled if necessary.

        Returns ``None`` otherwise, to omit the ``disabled`` attribute
        completely.
        """
        if self.disabled:
            return "disabled"
        else:
            return None

    @property
    def daterange(self):
        """The javascript variable giving the allowed date range to pick.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> from datetime import datetime
          >>> field = Field(__name__="foo", title="Foo")
          >>> widget = DateTimeWidget(field, TestRequest())
          >>> from_date = datetime(2004, 4, 5)
          >>> to_date = datetime(2004, 4, 10)

        The default date range is unlimited:

          >>> print(widget.from_date)
          None
          >>> print(widget.to_date)
          None

        If there is no date range, we return None so it won't be included
        on the template at all:

          >>> widget.from_date = None
          >>> widget.to_date = None
          >>> print(widget.daterange)
          None

        The daterange is correctly expressed as JavaScript in all the
        different permutations of to/from dates:

          >>> widget.from_date = from_date
          >>> widget.to_date = None
          >>> widget.daterange
          '[[2004,04,05],null]'

          >>> widget.from_date = None
          >>> widget.to_date = to_date
          >>> widget.daterange
          '[null,[2004,04,10]]'

          >>> widget.from_date = from_date
          >>> widget.to_date = to_date
          >>> widget.daterange
          '[[2004,04,05],[2004,04,10]]'

        The date range is displayed in the page when the widget is
        displayed:

          >>> "[[2004,04,05],[2004,04,10]]" in widget()
          True

        """
        self._align_date_constraints_with_time_zone()
        if not (self.from_date or self.to_date):
            return None
        daterange = "["
        if self.from_date is None:
            daterange += "null,"
        else:
            daterange += self.from_date.strftime("[%Y,%m,%d],")
        if self.to_date is None:
            daterange += "null]"
        else:
            daterange += self.to_date.strftime("[%Y,%m,%d]]")
        return daterange

    def getInputValue(self):
        """Return the date, if it is in the allowed date range."""
        value = super().getInputValue()
        if value is None:
            return None
        # Establish if the value is within the date range.
        self._align_date_constraints_with_time_zone()
        if self.from_date is not None and value < self.from_date:
            limit = self.from_date.strftime(self.timeformat)
            self._error = WidgetInputError(
                self.name,
                self.label,
                LaunchpadValidationError(
                    "Please pick a date after %s" % limit
                ),
            )
            raise self._error
        if self.to_date is not None and value > self.to_date:
            limit = self.to_date.strftime(self.timeformat)
            self._error = WidgetInputError(
                self.name,
                self.label,
                LaunchpadValidationError(
                    "Please pick a date before %s" % limit
                ),
            )
            raise self._error
        return value

    def _checkSupportedFormat(self, input):
        """Checks that the input is in a usable format."""
        for fmt in self.supported_input_formats:
            try:
                datetime.strptime(input.strip(), fmt)
            except ValueError as e:
                if "unconverted data remains" in str(e):
                    return
                else:
                    failure = e
            else:
                return
        try:
            if failure:
                raise ConversionError("Invalid date value", failure)
        finally:
            # Avoid traceback reference cycles.
            del failure

    def _toFieldValue(self, input):
        """Return parsed input (datetime) as a date."""
        return self._parseInput(input)

    def _parseInput(self, input):
        """Convert a string to a datetime value.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__="foo", title="Foo")
          >>> widget = DateTimeWidget(field, TestRequest())
          >>> widget.required_time_zone_name = "UTC"
          >>> widget.time_zone_name
          'UTC'

        The widget converts an empty string to the missing value:

          >>> widget._parseInput("") == field.missing_value
          True

        The widget prints out times in UTC:

          >>> print(widget._parseInput("2006-01-01 12:00:00"))
          2006-01-01 12:00:00+00:00

        But it will handle other time zones:

          >>> widget.required_time_zone_name = "Australia/Perth"
          >>> print(widget._parseInput("2006-01-01 12:00:00"))
          2006-01-01 12:00:00+08:00

        Invalid dates result in a ConversionError:

          >>> print(widget._parseInput("not a date"))
          ... # doctest: +NORMALIZE_WHITESPACE,+ELLIPSIS
          Traceback (most recent call last):
            ...
          zope.formlib.interfaces.ConversionError: ('Invalid date value', ...)
        """
        if input == self._missing:
            return self.context.missing_value
        self._checkSupportedFormat(input)
        try:
            year, month, day, hour, minute, second, _ = parse(input)
            second, micro = divmod(second, 1.0)
            micro = round_half_up(micro * 1000000)
            dt = datetime(year, month, day, hour, minute, int(second), micro)
        except (DateTimeError, ValueError, IndexError) as v:
            raise ConversionError("Invalid date value", v)
        return dt.replace(tzinfo=self.time_zone)

    def _toFormValue(self, value):
        """Convert a date to its string representation.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__="foo", title="Foo")
          >>> widget = DateTimeWidget(field, TestRequest())

        The 'missing' value is converted to an empty string:

          >>> print(widget._toFormValue(field.missing_value))
          <BLANKLINE>

        DateTimes are displayed without the corresponding time zone
        information:

          >>> dt = datetime(2006, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
          >>> widget._toFormValue(dt)
          '2006-01-01 12:00:00'

        The date value will be converted to the widget's time zone
        before being displayed:

          >>> widget.required_time_zone_name = "America/New_York"
          >>> widget._toFormValue(dt)
          '2006-01-01 07:00:00'
        """
        if value == self.context.missing_value:
            return self._missing
        return value.astimezone(self.time_zone).strftime(self.timeformat)

    def formvalue(self):
        """Return the value for the form to render, accessed via the
        formvalue property.

        This will be data from the request, or the fields value
        if the form has not been submitted. This method should return
        an object that makes the template simple and readable.

        """
        if not self._renderedValueSet():
            if self.hasInput():
                try:
                    value = self.getInputValue()
                except InputErrors:
                    return self._getFormInput()
            else:
                value = self._getDefault()
        else:
            value = self._data
        if value is None:
            return None
        return self._toFormValue(value)


class DateWidget(DateTimeWidget):
    """A date selection widget with popup selector.

    The assumed underlying storage is a datetime (in the database) so this
    class modifies that datetime into a date for presentation purposes. That
    date is always in UTC.

    The DateWidget subclass can limit requests to date ranges:

      >>> from datetime import date
      >>> from zope.publisher.browser import TestRequest
      >>> from zope.schema import Field
      >>> field = Field(__name__="foo", title="Foo")
      >>> from_date = date(2004, 4, 5)
      >>> to_date = date(2004, 4, 10)
      >>> widget = DateWidget(field, TestRequest())
      >>> widget.from_date = from_date
      >>> widget.to_date = to_date
      >>> "[[2004,04,05],[2004,04,10]]" in widget()
      True

    This widget ignores required_time_zone_name and system_time_zone_name and
    interprets everything as UTC. This does not matter, because it is only
    picking the date, and it will always be rendered as a date sans time
    zone even if it is stored as a datetime.

      >>> widget.time_zone
      datetime.timezone.utc

      >>> widget.system_time_zone_name = "America/New_York"
      >>> widget.time_zone
      datetime.timezone.utc

      >>> widget.required_time_zone_name = "America/Los_Angeles"
      >>> widget.time_zone
      datetime.timezone.utc

    A date picker can be disabled initially:

      >>> "disabled" in widget()
      False
      >>> widget.disabled = True
      >>> "disabled" in widget()
      True

    """

    timeformat = "%Y-%m-%d"
    time_zone_name = "UTC"

    # ZPT that renders our widget
    __call__ = ViewPageTemplateFile("templates/date.pt")

    def _toFieldValue(self, input):
        """Return parsed input (datetime) as a date.

        The input is expected to be a text string in a format that datetime
        can parse. The input is parsed by the DateTimeWidget._parseInput
        method, which returns a datetime, and this method turns that into a
        date (without the time).

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__="foo", title="Foo")
          >>> widget = DateWidget(field, TestRequest())

        The widget converts an empty string to the missing value:

          >>> widget._toFieldValue("") == field.missing_value
          True

        The widget ignores time and time zone information, returning only
        the date:

          >>> print(widget._toFieldValue("2006-01-01 12:00:00"))
          2006-01-01

        Even if you feed it information that gives a time zone, it will
        ignore that:

          >>> print(widget._toFieldValue("2006-01-01 2:00:00+06:00"))
          2006-01-01
          >>> print(widget._toFieldValue("2006-01-01 23:00:00-06:00"))
          2006-01-01

        Invalid dates result in a ConversionError:

          >>> print(widget._toFieldValue("not a date"))
          ... # doctest: +NORMALIZE_WHITESPACE,+ELLIPSIS
          Traceback (most recent call last):
            ...
          zope.formlib.interfaces.ConversionError: ('Invalid date value', ...)

        """
        parsed = self._parseInput(input)
        if parsed is None:
            return None
        return parsed.date()

    def _toFormValue(self, value):
        """Convert a datetime to its string representation.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__="foo", title="Foo")
          >>> widget = DateWidget(field, TestRequest())

        The 'missing' value is converted to an empty string:

          >>> print(widget._toFormValue(field.missing_value))
          <BLANKLINE>

        The widget ignores time and time zone information, returning only
        the date:

          >>> dt = datetime(2006, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
          >>> widget._toFormValue(dt)
          '2006-01-01'

        The widget can handle a date just as well as a datetime, of course.

          >>> a_date = dt.date()
          >>> widget._toFormValue(a_date)
          '2006-01-01'

        """
        if value == self.context.missing_value:
            return self._missing
        return value.strftime(self.timeformat)

    def setRenderedValue(self, value):
        """Render a date from the underlying datetime."""
        if value is None:
            self._data = None
            return
        if isinstance(value, datetime):
            self._data = value.date()
        else:
            self._data = value


class DatetimeDisplayWidget(DisplayWidget):
    """Display timestamps in the users preferred time zone"""

    def __call__(self):
        time_zone = getUtility(ILaunchBag).time_zone
        if self._renderedValueSet():
            value = self._data
        else:
            value = self.context.default
        if value == self.context.missing_value:
            return ""
        value = value.astimezone(time_zone)
        return html_escape(
            "%s %s" % (value.strftime("%Y-%m-%d %H:%M:%S", tzname(value)))
        )
