# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper functions for testing feeds."""

from __future__ import absolute_import, print_function

__metaclass__ = type
__all__ = [
    'IThing',
    'parse_entries',
    'parse_ids',
    'parse_links',
    'Thing',
    'ThingFeedView',
    ]

from zope.interface import (
    Attribute,
    implementer,
    Interface,
    )

from lp.services.beautifulsoup import (
    BeautifulSoup,
    SoupStrainer,
    )
from lp.services.webapp.publisher import LaunchpadView


class IThing(Interface):
    value = Attribute('the value of the thing')


@implementer(IThing)
class Thing(object):

    def __init__(self, value):
        self.value = value

        def __repr__(self):
            return "<Thing '%s'>" % self.value


class ThingFeedView(LaunchpadView):
    usedfor = IThing
    feedname = "thing-feed"

    def __call__(self):
        return "a feed view on an IThing"


def parse_entries(contents):
    """Define a helper function for parsing feed entries."""
    strainer = SoupStrainer('entry')
    entries = [
        tag for tag in BeautifulSoup(contents, 'xml', parse_only=strainer)]
    return entries


def parse_links(contents, rel):
    """Define a helper function for parsing feed links."""
    strainer = SoupStrainer('link', rel=rel)
    entries = [
        tag for tag in BeautifulSoup(contents, 'xml', parse_only=strainer)]
    return entries


def parse_ids(contents):
    """Define a helper function for parsing ids."""
    strainer = SoupStrainer('id')
    ids = [tag for tag in BeautifulSoup(contents, 'xml', parse_only=strainer)]
    return ids
