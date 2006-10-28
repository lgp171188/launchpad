# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Test the ticket workflow methods.

Comprehensive tests for the ticket workflow methods. A narrative kind of
documentation is done in the ../../doc/support-tracker-workflow.txt Doctest,
but testing all the possible transitions makes the documentation more heavy
than necessary. This is tested here.
"""

__metaclass__ = type

__all__ = []

from datetime import datetime, timedelta
from pytz import UTC
import unittest
import traceback

from zope.component import getUtility
from zope.interface.verify import verifyObject
from zope.security.interfaces import Unauthorized

from canonical.launchpad.event.interfaces import (
    ISQLObjectCreatedEvent, ISQLObjectModifiedEvent)
from canonical.launchpad.interfaces import (
    IDistributionSet, ILaunchBag, InvalidTicketStateError, IPersonSet,
    ITicket, ITicketMessage)
from canonical.launchpad.ftests import login, ANONYMOUS
from canonical.launchpad.ftests.event import TestEventListener
from canonical.lp.dbschema import TicketAction, TicketStatus
from canonical.testing.layers import LaunchpadFunctionalLayer


class BaseSupportTrackerWorkflowTestCase(unittest.TestCase):
    """Base class for test cases related to the support tracker workflow.

    It provides the common fixture and test helper methods.
    """

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        self.now = datetime.now(UTC)

        # Login as the ticket owner.
        login('no-priv@canonical.com')

        # Set up actors.
        personset = getUtility(IPersonSet)
        # User who submits request.
        self.owner = personset.getByEmail('no-priv@canonical.com')
        # User who answers request.
        self.answerer = personset.getByEmail('test@canonical.com')

        # Admin user which can change ticket status.
        self.admin = personset.getByEmail('foo.bar@canonical.com')

        # Simple ubuntu ticket.
        self.ubuntu = getUtility(IDistributionSet).getByName('ubuntu')

        self.ticket = self.ubuntu.newTicket(
            self.owner, 'Help!', 'I need help with Ubuntu',
            datecreated=self.now)

    def tearDown(self):
        if hasattr(self, 'created_event_listener'):
            self.created_event_listener.unregister()
            self.modified_event_listener.unregister()

    def setTicketStatus(self, ticket, new_status, comment="Status change."):
        """Utility metho to change a ticket status.

        This logs in as admin, change the status and log back as
        the previous user.
        """
        old_user = getUtility(ILaunchBag).user
        login(self.admin.preferredemail.email)
        ticket.setStatus(self.admin, new_status, comment)
        login(old_user.preferredemail.email)

    def setUpEventListeners(self):
        """Install a listener for events emitted during the test."""
        self.collected_events = []
        if hasattr(self, 'modified_event_listener'):
            # Event listeners is already registered.
            return
        self.modified_event_listener = TestEventListener(
            ITicket, ISQLObjectModifiedEvent, self.collectEvent)
        self.created_event_listener = TestEventListener(
            ITicketMessage, ISQLObjectCreatedEvent, self.collectEvent)

    def collectEvent(self, object, event):
        """Collect events"""
        self.collected_events.append(event)

    def nowPlus(self, n_hours):
        """Return a DateTime a number of hours in the future."""
        return self.now + timedelta(hours=n_hours)

    def _testTransitionGuard(self, guard_name, statuses_expected_true):
        """Helper for transition guard tests.

        Helper that verifies that the Ticket guard_name attribute
        is True when the ticket status is one listed in statuses_expected_true
        and False otherwise.
        """
        for status in TicketStatus.items:
            if status != self.ticket.status:
                self.setTicketStatus(self.ticket, status)
            expected = status.name in statuses_expected_true
            allowed = getattr(self.ticket, guard_name)
            self.failUnless(
                expected == allowed, "%s != %s when status = %s" % (
                    guard_name, expected, status.name))

    def _testValidTransition(self, statuses, transition_method,
                            expected_owner, expected_action, expected_status,
                            extra_message_check=None,
                            transition_method_args=(),
                            transition_method_kwargs=None,
                            edited_fields=None):
        """Helper for testing valid state transitions.

        Helper that verifies that transition_method can be called when
        the ticket status is one listed in statuses. It will validate the
        returned message using checkTransitionMessage(). The transition_method
        is called with the transition_method_args as positional parameters
        and transition_method_kwargs as keyword parameters.

        If extra_message_check is passed a function, it will be called with
        the returned message for extra checks.

        The datecreated parameter to the transition_method is set
        automatically to a value that will make the message sort last.

        The edited_fields parameter contain the list of field that
        are expected to be present in ISQLObjectModifiedEvent that should
        be triggered.
        """
        self.setUpEventListeners()
        count=0
        if transition_method_kwargs is None:
            transition_method_kwargs = {}
        if 'datecreated' not in transition_method_kwargs:
            transition_method_kwargs['datecreated'] = self.nowPlus(0)
        for status in statuses:
            if status != self.ticket.status:
                self.setTicketStatus(self.ticket, status)

            self.collected_events = []

            # Ensure ordering of the message.
            transition_method_kwargs['datecreated'] = (
                transition_method_kwargs['datecreated'] + timedelta(hours=1))
            message = transition_method(*transition_method_args,
                                        **transition_method_kwargs)
            try:
                self.checkTransitionMessage(
                    message, expected_owner=expected_owner,
                    expected_action=expected_action,
                    expected_status=expected_status)
                if extra_message_check:
                    extra_message_check(message)
            except AssertionError:
                # We capture and re-raise the error here to display a nice
                # message explaining in which state the transition failed.
                raise AssertionError(
                    "Failure in validating message when status=%s:\n%s" % (
                        status.name, traceback.format_exc(1)))
            self.checkTransitionEvents(
                message, edited_fields, status_name=status.name)
            count += 1

    def _testInvalidTransition(self, valid_statuses, transition_method,
                               *args, **kwargs):
        """Helper for testing invalid transitions.

        Helper that verifies that transition_method method cannot be
        called when the ticket status is different than the ones in
        valid_statuses.

        args and kwargs contains the parameters that should be passed to the
        transition method.
        """
        for status in TicketStatus.items:
            if status.name in valid_statuses:
                continue
            exceptionRaised = False
            try:
                if status != self.ticket.status:
                    self.setTicketStatus(self.ticket, status)
                transition_method(*args, **kwargs)
            except InvalidTicketStateError:
                exceptionRaised = True
            self.failUnless(exceptionRaised,
                            "%s() when status = %s should raise an error" % (
                                transition_method.__name__, status.name))

    def checkTransitionMessage(self, message, expected_owner,
                               expected_action, expected_status):
        """Helper method to check the message created by a transition.

        It make sure that the message provides ITicketMessage and that it
        was appended to the ticket messages attribute. It also checks that
        the subject was computed correctly and that the new_status, action
        and owner attributes were set correctly.

        It also verifies that the ticket status, datelastquery (or
        datelastresponse) were updated to reflect the time of the message.
        """
        self.failUnless(verifyObject(ITicketMessage, message))

        self.assertEquals("Re: Help!", message.subject)
        self.assertEquals(expected_owner, message.owner)
        self.assertEquals(expected_action, message.action)
        self.assertEquals(expected_status, message.new_status)

        self.assertEquals(message, self.ticket.messages[-1])
        self.assertEquals(expected_status, self.ticket.status)

        if expected_owner == self.ticket.owner:
            self.assertEquals(message.datecreated, self.ticket.datelastquery)
        else:
            self.assertEquals(
                message.datecreated, self.ticket.datelastresponse)

    def checkTransitionEvents(self, message, edited_fields, status_name):
        """Helper method to validate the events triggered from the transition.

        Check that an ISQLObjectCreatedEvent event was sent when the message
        was created and that an ISQLObjectModifiedEvent was also sent.
        The event object and edited_fields attribute are checked.
        """
        def failure_msg(msg):
            return "From status %s: %s" % (status_name, msg)
        self.failUnless(
            len(self.collected_events) >= 1,
            failure_msg('failed to trigger an ISQLObjectCreatedEvent'))
        created_event = self.collected_events[0]
        self.failUnless(
            ISQLObjectCreatedEvent.providedBy(created_event),
            failure_msg(
                "%s doesn't provide ISQLObjectCreatedEvent" % created_event))
        self.failUnless(
            created_event.object == message,
            failure_msg("ISQLObjectCreatedEvent contains wrong message"))
        self.failUnless(
            created_event.user == message.owner,
            failure_msg("%s != %s" % (
                created_event.user.displayname, message.owner.displayname)))

        self.failUnless(
            len(self.collected_events) == 2,
            failure_msg('failed to trigger an ISQLObjectModifiedEvent'))
        modified_event = self.collected_events[1]
        self.failUnless(
            ISQLObjectModifiedEvent.providedBy(modified_event),
            failure_msg(
                "%s doesn't provide ISQLObjectModifiedEvent" % modified_event))
        self.failUnless(
            modified_event.object == self.ticket,
            failure_msg("ISQLObjectModifiedEvent contains wrong ticket"))
        self.failUnless(
            modified_event.user == message.owner,
            failure_msg("%s != %s" % (
                modified_event.user.displayname, message.owner.displayname)))
        if edited_fields:
            self.failUnless(
                set(modified_event.edited_fields) == set(edited_fields),
                failure_msg("%s != %s" % (
                    set(modified_event.edited_fields), set(edited_fields))))


class MiscSupportTrackerWorkflowTestCase(BaseSupportTrackerWorkflowTestCase):
    """Various other test cases for the support tracker workflow."""

    def testDisallowNoOpSetStatus(self):
        """Test that calling setStatus to change to the same status
        raises an InvalidTicketStateError.
        """
        login('foo.bar@canonical.com')
        self.assertRaises(InvalidTicketStateError, self.ticket.setStatus,
                self.admin, TicketStatus.OPEN, 'Status Change')


class RequestInfoTestCase(BaseSupportTrackerWorkflowTestCase):
    """Test cases for the requestInfo() workflow action method."""

    def test_can_request_info(self):
        """Test the can_request_info attribute in all the possible states."""
        self._testTransitionGuard(
            'can_request_info', ['OPEN', 'NEEDSINFO', 'ANSWERED'])

    def test_requestInfo(self):
        """Test that requestInfo() can be called in the OPEN, NEEDSINFO,
        and ANSWERED state and that it returns a valid ITicketMessage.
        """
        # Do no check the edited_fields attribute since it varies depending
        # on the departure state.
        self._testValidTransition(
            [TicketStatus.OPEN, TicketStatus.NEEDSINFO],
            expected_owner=self.answerer,
            expected_action=TicketAction.REQUESTINFO,
            expected_status=TicketStatus.NEEDSINFO,
            transition_method=self.ticket.requestInfo,
            transition_method_args=(
                self.answerer, "What's your problem?"),
            edited_fields=None)

        # Even if the ticket is answered, a user can request more
        # information, but that leave the ticket in the ANSWERED state.
        self.setTicketStatus(self.ticket, TicketStatus.ANSWERED)
        self.collected_events = []
        message = self.ticket.requestInfo(
            self.answerer,
            "The previous answer is bad. What is the problem again?",
            datecreated=self.nowPlus(3))
        self.checkTransitionMessage(
            message, expected_owner=self.answerer,
            expected_action=TicketAction.REQUESTINFO,
            expected_status=TicketStatus.ANSWERED)
        self.checkTransitionEvents(
            message, ['messages', 'datelastresponse'], TicketStatus.OPEN.title)

    def test_requestInfoFromOwnerIsInvalid(self):
        """Test that the ticket owner cannot use requestInfo."""
        self.assertRaises(
            AssertionError, self.ticket.requestInfo,
                self.owner, 'Why should I care?', datecreated=self.nowPlus(1))

    def test_requestInfoFromInvalidStates(self):
        """Test that requestInfo cannot be called when the ticket status is
        not OPEN, NEEDSINFO, or ANSWERED.
        """
        self._testInvalidTransition(
            ['OPEN', 'NEEDSINFO', 'ANSWERED'], self.ticket.requestInfo,
            self.answerer, "What's up?", datecreated=self.nowPlus(3))

    def test_requestInfoPermission(self):
        """Test that only a logged in user can access requestInfo()."""
        login(ANONYMOUS)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'requestInfo')

        login(self.answerer.preferredemail.email)
        getattr(self.ticket, 'requestInfo')


class GiveInfoTestCase(BaseSupportTrackerWorkflowTestCase):
    """Test cases for the giveInfo() workflow action method."""

    def test_can_give_info(self):
        """Test the can_give_info attribute in all the possible states."""
        self._testTransitionGuard('can_give_info', ['OPEN', 'NEEDSINFO'])

    def test_giveInfoFromInvalidStates(self):
        """Test that giveInfo cannot be called when the ticket status is
        not OPEN or NEEDSINFO.
        """
        self._testInvalidTransition(
            ['OPEN', 'NEEDSINFO'], self.ticket.giveInfo,
            "That's that.", datecreated=self.nowPlus(1))

    def test_giveInfo(self):
        """Test that giveInfo() can be called when the ticket status is
        OPEN or NEEDSINFO and that it returns a valid ITicketMessage.
        """
        # Do not check the edited_fields attributes since it
        # changes based on departure state.
        self._testValidTransition(
            [TicketStatus.OPEN, TicketStatus.NEEDSINFO],
            expected_owner=self.owner,
            expected_action=TicketAction.GIVEINFO,
            expected_status=TicketStatus.OPEN,
            transition_method=self.ticket.giveInfo,
            transition_method_args=("That's that.",),
            edited_fields=None)

    def test_giveInfoPermission(self):
        """Test that only the owner can access giveInfo()."""
        login(ANONYMOUS)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'giveInfo')
        login(self.answerer.preferredemail.email)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'giveInfo')
        login(self.admin.preferredemail.email)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'giveInfo')

        login(self.owner.preferredemail.email)
        getattr(self.ticket, 'giveInfo')


class GiveAnswerTestCase(BaseSupportTrackerWorkflowTestCase):
    """Test cases for the giveAnswer() workflow action method."""

    def test_can_give_answer(self):
        """Test the can_give_answer attribute in all the possible states."""
        self._testTransitionGuard(
            'can_give_answer', ['OPEN', 'NEEDSINFO', 'ANSWERED'])

    def test_giveAnswerFromInvalidStates(self):
        """Test that giveAnswer cannot be called when the ticket status is
        not OPEN, NEEDSINFO, or ANSWERED.
        """
        self._testInvalidTransition(
            ['OPEN', 'NEEDSINFO', 'ANSWERED'], self.ticket.giveAnswer,
            self.answerer, "The answer is this.", datecreated=self.nowPlus(1))

    def test_giveAnswer(self):
        """Test that giveAnswer can be called when the ticket status is
        one of OPEN, NEEDSINFO or ANSWERED and check that it returns a
        valid ITicketMessage.
        """
        # Do not check the edited_fields attributes since it
        # changes based on departure state.
        self._testValidTransition(
            [TicketStatus.OPEN, TicketStatus.NEEDSINFO,
             TicketStatus.ANSWERED],
            expected_owner=self.answerer,
            expected_action=TicketAction.ANSWER,
            expected_status=TicketStatus.ANSWERED,
            transition_method=self.ticket.giveAnswer,
            transition_method_args=(
                self.answerer, "It looks like a real problem.",),
            edited_fields=None)

        # When the owner gives the answer, the ticket moves straight to
        # SOLVED.
        def checkAnswerMessage(message):
            """Check additional attributes set when the owner gives the
            answers.
            """
            self.assertEquals(message, self.ticket.answer)
            self.assertEquals(self.owner, self.ticket.answerer)
            self.assertEquals(message.datecreated, self.ticket.dateanswered)

        self._testValidTransition(
            [TicketStatus.OPEN, TicketStatus.NEEDSINFO,
             TicketStatus.ANSWERED],
            expected_owner=self.owner,
            expected_action=TicketAction.CONFIRM,
            expected_status=TicketStatus.SOLVED,
            extra_message_check=checkAnswerMessage,
            transition_method=self.ticket.giveAnswer,
            transition_method_args=(
                self.owner, "I found the solution.",),
            transition_method_kwargs={'datecreated': self.nowPlus(3)},
            edited_fields=['status', 'messages', 'dateanswered', 'answerer',
                           'answer', 'datelastquery'])

    def test_giveAnswerPermission(self):
        """Test that only a logged in user can access giveAnswer()."""
        login(ANONYMOUS)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'giveAnswer')

        login(self.answerer.preferredemail.email)
        getattr(self.ticket, 'giveAnswer')


class ConfirmAnswerTestCase(BaseSupportTrackerWorkflowTestCase):
    """Test cases for the confirmAnswer() workflow action method."""

    def test_can_confirm_answer_without_answer(self):
        """Test the can_confirm_answer attribute when no answer was posted.

        When the ticket didn't receive an answer, it should always be
        false.
        """
        self._testTransitionGuard('can_confirm_answer', [])

    def test_can_confirm_answer_with_answer(self):
        """Test that can_confirm_answer when there is an answer present.

        Once one answer was given, it becomes possible in some states.
        """
        self.ticket.giveAnswer(
            self.answerer, 'Do something about it.', self.nowPlus(1))
        self._testTransitionGuard(
            'can_confirm_answer', ['OPEN', 'NEEDSINFO', 'ANSWERED'])

    def test_confirmAnswerFromInvalidStates_without_answer(self):
        """Test calling confirmAnswer from invalid states.

        confirmAnswer() cannot be called when the ticket has no message with
        action ANSWER.
        """
        self._testInvalidTransition([], self.ticket.confirmAnswer,
            "That answer worked!.", datecreated=self.nowPlus(1))

    def test_confirmAnswerFromInvalidStates_with_answer(self):
        """ Test calling confirmAnswer from invalid states with an answer.

        When the ticket has a message with action ANSWER, confirmAnswer()
        can only be called when it is in the OPEN, NEEDSINFO, or ANSWERED
        state.
        """
        answer_message = self.ticket.giveAnswer(
            self.answerer, 'Do something about it.', self.nowPlus(1))
        self._testInvalidTransition(['OPEN', 'NEEDSINFO', 'ANSWERED'],
            self.ticket.confirmAnswer, "That answer worked!.",
            answer=answer_message, datecreated=self.nowPlus(1))

    def test_confirmAnswer(self):
        """Test confirmAnswer().

        Test that confirmAnswer() can be called when the ticket status
        is one of OPEN, NEEDSINFO, ANSWERED and that it has at least one
        ANSWER message and check that it returns a valid ITicketMessage.
        """
        answer_message = self.ticket.giveAnswer(
            self.answerer, "Get a grip!", datecreated=self.nowPlus(1))

        def checkAnswerMessage(message):
            # Check the attributes that are set when an answer is confirmed.
            self.assertEquals(answer_message, self.ticket.answer)
            self.assertEquals(self.answerer, self.ticket.answerer)
            self.assertEquals(message.datecreated, self.ticket.dateanswered)

        self._testValidTransition(
            [TicketStatus.OPEN, TicketStatus.NEEDSINFO,
             TicketStatus.ANSWERED],
            expected_owner=self.owner,
            expected_action=TicketAction.CONFIRM,
            expected_status=TicketStatus.SOLVED,
            extra_message_check=checkAnswerMessage,
            transition_method=self.ticket.confirmAnswer,
            transition_method_args=("That was very useful.",),
            transition_method_kwargs={'answer': answer_message,
                                      'datecreated' : self.nowPlus(2)},
            edited_fields=['status', 'messages', 'dateanswered', 'answerer',
                           'answer', 'datelastquery'])

    def testCannotConfirmAnAnswerFromAnotherTicket(self):
        """Test that you can't confirm an answer not from the same ticket."""
        ticket1_answer = self.ticket.giveAnswer(
            self.answerer, 'Really, just do it!')
        ticket2 = self.ubuntu.newTicket(self.owner, 'Help 2', 'Help me!')
        ticket2_answer = ticket2.giveAnswer(self.answerer, 'Do that!')
        answerRefused = False
        try:
            ticket2.confirmAnswer('That worked!', answer=ticket1_answer)
        except AssertionError:
            answerRefused = True
        self.failUnless(
            answerRefused, 'confirmAnswer accepted a message from a different'
            'ticket')

    def test_confirmAnswerPermission(self):
        """Test that only the owner can access confirmAnswer()."""
        login(ANONYMOUS)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'confirmAnswer')
        login(self.answerer.preferredemail.email)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'confirmAnswer')
        login(self.admin.preferredemail.email)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'confirmAnswer')

        login(self.owner.preferredemail.email)
        getattr(self.ticket, 'confirmAnswer')


class ReopenTestCase(BaseSupportTrackerWorkflowTestCase):
    """Test cases for the reopen() workflow action method."""

    def test_can_reopen(self):
        """Test the can_reopen attribute in all the possible states."""
        self._testTransitionGuard(
            'can_reopen', ['ANSWERED', 'EXPIRED', 'SOLVED'])

    def test_reopenFromInvalidStates(self):
        """Test that reopen cannot be called when the ticket status is
        not one of OPEN, NEEDSINFO, or ANSWERED.
        """
        self._testInvalidTransition(
            ['ANSWERED', 'EXPIRED', 'SOLVED'], self.ticket.reopen,
            "I still have a problem.", datecreated=self.nowPlus(1))

    def test_reopen(self):
        """Test that reopen() can be called when the ticket is in the
        ANSWERED and EXPIRED state and that it returns a valid
        ITicketMessage.
        """
        self._testValidTransition(
            [TicketStatus.ANSWERED, TicketStatus.EXPIRED],
            expected_owner=self.owner,
            expected_action=TicketAction.REOPEN,
            expected_status=TicketStatus.OPEN,
            transition_method=self.ticket.reopen,
            transition_method_args=('I still have this problem.',),
            edited_fields=['status', 'messages', 'datelastquery'])

    def test_reopenFromSOLVED(self):
        """Test that reopen() can be called when the ticket is in the
        SOLVED state and that it returns an appropriate ITicketMessage.
        This transition should also clear the dateanswered, answered and
        answerer attributes.
        """
        self.setUpEventListeners()
        # Mark the ticket as solved by the user.
        self.ticket.giveAnswer(
            self.owner, 'I solved my own problem.',
            datecreated=self.nowPlus(0))
        self.assertEquals(self.ticket.status, TicketStatus.SOLVED)

        # Clear previous events.
        self.collected_events = []

        message = self.ticket.reopen(
            "My solution doesn't work.", datecreated=self.nowPlus(1))
        self.checkTransitionMessage(
            message, expected_owner=self.owner,
            expected_action=TicketAction.REOPEN,
            expected_status=TicketStatus.OPEN)
        self.checkTransitionEvents(
            message, ['status', 'messages', 'answerer', 'answer',
                      'dateanswered', 'datelastquery'],
            TicketStatus.OPEN.title)

    def test_reopenPermission(self):
        """Test that only the owner can access reopen()."""
        login(ANONYMOUS)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'reopen')
        login(self.answerer.preferredemail.email)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'reopen')
        login(self.admin.preferredemail.email)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'reopen')

        login(self.owner.preferredemail.email)
        getattr(self.ticket, 'reopen')


class ExpireTicketTestCase(BaseSupportTrackerWorkflowTestCase):
    """Test cases for the expireTicket() workflow action method."""

    def test_expireTicketFromInvalidStates(self):
        """Test that expireTicket cannot be called when the ticket status is
        not one of OPEN or NEEDSINFO.
        """
        self._testInvalidTransition(
            ['OPEN', 'NEEDSINFO'], self.ticket.expireTicket,
            self.answerer, "Too late.", datecreated=self.nowPlus(1))

    def test_expireTicket(self):
        """Test that expireTicket() can be called when the ticket status is
        OPEN or NEEDSINFO and that it returns a valid ITicketMessage.
        """
        self._testValidTransition(
            [TicketStatus.OPEN, TicketStatus.NEEDSINFO],
            expected_owner=self.answerer,
            expected_action=TicketAction.EXPIRE,
            expected_status=TicketStatus.EXPIRED,
            transition_method=self.ticket.expireTicket,
            transition_method_args=(
                self.answerer, 'This ticket is expired.'),
            edited_fields=['status', 'messages', 'datelastresponse'])

    def test_expireTicketPermission(self):
        """Test that only a logged in user can access expireTicket()."""
        login(ANONYMOUS)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'expireTicket')

        login(self.answerer.preferredemail.email)
        getattr(self.ticket, 'expireTicket')


class RejectTestCase(BaseSupportTrackerWorkflowTestCase):
    """Test cases for the reject() workflow action method."""

    def test_rejectFromInvalidStates(self):
        """Test that expireTicket cannot be called when the ticket status is
        not one of OPEN or NEEDSINFO.
        """
        valid_statuses = [status.name for status in TicketStatus.items
                          if status.name != 'INVALID']
        # Reject user must be a support contact, (or admin, or product owner).
        self.ubuntu.addSupportContact(self.answerer)
        login(self.answerer.preferredemail.email)
        self._testInvalidTransition(
            valid_statuses, self.ticket.reject,
            self.answerer, "This is lame.", datecreated=self.nowPlus(1))

    def test_reject(self):
        """Test that expireTicket() can be called when the ticket status is
        OPEN or NEEDSINFO and that it returns a valid ITicketMessage.
        """
        # Reject user must be a support contact, (or admin, or product owner).
        login(self.answerer.preferredemail.email)
        self.ubuntu.addSupportContact(self.answerer)
        valid_statuses = [status for status in TicketStatus.items
                          if status.name != 'INVALID']

        def checkRejectMessageIsAnAnswer(message):
            # Check that the rejection message was considered answering
            # the ticket.
            self.assertEquals(message, self.ticket.answer)
            self.assertEquals(self.answerer, self.ticket.answerer)
            self.assertEquals(message.datecreated, self.ticket.dateanswered)

        self._testValidTransition(
            valid_statuses,
            expected_owner=self.answerer,
            expected_action=TicketAction.REJECT,
            expected_status=TicketStatus.INVALID,
            extra_message_check=checkRejectMessageIsAnAnswer,
            transition_method=self.ticket.reject,
            transition_method_args=(
                self.answerer, 'This is lame.'),
            edited_fields=['status', 'messages', 'answerer', 'dateanswered',
                           'answer', 'datelastresponse'])

    def testRejectPermission(self):
        """Test the reject() access control.

        Only a support contacts and administrator can reject a ticket.
        """
        login(ANONYMOUS)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'reject')

        login(self.owner.preferredemail.email)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'reject')

        login(self.answerer.preferredemail.email)
        self.assertRaises(Unauthorized, getattr, self.ticket, 'reject')

        self.ticket.target.addSupportContact(self.answerer)
        getattr(self.ticket, 'reject')

        login(self.admin.preferredemail.email)
        getattr(self.ticket, 'reject')


def test_suite():
    import canonical.launchpad.interfaces.ftests as ftests
    return unittest.findTestCases(ftests.test_ticket_workflow)


if __name__ == '__main__':
    unittest.main()
