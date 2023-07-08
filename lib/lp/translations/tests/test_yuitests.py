# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Run YUI.test tests."""

__all__ = []

from lp.testing import YUIUnitTestCase, build_yui_unittest_suite
from lp.testing.layers import YUITestLayer


class TranslationsYUIUnitTestCase(YUIUnitTestCase):
    layer = YUITestLayer
    suite_name = "TranslationsYUIUnitTests"


def test_suite():
    app_testing_path = "lp/translations"
    return build_yui_unittest_suite(
        app_testing_path, TranslationsYUIUnitTestCase
    )
