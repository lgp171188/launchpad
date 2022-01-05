# Copyright 2017-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Beautiful Soup wrapper for Launchpad."""

__all__ = [
    'BeautifulSoup',
    'SoupStrainer',
    ]


from bs4 import BeautifulSoup as _BeautifulSoup
from bs4.element import SoupStrainer


class BeautifulSoup(_BeautifulSoup):

    def __init__(self, markup="", features="html.parser", **kwargs):
        if (not isinstance(markup, str) and
                "from_encoding" not in kwargs):
            kwargs["from_encoding"] = "UTF-8"
        super().__init__(markup=markup, features=features, **kwargs)
