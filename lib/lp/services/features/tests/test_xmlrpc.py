# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for FeatureFlagApplication."""

import xmlrpc.client

from lp.services import features
from lp.services.config import config
from lp.services.features.flags import FeatureController
from lp.services.features.rulesource import StormFeatureRuleSource
from lp.services.features.scopes import (
    DefaultScope,
    FixedScope,
    MultiScopeHandler,
)
from lp.services.features.xmlrpc import FeatureFlagApplication
from lp.testing import TestCaseWithFactory, feature_flags, set_feature_flag
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.xmlrpc import XMLRPCTestTransport


class TestGetFeatureFlag(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.endpoint = FeatureFlagApplication()

    def installFeatureController(self, feature_controller):
        old_features = features.get_relevant_feature_controller()
        features.install_feature_controller(feature_controller)
        self.addCleanup(features.install_feature_controller, old_features)

    def test_getFeatureFlag_returns_None_by_default(self):
        self.assertIs(None, self.endpoint.getFeatureFlag("unknown"))

    def test_getFeatureFlag_returns_true_for_set_flag(self):
        flag_name = "flag"
        with feature_flags():
            set_feature_flag(flag_name, "1")
            self.assertEqual("1", self.endpoint.getFeatureFlag(flag_name))

    def test_getFeatureFlag_ignores_relevant_feature_controller(self):
        # getFeatureFlag should only consider the scopes it is asked to
        # consider, not any that happen to be active due to the XML-RPC
        # request itself.
        flag_name = "flag"
        scope_name = "scope"
        self.installFeatureController(
            FeatureController(
                MultiScopeHandler(
                    [DefaultScope(), FixedScope(scope_name)]
                ).lookup,
                StormFeatureRuleSource(),
            )
        )
        set_feature_flag(flag_name, "1", scope_name)
        self.assertEqual(None, self.endpoint.getFeatureFlag(flag_name))

    def test_getFeatureFlag_considers_supplied_scope(self):
        flag_name = "flag"
        scope_name = "scope"
        with feature_flags():
            set_feature_flag(flag_name, "value", scope_name)
            self.assertEqual(
                "value", self.endpoint.getFeatureFlag(flag_name, [scope_name])
            )

    def test_getFeatureFlag_turns_user_into_team_scope(self):
        flag_name = "flag"
        person = self.factory.makePerson()
        team = self.factory.makeTeam(members=[person])
        with feature_flags():
            set_feature_flag(flag_name, "value", "team:" + team.name)
            self.assertEqual(
                "value",
                self.endpoint.getFeatureFlag(
                    flag_name, ["user:" + person.name]
                ),
            )

    def test_xmlrpc_interface_unset(self):
        sp = xmlrpc.client.ServerProxy(
            config.launchpad.feature_flags_endpoint,
            transport=XMLRPCTestTransport(),
            allow_none=True,
        )
        self.assertEqual(None, sp.getFeatureFlag("flag"))

    def test_xmlrpc_interface_set(self):
        sp = xmlrpc.client.ServerProxy(
            config.launchpad.feature_flags_endpoint,
            transport=XMLRPCTestTransport(),
            allow_none=True,
        )
        flag_name = "flag"
        with feature_flags():
            set_feature_flag(flag_name, "1")
            self.assertEqual("1", sp.getFeatureFlag(flag_name))
