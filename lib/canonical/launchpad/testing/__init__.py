# Copyright 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0401,C0301

import unittest

import zope.event
from zope.security.proxy import (
    isinstance as zope_isinstance, removeSecurityProxy)

from canonical.database.sqlbase import sqlvalues
# Import the login and logout functions here as it is a much better
# place to import them from in tests.
from canonical.launchpad.ftests import ANONYMOUS, login, login_person, logout
from canonical.launchpad.testing.factory import *


class TestCase(unittest.TestCase):
    """Provide Launchpad-specific test facilities."""

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        self._cleanups = []
        # Python 2.4 shenanigans. These are both implemented by unittest with
        # double underscores in Python 2.4. There are no direct
        # implementations of these methods in this class. We use the double
        # underscore syntax without expansion because this class has the same
        # __name__ as its base class. In Python 2.5 these elements have single
        # underscores.
        self._testMethodName = self.__testMethodName
        self._exc_info = self.__exc_info

    def _runCleanups(self, result):
        """Run the cleanups that have been added with addCleanup.

        See the docstring for addCleanup for more information.

        Returns True if all cleanups ran without error, False otherwise.
        """
        ok = True
        while self._cleanups:
            function, arguments, keywordArguments = self._cleanups.pop()
            try:
                function(*arguments, **keywordArguments)
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self._exc_info())
                ok = False
        return ok

    def addCleanup(self, function, *arguments, **keywordArguments):
        """Add a cleanup function to be called before tearDown.

        Functions added with addCleanup will be called in reverse order of
        adding after the test method and before tearDown.

        If a function added with addCleanup raises an exception, the error
        will be recorded as a test error, and the next cleanup will then be
        run.

        Cleanup functions are always called before a test finishes running,
        even if setUp is aborted by an exception.
        """
        self._cleanups.append((function, arguments, keywordArguments))

    def assertNotifies(self, event_type, callable_obj, *args, **kwargs):
        """Assert that a callable performs a given notification.

        :param event_type: The type of event that notification is expected
            for.
        :param callable_obj: The callable to call.
        :param *args: The arguments to pass to the callable.
        :param **kwargs: The keyword arguments to pass to the callable.
        :return: (result, event), where result was the return value of the
            callable, and event is the event emitted by the callable.
        """
        result, events = capture_events(callable_obj, *args, **kwargs)
        if len(events) == 0:
            raise AssertionError('No notification was performed.')
        elif len(events) > 1:
            raise AssertionError('Too many (%d) notifications performed.'
                % len(events))
        elif not isinstance(events[0], event_type):
            raise AssertionError('Wrong event type: %r (expected %r).' %
                (events[0], event_type))
        return result, events[0]

    def assertSqlAttributeEqualsDate(self, sql_object, attribute_name, date):
        """Fail unless the value of the attribute is equal to the date.

        Use this method to test that date value that may be UTC_NOW is equal
        to another date value. Trickery is required because SQLBuilder truth
        semantics cause UTC_NOW to appear equal to all dates.

        :param sql_object: a security-proxied SQLObject instance.
        :param attribute_name: the name of a database column in the table
            associated to this object.
        :param date: `datetime.datetime` object or `UTC_NOW`.
        """
        # XXX: Aaron Bentley 2008-04-14: Probably does not belong here, but
        # better location not clear. Used primarily for testing ORM objects,
        # which ought to use factory.
        sql_object = removeSecurityProxy(sql_object)
        sql_object.syncUpdate()
        sql_class = type(sql_object)
        found_object = sql_class.selectOne(
            ('id=%s AND ' + attribute_name + '=%s')
            % sqlvalues(sql_object.id, date))
        if found_object is None:
            self.fail(
                "Expected %s to be %s, but it was %s."
                % (attribute_name, date, getattr(sql_object, attribute_name)))

    def assertIsInstance(self, instance, assert_class):
        """Assert that an instance is an instance of assert_class.

        instance and assert_class have the same semantics as the parameters
        to isinstance.
        """
        self.assertTrue(zope_isinstance(instance, assert_class),
            '%r is not an instance of %r' % (instance, assert_class))

    def assertIs(self, expected, observed):
        """Assert that `expected` is the same object as `observed`."""
        self.assertTrue(expected is observed,
                        "%r is not %r" % (expected, observed))

    def assertIsNot(self, expected, observed):
        """Assert that `expected` is not the same object as `observed`."""
        self.assertTrue(expected is not observed,
                        "%r is %r" % (expected, observed))

    def assertIn(self, needle, haystack):
        """Assert that 'needle' is in 'haystack'."""
        self.assertTrue(
            needle in haystack, '%r not in %r' % (needle, haystack))

    def assertNotIn(self, needle, haystack):
        """Assert that 'needle' is not in 'haystack'."""
        self.assertFalse(
            needle in haystack, '%r in %r' % (needle, haystack))

    def run(self, result=None):
        if result is None:
            result = self.defaultTestResult()
        result.startTest(self)
        testMethod = getattr(self, self._testMethodName)
        try:
            try:
                self.setUp()
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self._exc_info())
                self._runCleanups(result)
                return

            ok = False
            try:
                testMethod()
                ok = True
            except self.failureException:
                result.addFailure(self, self._exc_info())
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self._exc_info())

            cleanupsOk = self._runCleanups(result)
            try:
                self.tearDown()
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self._exc_info())
                ok = False
            if ok and cleanupsOk:
                result.addSuccess(self)
        finally:
            result.stopTest(self)


class TestCaseWithFactory(TestCase):

    def setUp(self, user=ANONYMOUS):
        login(user)
        self.factory = LaunchpadObjectFactory()

    def tearDown(self):
        logout()

    def getUserBrowser(self, url=None):
        """Return a Browser logged in as a fresh user, maybe opened at `url`.
        """
        # Do the import here to avoid issues with import cycles.
        from canonical.launchpad.testing.pages import setupBrowser
        login(ANONYMOUS)
        user = self.factory.makePerson(password='test')
        naked_user = removeSecurityProxy(user)
        email = naked_user.preferredemail.email
        logout()
        browser = setupBrowser(
            auth="Basic %s:test" % str(email))
        if url is not None:
            browser.open(url)
        return browser


def capture_events(callable_obj, *args, **kwargs):
    """Capture the events emitted by a callable.

    :param event_type: The type of event that notification is expected
        for.
    :param callable_obj: The callable to call.
    :param *args: The arguments to pass to the callable.
    :param **kwargs: The keyword arguments to pass to the callable.
    :return: (result, events), where result was the return value of the
        callable, and events are the events emitted by the callable.
    """
    events = []
    def on_notify(event):
        events.append(event)
    old_subscribers = zope.event.subscribers[:]
    try:
        zope.event.subscribers[:] = [on_notify]
        result = callable_obj(*args, **kwargs)
        return result, events
    finally:
        zope.event.subscribers[:] = old_subscribers
