# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import unittest
from doctest import DocTestSuite


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(DocTestSuite("lp.services.database.sort_sql"))
    return suite
