# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Module docstring goes here."""

from datetime import datetime

from testtools.matchers import MatchesListwise, MatchesStructure
from zope.i18n import Message
from zope.interface import implementer
from zope.publisher.browser import TestRequest
from zope.publisher.interfaces.browser import IBrowserRequest
from zope.publisher.interfaces.http import IHTTPApplicationResponse

from lp import _
from lp.services.webapp.escaping import structured
from lp.services.webapp.interfaces import (
    BrowserNotificationLevel,
    INotificationList,
    INotificationRequest,
    INotificationResponse,
    ISession,
    ISessionData,
    IStructuredString,
)
from lp.services.webapp.notifications import (
    SESSION_KEY,
    Notification,
    NotificationList,
    NotificationRequest,
    NotificationResponse,
)
from lp.testing import TestCase
from lp.testing.fixture import ZopeAdapterFixture
from lp.testing.layers import FunctionalLayer


@implementer(ISession)
class MockSession(dict):
    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            self[key] = MockSessionData()
            return super().__getitem__(key)


@implementer(ISessionData)
class MockSessionData(dict):
    def __call__(self, whatever):
        return self


@implementer(IHTTPApplicationResponse)
class MockHTTPApplicationResponse:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redirect_log = []

    def redirect(self, location, status=None, trusted=False):
        """Just log the redirection."""
        if status is None:
            status = 302
        self.redirect_log.append((status, location))


class MyNotificationResponse(
    NotificationResponse, MockHTTPApplicationResponse
):
    pass


def adaptNotificationRequestToResponse(request):
    try:
        return request.response
    except AttributeError:
        response = NotificationResponse()
        request.response = response
        response._request = request
        return response


class TestNotificationsBase:
    def setUp(self):
        super().setUp()

        mock_session = MockSession()
        self.useFixture(
            ZopeAdapterFixture(
                lambda x: mock_session, (INotificationRequest,), ISession
            )
        )
        self.useFixture(
            ZopeAdapterFixture(
                lambda x: mock_session, (INotificationResponse,), ISession
            )
        )
        self.useFixture(
            ZopeAdapterFixture(
                adaptNotificationRequestToResponse,
                (INotificationRequest,),
                INotificationResponse,
            )
        )

        mock_browser_request = TestRequest()
        self.useFixture(
            ZopeAdapterFixture(
                lambda x: mock_browser_request,
                (INotificationRequest,),
                IBrowserRequest,
            )
        )


class TestNotificationRequest(TestNotificationsBase, TestCase):
    layer = FunctionalLayer

    def test_provides_interface(self):
        request = NotificationRequest()
        self.assertTrue(INotificationRequest.providedBy(request))

    def test_no_notifications_by_default(self):
        # By default, there are no notifications.
        request = NotificationRequest()
        self.assertEqual(0, len(request.notifications))

    def test_single_notification(self):
        request = NotificationRequest()
        session = ISession(request)[SESSION_KEY]
        notifications = NotificationList()
        session["notifications"] = notifications
        notifications.append(Notification(0, "Fnord"))
        self.assertThat(
            request.notifications,
            MatchesListwise([MatchesStructure.byEquality(message="Fnord")]),
        )

    def test_multiple_notifications(self):
        # NotificationRequest.notifications also returns any notifications
        # that have been added so far in this request, making it the single
        # source you need to interrogate to display notifications to the
        # user.
        request = NotificationRequest()
        session = ISession(request)[SESSION_KEY]
        notifications = NotificationList()
        session["notifications"] = notifications
        notifications.append(Notification(0, "Fnord"))
        response = INotificationResponse(request)
        response.addNotification("Aargh")
        self.assertThat(
            request.notifications,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(message="Fnord"),
                    MatchesStructure.byEquality(message="Aargh"),
                ]
            ),
        )


class TestNotificationResponse(TestNotificationsBase, TestCase):
    layer = FunctionalLayer

    def test_provides_interface(self):
        response = NotificationResponse()
        self.assertTrue(INotificationResponse.providedBy(response))

    def makeNotificationResponse(self):
        # Return a `NotificationResponse` linked to a `NotificationRequest`.
        response = MyNotificationResponse()
        request = NotificationRequest()
        request.response = response
        response._request = request
        # Full IRequests are zope.security participations, and
        # NotificationResponse.redirect expects a principal, as in the full
        # IRequest interface.
        request.principal = None
        return response

    def test_no_notifications(self):
        response = self.makeNotificationResponse()
        self.assertEqual(0, len(response.notifications))

    def test_addNotification(self):
        response = self.makeNotificationResponse()
        response.addNotification("something")
        self.assertEqual(1, len(response.notifications))

    def test_removeAllNotifications(self):
        response = self.makeNotificationResponse()
        response.addNotification("something")
        response.removeAllNotifications()
        self.assertEqual(0, len(response.notifications))

    def test_many_notifications(self):
        response = self.makeNotificationResponse()
        msg = structured("<b>%(escaped)s</b>", escaped="<Fnord>")
        response.addNotification(msg)
        response.addNotification("Whatever", BrowserNotificationLevel.DEBUG)
        response.addDebugNotification("Debug")
        response.addInfoNotification("Info")
        response.addWarningNotification("Warning")
        # And an odd one to test
        # https://bugs.launchpad.net/launchpad/+bug/54987
        response.addErrorNotification(
            _("Error${value}", mapping={"value": ""})
        )

        self.assertTrue(INotificationList.providedBy(response.notifications))
        self.assertThat(
            response.notifications,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(
                        level=20, message="<b>&lt;Fnord&gt;</b>"
                    ),
                    MatchesStructure.byEquality(level=10, message="Whatever"),
                    MatchesStructure.byEquality(level=10, message="Debug"),
                    MatchesStructure.byEquality(level=20, message="Info"),
                    MatchesStructure.byEquality(level=30, message="Warning"),
                    MatchesStructure.byEquality(level=40, message="Error"),
                ]
            ),
        )

    def test_no_notifications_session_untouched(self):
        # If there are no notifications, the session is not touched.  This
        # ensures that we don't needlessly burden the session storage.
        response = self.makeNotificationResponse()
        session = ISession(response._request)[SESSION_KEY]
        self.assertNotIn("notifications", session)
        self.assertEqual(0, len(response.notifications))
        response.redirect("http://example.com")
        self.assertEqual([(302, "http://example.com")], response.redirect_log)
        self.assertNotIn("notifications", session)


class TestNotificationResponseTextEscaping(TestNotificationsBase, TestCase):
    """Test notification text escaping.

    There are a number of user actions that may generate on-screen
    notifications, such as moving a bug or deleting a branch.  Some of these
    notifications display potentially unsafe text that is obtained from the
    user.  In order to prevent a cross-site-scripting attack, HTML
    characters in notifications must be escaped.  However, there are special
    cases where notifications from known safe sources must be allowed to
    pass HTML through.
    """

    layer = FunctionalLayer

    def makeNotificationResponse(self):
        # Return a `NotificationResponse` linked to a `NotificationRequest`.
        response = MyNotificationResponse()
        request = NotificationRequest()
        request.response = response
        response._request = request
        return response

    def test_addNotification_plain_text(self):
        # Plain text is left unchanged.
        response = self.makeNotificationResponse()
        response.addNotification("clean")
        self.assertThat(
            response.notifications,
            MatchesListwise([MatchesStructure.byEquality(message="clean")]),
        )

    def test_addNotification_html(self):
        # HTML is escaped.
        response = self.makeNotificationResponse()
        response.addNotification("<br/>dirty")
        self.assertThat(
            response.notifications,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(message="&lt;br/&gt;dirty"),
                ]
            ),
        )

    def test_addNotification_structured_string(self):
        # If the object passed to `addNotification` publishes the
        # `IStructuredString` interface, then a string is returned with the
        # appropriate sections escaped and unescaped.
        structured_text = structured("<b>%(escaped)s</b>", escaped="<br/>foo")
        self.assertTrue(IStructuredString.providedBy(structured_text))
        self.assertEqual("<b>&lt;br/&gt;foo</b>", structured_text.escapedtext)
        response = self.makeNotificationResponse()
        response.addNotification(structured_text)
        self.assertThat(
            response.notifications,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(
                        message="<b>&lt;br/&gt;foo</b>"
                    ),
                ]
            ),
        )

    def test_addNotification_i18n_message(self):
        # An instance of `zope.i18n.Message` is escaped in the same manner
        # as raw text.
        response = self.makeNotificationResponse()
        response.addNotification(Message("<br/>foo"))
        self.assertThat(
            response.notifications,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(message="&lt;br/&gt;foo"),
                ]
            ),
        )

    def test_addNotification_structured_internationalized(self):
        # To pass internationalized text that contains markup, one may call
        # `structured` directly with an internationalized object.
        # `structured` performs the translation and substitution, and the
        # resulting object may then be passed to `addNotification`.
        structured_text = structured(_("<good/>%(evil)s"), evil="<evil/>")
        self.assertEqual("<good/>&lt;evil/&gt;", structured_text.escapedtext)
        response = self.makeNotificationResponse()
        response.addNotification(structured_text)
        self.assertThat(
            response.notifications,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(
                        message="<good/>&lt;evil/&gt;"
                    ),
                ]
            ),
        )


class TestNotificationList(TestNotificationsBase, TestCase):
    layer = FunctionalLayer

    def test_empty(self):
        notifications = NotificationList()
        self.assertLessEqual(notifications.created, datetime.utcnow())
        self.assertRaises(IndexError, notifications.__getitem__, 0)

    def test_iterate(self):
        notifications = NotificationList()
        notifications.append(
            Notification(BrowserNotificationLevel.ERROR, "An error")
        )
        notifications.append(
            Notification(BrowserNotificationLevel.DEBUG, "A debug message")
        )
        self.assertThat(
            notifications,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(message="An error"),
                    MatchesStructure.byEquality(message="A debug message"),
                ]
            ),
        )

    def test___getitem__(self):
        # The __getitem__ method is also overloaded to allow TALES
        # expressions to easily retrieve lists of notifications that match a
        # particular notification level.
        notifications = NotificationList()
        notifications.append(
            Notification(BrowserNotificationLevel.ERROR, "An error")
        )
        notifications.append(
            Notification(BrowserNotificationLevel.DEBUG, "A debug message")
        )
        self.assertThat(
            notifications["debug"],
            MatchesListwise(
                [
                    MatchesStructure.byEquality(message="A debug message"),
                ]
            ),
        )
