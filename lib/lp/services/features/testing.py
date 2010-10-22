# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helpers for writing tests that use feature flags."""

__metaclass__ = type
__all__ = ['active_features']


from fixtures import Fixture
from lp.services.features import per_thread
from lp.services.features.flags import FeatureController
from lp.services.features.rulesource import StormFeatureRuleSource


class FeatureFixture(Fixture):
    """A fixture that sets a feature.

    The fixture takes a dictionary as its constructor argument. The keys of
    the dictionary are features to be set. All existing flags will be cleared.

    Call the fixture's `setUp()' method to install the features with the
    desired values.  Calling `cleanUp()' will restore the original values.
    You can also install this fixture by inheriting from
    `fixtures.TestWithFixtures' and then calling the TestCase's
    `self.useFixture()' method.

    The fixture can also be used as a context manager. The value of the
    feature within the context block is set to the dictionary's key's value.
    The values are restored when the block exits.
    """

    def __init__(self, features_dict):
        """Constructor.

        :param features_dict: A dictionary-like object with keys and values
            that are flag names and those flags' settings.
        """
        self.desired_features = features_dict

    def setUp(self):
        """Set the feature flags that this fixture is responsible for."""
        super(FeatureFixture, self).setUp()

        rule_source = StormFeatureRuleSource()
        self.addCleanup(
            rule_source.setAllRules, rule_source.getAllRulesAsTuples())
        rule_source.setAllRules(self.makeNewRules())

        original_controller = getattr(per_thread, 'features', None)
        controller = FeatureController(lambda _: True, rule_source)
        per_thread.features = controller
        self.addCleanup(setattr, per_thread, 'features', original_controller)

    def makeNewRules(self):
        """Make a set of new feature flag rules."""
        # XXX mars 2010-10-22
        # This would be much nicer if the rules were built as a namedtuple
        # instead of a list of position-dependant tuple elements.
        # Still waiting for Python 2.6 though.

        # Create a list of the new rules. Note that rules with a None
        # value are quietly dropped, since you can't assign None as a
        # feature flag value (it would come out as u'None') and setting
        # a flag to None essentially means turning it off anyway.
        #
        # Flags that are not present in the set of new rules will be deleted
        # by setAllRules().

        new_rules = [
            (flag_name,         # Flag name.
             'default',         # Scope.
             1,                 # Priority 1 is a safe default.
             unicode(value))    # Flag value.
            for flag_name, value in self.desired_features.iteritems()
                if value is not None]

        return new_rules
