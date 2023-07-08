# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for lp.services.config.zcml."""

import io
import os.path
from textwrap import dedent

from zope.configuration.config import ConfigurationMachine
from zope.configuration.xmlconfig import (
    processxmlfile,
    registerCommonDirectives,
)

from lp.services.config.fixture import ConfigUseFixture
from lp.services.config.tests.test_config_lookup import ConfigTestCase
from lp.testing.layers import BaseLayer


class TestIncludeLaunchpadOverrides(ConfigTestCase):
    layer = BaseLayer

    def test_includes_overrides(self):
        instance_dir = self.setUpInstanceConfig("zcmltest")
        self.useFixture(ConfigUseFixture("zcmltest"))
        with open(os.path.join(instance_dir, "test.zcml"), "w") as f:
            f.write(
                dedent(
                    """
                    <configure xmlns="http://namespaces.zope.org/zope"
                               xmlns:meta="http://namespaces.zope.org/meta">
                        <meta:provides feature="testfeature" />
                    </configure>
                    """
                )
            )
        context = ConfigurationMachine()
        self.assertFalse(context.hasFeature("testfeature"))
        registerCommonDirectives(context)
        topfile = io.StringIO(
            dedent(
                """
                <configure xmlns="http://namespaces.zope.org/zope"
                           xmlns:lp="http://namespaces.canonical.com/lp">
                    <include package="lp.services.config" file="meta.zcml" />
                    <lp:includeLaunchpadOverrides />
                </configure>
                """
            )
        )
        processxmlfile(topfile, context, testing=True)
        self.assertTrue(context.hasFeature("testfeature"))
