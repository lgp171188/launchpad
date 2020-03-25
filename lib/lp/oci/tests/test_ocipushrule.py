# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI registry push rules."""

from __future__ import absolute_import, print_function, unicode_literals

from testtools.matchers import MatchesStructure
from zope.component import getUtility

from lp.oci.interfaces.ocipushrule import (
    IOCIPushRule,
    IOCIPushRuleSet,
    )
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.testing import TestCaseWithFactory
from lp.testing.layers import LaunchpadZopelessLayer


class TestOCIPushRule(OCIConfigHelperMixin, TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIPushRule, self).setUp()
        self.setConfig()

    def test_implements_interface(self):
        push_rule = self.factory.makeOCIPushRule()
        self.assertProvides(push_rule, IOCIPushRule)


class TestOCIPushRuleSet(OCIConfigHelperMixin, TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIPushRuleSet, self).setUp()
        self.setConfig()

    def test_implements_interface(self):
        push_rule_set = getUtility(IOCIPushRuleSet)
        self.assertProvides(push_rule_set, IOCIPushRuleSet)

    def test_new(self):
        recipe = self.factory.makeOCIRecipe()
        registry_credentials = self.factory.makeOCIRegistryCredentials()
        image_name = self.factory.getUniqueUnicode()
        push_rule = getUtility(IOCIPushRuleSet).new(
            recipe=recipe,
            registry_credentials=registry_credentials,
            image_name=image_name)

        self.assertThat(
            push_rule,
            MatchesStructure.byEquality(
                recipe=recipe,
                registry_credentials=registry_credentials,
                image_name=image_name))
