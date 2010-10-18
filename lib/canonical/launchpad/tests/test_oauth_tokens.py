# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from datetime import (
    datetime,
    timedelta
    )
import pytz

from zope.component import getUtility

from canonical.launchpad.webapp.interfaces import (
    AccessLevel,
    OAuthPermission,
    )
from canonical.launchpad.webapp.testing import verifyObject
from canonical.testing.layers import DatabaseFunctionalLayer

from canonical.launchpad.interfaces.oauth import (
    IOAuthConsumer,
    IOAuthConsumerSet,
    IOAuthRequestToken,
    IOAuthRequestTokenSet,
    )

from lp.testing import (
    TestCaseWithFactory,
    )


class TestConsumerSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestConsumerSet, self).setUp()
        self.consumers = getUtility(IOAuthConsumerSet)

    def test_interface(self):
        verifyObject(IOAuthConsumerSet, self.consumers)

    def test_consumer_management(self):
        key = self.factory.getUniqueString("oauthconsumerkey")

        # We can create a consumer.
        consumer = self.consumers.new(key=key)
        verifyObject(IOAuthConsumer, consumer)

        # We can retrieve the consumer we just created.
        self.assertEqual(self.consumers.getByKey(key), consumer)

        # We can't create another consumer with the same name.
        self.assertRaises(AssertionError, self.consumers.new, key=key)

    def test_get_nonexistent_consumer_returns_none(self):
        nonexistent_key = self.factory.getUniqueString(
            "oauthconsumerkey-nonexistent")
        self.assertEqual(self.consumers.getByKey(nonexistent_key), None)


class TestRequestTokens(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        """Set up a dummy person and OAuth consumer."""
        super(TestRequestTokens, self).setUp()

        self.person = self.factory.makePerson()
        self.consumer = self.factory.makeOAuthConsumer()

        now = datetime.now(pytz.timezone('UTC'))
        self.in_a_while = now + timedelta(hours=1)
        self.a_long_time_ago = now - timedelta(hours=1000)

    def test_new_token(self):
        request_token = self.consumer.newRequestToken()
        verifyObject(IOAuthRequestToken, request_token)

        # The key and secret are automatically generated.
        self.assertEqual(len(request_token.key), 20)
        self.assertEqual(len(request_token.secret), 80)

        # The date_created is set automatically upon creation.
        now = datetime.now(pytz.timezone('UTC'))
        self.assertTrue(request_token.date_created <= now)

        # A newly created token has not been reviewed by anyone.
        self.assertFalse(request_token.is_reviewed)
        self.assertEqual(None, request_token.person)
        self.assertEqual(None, request_token.date_reviewed)

        # As such, it has no associated permission, expiration date,
        # or context.
        self.assertEqual(None, request_token.permission)
        self.assertEqual(None, request_token.date_expires)
        self.assertEqual(None, request_token.context)

    def test_get_token_for_consumer(self):
        # getRequestToken will find one of a consumer's request
        # tokens, given the token key.
        token_1 = self.consumer.newRequestToken()
        token_2 = self.consumer.getRequestToken(token_1.key)
        self.assertEqual(token_1, token_2)

        # If the key exists but is associated with some other
        # consumer, getRequestToken returns None.
        consumer_2 = self.factory.makeOAuthConsumer()
        self.assertEquals(
            None, consumer_2.getRequestToken(token_1.key))

        # If the key is not in use at all, getRequestToken returns
        # None.
        self.assertEquals(
            None, self.consumer.getRequestToken("no-such-token"))

    def test_get_token_by_key(self):
        # getByKey finds a request token given only its key.
        token = self.consumer.newRequestToken()
        tokens = getUtility(IOAuthRequestTokenSet)
        self.assertEquals(token, tokens.getByKey(token.key))

        # It doesn't matter which consumer the token is associated
        # with.
        consumer_2 = self.factory.makeOAuthConsumer()
        token_2 = consumer_2.newRequestToken()
        self.assertEquals(token_2, tokens.getByKey(token_2.key))

        # If the token is not in use at all, getByKey returns
        # None.
        self.assertEquals(None, tokens.getByKey("no-such-token"))

    def test_token_review(self):
        request_token = self.consumer.newRequestToken()
        # A person may review a request token, associating an
        # OAuthPermission with it.
        request_token.review(self.person, OAuthPermission.WRITE_PUBLIC)

        self.assertTrue(request_token.is_reviewed)
        self.assertEquals(request_token.person, self.person)
        self.assertEquals(request_token.permission,
                          OAuthPermission.WRITE_PUBLIC)

        now = datetime.now(pytz.timezone('UTC'))
        self.assertTrue(request_token.date_created <= now)

        # By default, reviewing a token does not set a context or
        # expiration date.
        self.assertEquals(request_token.context, None)
        self.assertEquals(request_token.date_expires, None)

    def test_token_review_as_unauthorized(self):
        # A request token may be associated with the UNAUTHORIZED
        # permission.
        request_token = self.consumer.newRequestToken()
        request_token.review(self.person, OAuthPermission.UNAUTHORIZED)

        # This token has been reviewed, but it may not be used for any
        # purpose.
        self.assertTrue(request_token.is_reviewed)
        self.assertEquals(request_token.permission,
                          OAuthPermission.UNAUTHORIZED)

    def test_review_with_expiration_date(self):
        # A request token may be associated with an expiration date
        # upon review.
        request_token = self.consumer.newRequestToken()
        request_token.review(
            self.person, OAuthPermission.WRITE_PUBLIC,
            date_expires=self.in_a_while)
        self.assertEquals(request_token.date_expires, self.in_a_while)

        # The expiration date, like the permission and context, is
        # associated with the eventual access token. It has nothing to
        # do with how long the *request* token will remain
        # valid. Setting the expiration date to a date in the past is
        # not a good idea, but it won't expire the request token.
        request_token = self.consumer.newRequestToken()
        request_token.review(
            self.person, OAuthPermission.WRITE_PUBLIC,
            date_expires=self.a_long_time_ago)
        self.assertEquals(request_token.date_expires, self.a_long_time_ago)
        self.assertFalse(request_token.is_expired)

    def _reviewed_token_for_context(self, context_factory):
        """Create and review a request token with a given context."""
        token = self.consumer.newRequestToken()
        name = self.factory.getUniqueString('context')
        context = context_factory(name)
        token.review(
            self.person, OAuthPermission.WRITE_PRIVATE, context=context)
        return token, name

    def test_review_with_product_context(self):
        # When reviewing a request token, the context may be set to a
        # product.
        token, name = self._reviewed_token_for_context(
            self.factory.makeProduct)
        self.assertEquals(token.context.name, name)

    def test_review_with_project_context(self):
        # When reviewing a request token, the context may be set to a
        # project.
        token, name = self._reviewed_token_for_context(
            self.factory.makeProject)
        self.assertEquals(token.context.name, name)

    def test_review_with_distrosourcepackage_context(self):
        # When reviewing a request token, the context may be set to a
        # distribution source package.
        token, name = self._reviewed_token_for_context(
            self.factory.makeDistributionSourcePackage)
        self.assertEquals(token.context.name, name)

    def test_exchange_request_token_for_access_token(self):
        # Once a request token is reviewed, it can be exchanged for an
        # access token.
        request_token = self.consumer.newRequestToken()
        request_token.review(self.person, OAuthPermission.WRITE_PRIVATE)
        access_token = request_token.createAccessToken()

        # An access token inherits its permission from the request
        # token that created it. But an access token's .permission is
        # an AccessLevel object, not an OAuthPermission. The only real
        # difference is that there's no AccessLevel corresponding to
        # OAuthPermission.UNAUTHORIZED.
        self.assertEquals(
            access_token.permission, AccessLevel.WRITE_PRIVATE)

        # By default, access tokens have no context and no expiration
        # date.
        self.assertEquals(None, access_token.context)
        self.assertEquals(None, access_token.date_expires)

        # After being exchanged for an access token, the request token
        # no longer exists.
        self.assertEquals(
            None, self.consumer.getRequestToken(request_token.key))

    def test_cant_exchange_unreviewed_request_token(self):
        # An unreviewed request token cannot be exchanged for an access token.
        token = self.consumer.newRequestToken()
        self.assertRaises(AssertionError, token.createAccessToken)

    def test_cant_exchange_unauthorized_request_token(self):
        # A request token associated with the UNAUTHORIZED
        # OAuthPermission cannot be exchanged for an access token.
        token = self.consumer.newRequestToken()
        token.review(self.person, OAuthPermission.UNAUTHORIZED)
        self.assertRaises(AssertionError, token.createAccessToken)

    def test_access_token_inherits_context_and_expiration(self):
        request_token = self.consumer.newRequestToken()
        context = self.factory.makeProduct()
        request_token.review(
            self.person, OAuthPermission.WRITE_PRIVATE,
            context=context, date_expires=self.in_a_while)

        access_token = request_token.createAccessToken()
        self.assertEquals(request_token.context, access_token.context)
        self.assertEquals(
            request_token.date_expires, access_token.date_expires)

    def testExpiredRequestTokenCantBeReviewed(self):
        """An expired request token can't be reviewed."""
        token = self.factory.makeOAuthRequestToken(
            date_created=self.a_long_time_ago)
        self.assertRaises(
            AssertionError, token.review, self.person,
            OAuthPermission.WRITE_PUBLIC)

    def testExpiredRequestTokenCantBeExchanged(self):
        """An expired request token can't be exchanged for an access token.

        This can only happen if the token was reviewed before it expired.
        """
        token = self.factory.makeOAuthRequestToken(
            date_created=self.a_long_time_ago, reviewed_by=self.person)
        self.assertRaises(AssertionError, token.createAccessToken)
