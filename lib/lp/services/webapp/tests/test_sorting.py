# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from doctest import ELLIPSIS, NORMALIZE_WHITESPACE, DocTestSuite


def test_suite():
    suite = DocTestSuite(
        "lp.services.webapp.sorting",
        optionflags=NORMALIZE_WHITESPACE | ELLIPSIS,
    )
    return suite
