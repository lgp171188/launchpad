# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI registry push rules."""

from __future__ import absolute_import, print_function, unicode_literals

<<<<<<< 16ae97a6453c1c6d4e298ff58b1cc50a78f4b326
from testtools.matchers import MatchesStructure
=======
>>>>>>> Add OCIPushRule model
from zope.component import getUtility

from lp.oci.interfaces.ocipushrule import (
    IOCIPushRule,
    IOCIPushRuleSet,
    )
<<<<<<< 16ae97a6453c1c6d4e298ff58b1cc50a78f4b326
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
=======
from lp.oci.tests.test_ociregistrycredentials import OCIConfigHelperMixin
from lp.testing import TestCaseWithFactory
>>>>>>> Add OCIPushRule model
from lp.testing.layers import LaunchpadZopelessLayer


class TestOCIPushRule(OCIConfigHelperMixin, TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIPushRule, self).setUp()
        self.setConfig()

    def test_implements_interface(self):
        push_rule = self.factory.makeOCIPushRule()
        self.assertProvides(push_rule, IOCIPushRule)

<<<<<<< 16ae97a6453c1c6d4e298ff58b1cc50a78f4b326
    def test_change_attribute(self):
        push_rule = self.factory.makeOCIPushRule()
        with person_logged_in(push_rule.recipe.owner):
            push_rule.image_name = 'new image name'

        found_rule = push_rule.recipe.push_rules[0]
        self.assertEqual(found_rule.image_name, 'new image name')

=======
>>>>>>> Add OCIPushRule model

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

<<<<<<< 16ae97a6453c1c6d4e298ff58b1cc50a78f4b326
        self.assertThat(
            push_rule,
            MatchesStructure.byEquality(
                recipe=recipe,
                registry_credentials=registry_credentials,
                image_name=image_name))
=======
        self.assertEqual(push_rule.recipe, recipe)
        self.assertEqual(push_rule.registry_credentials, registry_credentials)
        self.assertEqual(push_rule.image_name, image_name)
>>>>>>> Add OCIPushRule model
