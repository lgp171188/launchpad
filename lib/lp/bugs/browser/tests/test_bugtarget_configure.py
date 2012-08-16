# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version (see the file LICENSE).

"""Unit tests for bug configuration views."""

__metaclass__ = type

from lp.app.enums import ServiceUsage
from lp.registry.interfaces.person import TeamMembershipPolicy
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.views import create_initialized_view


class TestProductBugConfigurationView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestProductBugConfigurationView, self).setUp()
        self.owner = self.factory.makePerson(name='boing-owner')
        self.bug_supervisor = self.factory.makePerson(
            name='boing-bug-supervisor')
        self.product = self.factory.makeProduct(
            name='boing', owner=self.owner,
            bug_supervisor=self.bug_supervisor)
        login_person(self.owner)

    def _makeForm(self):
        return {
            'field.bug_supervisor': 'boing-owner',
            'field.security_contact': 'boing-owner',
            'field.bugtracker': 'malone',
            'field.enable_bug_expiration': 'on',
            'field.remote_product': 'sf-boing',
            'field.bug_reporting_guidelines': 'guidelines',
            'field.bug_reported_acknowledgement': 'acknowledgement message',
            'field.enable_bugfiling_duplicate_search': False,
            'field.private_bugs': 'off',
            'field.actions.change': 'Change',
            }

    def test_owner_view_attributes(self):
        view = create_initialized_view(
            self.product, name='+configure-bugtracker')
        label = 'Configure bug tracker'
        self.assertEqual(label, view.label)
        fields = [
            'bugtracker', 'enable_bug_expiration', 'remote_product',
            'bug_reporting_guidelines', 'bug_reported_acknowledgement',
            'enable_bugfiling_duplicate_search', 'private_bugs',
            'bug_supervisor', 'security_contact']
        self.assertEqual(fields, view.field_names)
        self.assertEqual('http://launchpad.dev/boing', view.next_url)
        self.assertEqual('http://launchpad.dev/boing', view.cancel_url)

    def test_bug_supervisor_view_attributes(self):
        login_person(self.bug_supervisor)
        view = create_initialized_view(
            self.product, name='+configure-bugtracker')
        label = 'Configure bug tracker'
        self.assertEqual(label, view.label)
        fields = [
            'bugtracker', 'enable_bug_expiration', 'remote_product',
            'bug_reporting_guidelines', 'bug_reported_acknowledgement',
            'enable_bugfiling_duplicate_search', 'private_bugs']
        self.assertEqual(fields, view.field_names)
        self.assertEqual('http://launchpad.dev/boing', view.next_url)
        self.assertEqual('http://launchpad.dev/boing', view.cancel_url)

    def test_all_data_change(self):
        # Verify that the composed interface supports all fields.
        # This is a sanity check. The bug_supervisor, security_contact and
        # bugtracker field are rigorously tested in their respective tests.
        form = self._makeForm()
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertEqual(self.owner, self.product.bug_supervisor)
        self.assertEqual(self.owner, self.product.security_contact)
        self.assertEqual(
            ServiceUsage.LAUNCHPAD,
            self.product.bug_tracking_usage)
        self.assertTrue(self.product.enable_bug_expiration)
        self.assertEqual('sf-boing', self.product.remote_product)
        self.assertEqual('guidelines', self.product.bug_reporting_guidelines)
        self.assertEqual(
            'acknowledgement message',
            self.product.bug_reported_acknowledgement)
        self.assertFalse(self.product.enable_bugfiling_duplicate_search)

    def test_security_contact_invalid(self):
        # Verify that invalid security_contact states are reported.
        # This is a sanity check. The security_contact is rigorously tested
        # in its own test.
        other_person = self.factory.makePerson()
        form = self._makeForm()
        form['field.security_contact'] = other_person.name
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual(1, len(view.errors))

    def test_enable_bug_expiration_with_launchpad(self):
        # Verify that enable_bug_expiration can be True bugs are tracked
        # in Launchpad.
        form = self._makeForm()
        form['field.enable_bug_expiration'] = 'on'
        form['field.bugtracker'] = 'malone'
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertTrue(self.product.enable_bug_expiration)

    def test_enable_bug_expiration_with_external_bug_tracker(self):
        # Verify that enable_bug_expiration is forced to False when the
        # bug tracker is external.
        form = self._makeForm()
        form['field.enable_bug_expiration'] = 'on'
        form['field.bugtracker'] = 'external'
        form['field.bugtracker.bugtracker'] = 'debbugs'
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertFalse(self.product.enable_bug_expiration)

    def test_enable_bug_expiration_with_no_bug_tracker(self):
        # Verify that enable_bug_expiration is forced to False when the
        # bug tracker is unknown.
        form = self._makeForm()
        form['field.enable_bug_expiration'] = 'on'
        form['field.bugtracker'] = 'project'
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertFalse(self.product.enable_bug_expiration)

    def test_bug_role_non_admin_can_edit(self):
        # Verify that a member of an owning team who is not an admin of
        # the bug supervisor team or security_contact team can change bug
        # reporting guidelines.
        owning_team = self.factory.makeTeam(
            owner=self.owner,
            membership_policy=TeamMembershipPolicy.RESTRICTED)
        bug_team = self.factory.makeTeam(
            owner=self.owner,
            membership_policy=TeamMembershipPolicy.RESTRICTED)
        weak_owner = self.factory.makePerson()
        login_person(self.owner)
        owning_team.addMember(weak_owner, self.owner)
        bug_team.addMember(weak_owner, self.owner)
        self.product.owner = owning_team
        self.product.setBugSupervisor(bug_team, self.owner)
        self.product.security_contact = bug_team
        login_person(weak_owner)
        form = self._makeForm()
        # Only the bug_reporting_guidelines are different.
        form['field.bug_supervisor'] = bug_team.name
        form['field.security_contact'] = bug_team.name
        form['field.bug_reporting_guidelines'] = 'new guidelines'
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertEqual(
            'new guidelines', self.product.bug_reporting_guidelines)

    def test_bug_supervisor_can_edit(self):
        login_person(self.bug_supervisor)
        form = self._makeForm()
        # Only the bug_reporting_guidelines are different.
        form['field.bug_reporting_guidelines'] = 'new guidelines'
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertEqual(
            'new guidelines', self.product.bug_reporting_guidelines)

    def test_commercial_subscriber_can_turn_on_private_bugs(self):
        # Verify commercial subscribers can set private_bugs to on.
        form = self._makeForm()
        self.factory.makeCommercialSubscription(self.product)
        form['field.private_bugs'] = 'on'
        login_person(self.bug_supervisor)
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertTrue(self.product.private_bugs)

    def test_expired_commercial_subscriber_cannot_turn_on_private_bugs(self):
        # Verify expired commercial subscribers cannot set private_bugs to on.
        form = self._makeForm()
        self.factory.makeCommercialSubscription(self.product, expired=True)
        form['field.private_bugs'] = 'on'
        login_person(self.bug_supervisor)
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual(
            [u'A valid commercial subscription is required to turn on '
             u'default private bugs.'],
            view.errors)

    def test_unauthorised_cannot_turn_on_private_bugs(self):
        # Verify unauthorised users cannot set private_bugs to on.
        form = self._makeForm()
        form['field.private_bugs'] = 'on'
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual(
            [u'A valid commercial subscription is required to turn on '
             u'default private bugs.'],
            view.errors)

    def test_unauthorised_cannot_turn_off_private_bugs(self):
        # Verify unauthorised user cannot set private_bugs off.
        registry_expert = self.factory.makeRegistryExpert()
        self.product.setPrivateBugs(True, registry_expert)
        anyperson = self.factory.makePerson()
        login_person(anyperson)
        form = self._makeForm()
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual(
            [u'Only bug supervisors can turn off default private bugs.'],
            view.errors)

    def test_bug_supervisor_can_turn_off_private_bugs(self):
        # Verify the bug supervisor can always set private_bugs off.
        registry_expert = self.factory.makeRegistryExpert()
        self.product.setPrivateBugs(True, registry_expert)
        form = self._makeForm()
        login_person(self.bug_supervisor)
        view = create_initialized_view(
            self.product, name='+configure-bugtracker', form=form)
        self.assertEqual([], view.errors)
        self.assertFalse(self.product.private_bugs)
