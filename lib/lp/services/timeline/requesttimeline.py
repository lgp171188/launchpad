# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Manage a Timeline for a request."""

__all__ = [
    "get_request_timeline",
    "make_timeline",
    "set_request_timeline",
    "temporary_request_timeline",
]

import sys
from contextlib import contextmanager
from functools import partial
from typing import Callable, MutableSequence, Optional

from timeline import Timeline
from timeline.timedaction import TimedAction
from zope.exceptions.exceptionformatter import extract_stack

# XXX RobertCollins 2010-09-01 bug=623199: Undesirable but pragmatic.
# Because of this bug, rather than using request.annotations we have
# to work in with the webapp.adapter request model, which is
# different to that used by get_current_browser_request.
from lp.services import webapp


class FilteredTimeline(Timeline):
    """A timeline that filters its actions.

    This is useful for requests that are expected to log actions with very
    large details (for example, large bulk SQL INSERT statements), where we
    don't want the overhead of storing those in memory.
    """

    def __init__(self, actions=None, detail_filter=None, **kwargs):
        super().__init__(actions=actions, **kwargs)
        self.detail_filter = detail_filter

    def start(self, category, detail, allow_nested=False):
        """See `Timeline`."""
        if self.detail_filter is not None:
            detail = self.detail_filter(category, detail)
        return super().start(category, detail)


def format_stack():
    """Format a stack like traceback.format_stack, but skip 2 frames.

    This means the stack formatting frame isn't in the backtrace itself.

    Also add supplemental information to the traceback using
    `zope.exceptions.exceptionformatter`.
    """
    return extract_stack(f=sys._getframe(2))


def make_timeline(
    actions: Optional[MutableSequence[TimedAction]] = None,
    detail_filter: Optional[Callable[[str, str], str]] = None,
) -> Timeline:
    """Make a new `Timeline`, configured appropriately for Launchpad.

    :param actions: The sequence used to store the logged SQL statements.
    :param detail_filter: An optional (category, detail) -> detail callable
        that filters action details.  This may be used when some details are
        expected to be very large.
    """
    if detail_filter is not None:
        factory = partial(FilteredTimeline, detail_filter=detail_filter)
    else:
        factory = Timeline
    # XXX cjwatson 2023-03-09: Ideally we'd pass `format_stack=format_stack`
    # here so that we pick up traceback supplements.  Unfortunately, the act
    # of formatting traceback supplements (e.g. TALESTracebackSupplement)
    # often turns out to involve database access, and the effect of that is
    # to recursively add a timeline action, which seems bad; it can also be
    # problematic for the parts of a timeline that immediately follow the
    # end of a transaction.  Blocking database access here just results in a
    # traceback from the exception formatter, which isn't much better.
    # Until we find some solution to this, we'll have to live with plain
    # tracebacks.
    return factory(actions=actions)


def get_request_timeline(request):
    """Get a `Timeline` for request.

    This should ideally return the request.annotations['timeline'], creating it
    if necessary. However due to bug 623199 it instead using the adapter
    context for 'requests'. Once bug 623199 is fixed it will instead use the
    request annotations.

    :param request: A zope/launchpad request object.
    :return: A timeline.timeline.Timeline object for the request.
    """
    try:
        return webapp.adapter._local.request_timeline
    except AttributeError:
        return set_request_timeline(request, make_timeline())
    # Disabled code path: bug 623199, ideally we would use this code path.
    return request.annotations.setdefault("timeline", make_timeline())


def set_request_timeline(request, timeline):
    """Explicitly set a timeline for request.

    This is used by code which wants to manually assemble a timeline.

    :param request: A zope/launchpad request object.
    :param timeline: A Timeline.
    """
    webapp.adapter._local.request_timeline = timeline
    return timeline
    # Disabled code path: bug 623199, ideally we would use this code path.
    request.annotations["timeline"] = timeline


@contextmanager
def temporary_request_timeline(request):
    """Give `request` a temporary timeline.

    This is useful in contexts where we want to raise an OOPS but we know
    that the timeline is uninteresting and may be very large.

    :param request: A Zope/Launchpad request object.
    """
    old_timeline = get_request_timeline(request)
    try:
        set_request_timeline(request, make_timeline())
        yield
    finally:
        set_request_timeline(request, old_timeline)
