# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import os

from lp.services.testing import build_test_suite
from lp.services.webapp.tests import test_notifications
from lp.testing.layers import (
    FunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setGlobs,
    setUp,
    tearDown,
    )


here = os.path.dirname(os.path.realpath(__file__))


special = {
    'canonical_url.rst': LayeredDocFileSuite(
        '../doc/canonical_url.rst',
        setUp=setUp, tearDown=tearDown,
        layer=FunctionalLayer,),
    'notification-text-escape.rst': LayeredDocFileSuite(
        '../doc/notification-text-escape.rst',
        setUp=test_notifications.setUp,
        tearDown=test_notifications.tearDown,
        stdout_logging=False, layer=None),
    'test_adapter.rst': LayeredDocFileSuite(
        '../doc/test_adapter.rst',
        setUp=setGlobs,
        layer=LaunchpadFunctionalLayer),
# XXX Julian 2009-05-13, bug=376171
# Temporarily disabled because of intermittent failures.
#    'test_adapter_timeout.rst': LayeredDocFileSuite(
#        '../doc/test_adapter_timeout.rst',
#        setUp=setUp, tearDown=tearDown,
#        layer=LaunchpadFunctionalLayer),
    'test_adapter_permissions.rst': LayeredDocFileSuite(
        '../doc/test_adapter_permissions.rst',
        setUp=setGlobs,
        layer=LaunchpadFunctionalLayer),
    'uri.rst': LayeredDocFileSuite(
        '../doc/uri.rst',
        setUp=setUp, tearDown=tearDown,
        layer=FunctionalLayer),
    }


def test_suite():
    return build_test_suite(here, special, layer=LaunchpadFunctionalLayer)
