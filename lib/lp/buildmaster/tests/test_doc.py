# Copyright 2015-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Run doctests and pagetests."""

from __future__ import absolute_import, print_function, unicode_literals

import os

from lp.services.config import config
from lp.services.testing import build_test_suite
from lp.testing import (
    ANONYMOUS,
    login,
    logout,
    )
from lp.testing.dbuser import switch_dbuser
from lp.testing.layers import (
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setGlobs,
    setUp,
    tearDown,
    )


here = os.path.dirname(os.path.realpath(__file__))


def buildmasterSetUp(test):
    """Setup a typical builddmaster test environment.

    Log in as ANONYMOUS and perform DB operations as the builddmaster
    dbuser.
    """
    test_dbuser = config.builddmaster.dbuser
    login(ANONYMOUS)
    setGlobs(test)
    test.globs['test_dbuser'] = test_dbuser
    switch_dbuser(test_dbuser)


def buildmasterTearDown(test):
    logout()


special = {
    'builder.txt': LayeredDocFileSuite(
        '../doc/builder.txt',
        setUp=setUp, tearDown=tearDown,
        layer=LaunchpadFunctionalLayer),
    'buildqueue.txt': LayeredDocFileSuite(
        '../doc/buildqueue.txt',
        setUp=setUp, tearDown=tearDown,
        layer=LaunchpadFunctionalLayer),
    }


def test_suite():
    return build_test_suite(
        here, special, layer=LaunchpadZopelessLayer,
        setUp=lambda test: setUp(test, future=True))
