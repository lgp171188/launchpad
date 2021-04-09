# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Module docstring goes here."""

from __future__ import absolute_import, print_function

__metaclass__ = type

import __future__
from doctest import DocTestSuite
import unittest

from zope.component import provideAdapter
from zope.container.testing import (
    setUp as containerSetUp,
    tearDown as containerTearDown,
    )
from zope.interface import implementer
from zope.publisher.browser import TestRequest
from zope.publisher.interfaces.browser import IBrowserRequest
from zope.publisher.interfaces.http import IHTTPApplicationResponse
from zope.session.interfaces import (
    ISession,
    ISessionData,
    )

from lp.services.webapp.escaping import structured
from lp.services.webapp.interfaces import (
    INotificationRequest,
    INotificationResponse,
    )
from lp.services.webapp.notifications import NotificationResponse


@implementer(ISession)
class MockSession(dict):

    def __getitem__(self, key):
        try:
            return super(MockSession, self).__getitem__(key)
        except KeyError:
            self[key] = MockSessionData()
            return super(MockSession, self).__getitem__(key)


@implementer(ISessionData)
class MockSessionData(dict):

    lastAccessTime = 0

    def __call__(self, whatever):
        return self


@implementer(IHTTPApplicationResponse)
class MockHTTPApplicationResponse:

    def redirect(self, location, status=None, trusted=False):
        """Just report the redirection to the doctest"""
        if status is None:
            status = 302
        print('%d: %s' % (status, location))


def adaptNotificationRequestToResponse(request):
    try:
        return request.response
    except AttributeError:
        response = NotificationResponse()
        request.response = response
        response._request = request
        return response


def setUp(test):
    containerSetUp()
    mock_session = MockSession()
    provideAdapter(lambda x: mock_session, (INotificationRequest,), ISession)
    provideAdapter(lambda x: mock_session, (INotificationResponse,), ISession)
    provideAdapter(
        adaptNotificationRequestToResponse,
        (INotificationRequest,), INotificationResponse)

    mock_browser_request = TestRequest()
    provideAdapter(
        lambda x: mock_browser_request, (INotificationRequest,),
        IBrowserRequest)

    for future_item in 'absolute_import', 'print_function':
        test.globs[future_item] = getattr(__future__, future_item)
    test.globs['MockResponse'] = MockHTTPApplicationResponse
    test.globs['structured'] = structured


def tearDown(test):
    containerTearDown()


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(DocTestSuite(
        'lp.services.webapp.notifications',
        setUp=setUp, tearDown=tearDown,
        ))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
