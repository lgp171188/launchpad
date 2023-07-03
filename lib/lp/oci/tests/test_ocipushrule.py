# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI registry push rules."""

from storm.store import Store
from testtools.matchers import MatchesStructure
from zope.component import getUtility
from zope.schema import ValidationError

from lp.oci.interfaces.ocipushrule import (
    IOCIPushRule,
    IOCIPushRuleSet,
    OCIPushRuleAlreadyExists,
)
from lp.oci.model.ociregistrycredentials import OCIRegistryCredentials
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.layers import LaunchpadZopelessLayer


class TestOCIPushRule(OCIConfigHelperMixin, TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.setConfig()

    def test_implements_interface(self):
        push_rule = self.factory.makeOCIPushRule()
        self.assertProvides(push_rule, IOCIPushRule)

    def test_change_attribute(self):
        push_rule = self.factory.makeOCIPushRule()
        with person_logged_in(push_rule.recipe.owner):
            push_rule.setNewImageName("new image name")

        found_rule = push_rule.recipe.push_rules[0]
        self.assertEqual(found_rule.image_name, "new image name")

    def test_change_image_name_existing(self):
        first = self.factory.makeOCIPushRule(image_name="first")
        second = self.factory.makeOCIPushRule(
            image_name="second",
            registry_credentials=first.registry_credentials,
        )
        self.assertRaises(
            OCIPushRuleAlreadyExists, second.setNewImageName, first.image_name
        )

    def test_username_retrieval(self):
        credentials = self.factory.makeOCIRegistryCredentials()
        push_rule = self.factory.makeOCIPushRule(
            registry_credentials=credentials
        )
        self.assertEqual(credentials.username, push_rule.username)

    def test_valid_registry_url(self):
        owner = self.factory.makePerson()
        url = "asdf://foo.com"
        credentials = {"username": "foo"}
        self.assertRaisesRegex(
            ValidationError,
            "asdf://foo.com is not a valid URL for 'url' attribute",
            OCIRegistryCredentials,
            owner,
            url,
            credentials,
        )
        # Avoid trying to flush the incomplete object on cleanUp.
        Store.of(owner).rollback()


class TestOCIPushRuleSet(OCIConfigHelperMixin, TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
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
            image_name=image_name,
        )

        self.assertThat(
            push_rule,
            MatchesStructure.byEquality(
                recipe=recipe,
                registry_credentials=registry_credentials,
                image_name=image_name,
            ),
        )

    def test_new_with_existing(self):
        recipe = self.factory.makeOCIRecipe()
        registry_credentials = self.factory.makeOCIRegistryCredentials()
        image_name = self.factory.getUniqueUnicode()
        getUtility(IOCIPushRuleSet).new(
            recipe=recipe,
            registry_credentials=registry_credentials,
            image_name=image_name,
        )

        self.assertRaises(
            OCIPushRuleAlreadyExists,
            getUtility(IOCIPushRuleSet).new,
            recipe,
            registry_credentials,
            image_name,
        )
