# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Run YUI.test tests."""

__all__ = []

from lp.testing import YUIUnitTestCase, build_yui_unittest_suite
from lp.testing.layers import YUITestLayer


class AuthYUIUnitTestCase(YUIUnitTestCase):
    layer = YUITestLayer
    suite_name = "AuthYUIUnitTests"


def test_suite():
    app_testing_path = "lp/services/auth"
    return build_yui_unittest_suite(app_testing_path, AuthYUIUnitTestCase)
