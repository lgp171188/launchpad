# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'OAuthAccessToken',
    'OAuthConsumer',
    'OAuthConsumerSet',
    'OAuthNonce',
    'OAuthRequestToken',
    'OAuthRequestTokenSet']

from datetime import (
    datetime,
    timedelta,
    )

import re
import pytz
from sqlobject import (
    BoolCol,
    ForeignKey,
    StringCol,
    )
from storm.expr import And
from zope.component import getUtility
from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase
from canonical.launchpad.components.tokens import (
    create_token,
    create_unique_token_for_table,
    )
from canonical.launchpad.interfaces import (
    ClockSkew,
    IOAuthAccessToken,
    IOAuthConsumer,
    IOAuthConsumerSet,
    IOAuthNonce,
    IOAuthRequestToken,
    IOAuthRequestTokenSet,
    NonceAlreadyUsed,
    TimestampOrderingError,
    )
from canonical.launchpad.webapp.interfaces import (
    AccessLevel,
    IStoreSelector,
    MAIN_STORE,
    MASTER_FLAVOR,
    OAuthPermission,
    )
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
    )
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.projectgroup import IProjectGroup

# How many hours should a request token be valid for?
REQUEST_TOKEN_VALIDITY = 2
# The OAuth Core 1.0 spec (http://oauth.net/core/1.0/#nonce) says that a
# timestamp "MUST be equal or greater than the timestamp used in previous
# requests," but this is likely to cause problems if the client does request
# pipelining, so we use a time window (relative to the timestamp of the
# existing OAuthNonce) to check if the timestamp can is acceptable. As
# suggested by Robert, we use a window which is at least twice the size of our
# hard time out. This is a safe bet since no requests should take more than
# one hard time out.
TIMESTAMP_ACCEPTANCE_WINDOW = 60 # seconds
# If the timestamp is far in the future because of a client's clock skew,
# it will effectively invalidate the authentication tokens when the clock is
# corrected.  To prevent that from becoming too serious a problem, we raise an
# exception if the timestamp is off by more than this amount from the server's
# concept of "now".  We also reject timestamps that are too old by the same
# amount.
TIMESTAMP_SKEW_WINDOW = 60*60 # seconds, +/-

class OAuthBase(SQLBase):
    """Base class for all OAuth database classes."""

    @staticmethod
    def _get_store():
        """See `SQLBase`.

        We want all OAuth classes to be retrieved from the master flavour.  If
        they are retrieved from the slave, there will be problems in the
        authorization exchange, since it will be done across applications that
        won't share the session cookies.
        """
        return getUtility(IStoreSelector).get(MAIN_STORE, MASTER_FLAVOR)

    getStore = _get_store


class OAuthConsumer(OAuthBase):
    """See `IOAuthConsumer`."""
    implements(IOAuthConsumer)

    date_created = UtcDateTimeCol(default=UTC_NOW, notNull=True)
    disabled = BoolCol(notNull=True, default=False)
    key = StringCol(notNull=True)
    secret = StringCol(notNull=False, default='')

    # This regular expression singles out a consumer key that
    # represents any and all apps running on a specific computer
    # (usually a desktop). For instance:
    #
    # System-wide: Ubuntu desktop (hostname1)
    #  - An Ubuntu desktop called "hostname1"
    # System-wide: Windows desktop (Computer Name)
    #  - A Windows desktop called "Computer Name"
    # System-wide: Mac OS desktop (hostname2)
    #  - A Macintosh desktop called "hostname2"
    # System-wide Android phone (Bob's Phone)
    #  - An Android phone called "Bob's Phone"
    integrated_desktop_re = re.compile("^System-wide: (.*) \(([^)]*)\)$")

    def _integrated_desktop_match_group(self, position):
        """Return information about a desktop integration token.

        A convenience method that runs the desktop integration regular
        expression against the consumer key.

        :param position: The match group to return if the regular
        expression matches.

        :return: The value of one of the match groups, or None.
        """
        match = self.integrated_desktop_re.match(self.key)
        if match is None:
            return None
        return match.groups()[position]

    @property
    def is_integrated_desktop(self):
        """See `IOAuthConsumer`."""
        return self.integrated_desktop_re.match(self.key) is not None

    @property
    def integrated_desktop_type(self):
        """See `IOAuthConsumer`."""
        return self._integrated_desktop_match_group(0)

    @property
    def integrated_desktop_name(self):
        """See `IOAuthConsumer`."""
        return self._integrated_desktop_match_group(1)

    def newRequestToken(self):
        """See `IOAuthConsumer`."""
        key, secret = create_token_key_and_secret(table=OAuthRequestToken)
        return OAuthRequestToken(
            consumer=self, key=key, secret=secret)

    def getAccessToken(self, key):
        """See `IOAuthConsumer`."""
        return OAuthAccessToken.selectOneBy(key=key, consumer=self)

    def getRequestToken(self, key):
        """See `IOAuthConsumer`."""
        return OAuthRequestToken.selectOneBy(key=key, consumer=self)


class OAuthConsumerSet:
    """See `IOAuthConsumerSet`."""
    implements(IOAuthConsumerSet)

    def new(self, key, secret=''):
        """See `IOAuthConsumerSet`."""
        assert self.getByKey(key) is None, (
            "The key '%s' is already in use by another consumer." % key)
        return OAuthConsumer(key=key, secret=secret)

    def getByKey(self, key):
        """See `IOAuthConsumerSet`."""
        return OAuthConsumer.selectOneBy(key=key)


class OAuthAccessToken(OAuthBase):
    """See `IOAuthAccessToken`."""
    implements(IOAuthAccessToken)

    consumer = ForeignKey(
        dbName='consumer', foreignKey='OAuthConsumer', notNull=True)
    person = ForeignKey(
        dbName='person', foreignKey='Person', notNull=False, default=None)
    date_created = UtcDateTimeCol(default=UTC_NOW, notNull=True)
    date_expires = UtcDateTimeCol(notNull=False, default=None)
    key = StringCol(notNull=True)
    secret = StringCol(notNull=False, default='')

    permission = EnumCol(enum=AccessLevel, notNull=True)

    product = ForeignKey(
        dbName='product', foreignKey='Product', notNull=False, default=None)
    project = ForeignKey(
        dbName='project', foreignKey='ProjectGroup', notNull=False,
        default=None)
    sourcepackagename = ForeignKey(
        dbName='sourcepackagename', foreignKey='SourcePackageName',
        notNull=False, default=None)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution',
        notNull=False, default=None)

    @property
    def context(self):
        """See `IOAuthToken`."""
        if self.product:
            return self.product
        elif self.project:
            return self.project
        elif self.distribution:
            if self.sourcepackagename:
                return self.distribution.getSourcePackage(
                    self.sourcepackagename)
            else:
                return self.distribution
        else:
            return None

    @property
    def is_expired(self):
        now = datetime.now(pytz.timezone('UTC'))
        return self.date_expires is not None and self.date_expires <= now

    def checkNonceAndTimestamp(self, nonce, timestamp):
        """See `IOAuthAccessToken`."""
        timestamp = float(timestamp)
        date = datetime.fromtimestamp(timestamp, pytz.UTC)
        # Determine if the timestamp is too far off from now.
        skew = timedelta(seconds=TIMESTAMP_SKEW_WINDOW)
        now = datetime.now(pytz.UTC)
        if date < (now-skew) or date > (now+skew):
            raise ClockSkew('Timestamp appears to come from bad system clock')
        # Determine if the nonce was already used for this timestamp.
        store = OAuthNonce.getStore()
        oauth_nonce = store.find(OAuthNonce,
                                 And(OAuthNonce.access_token==self,
                                     OAuthNonce.nonce==nonce,
                                     OAuthNonce.request_timestamp==date)
                                 ).one()
        if oauth_nonce is not None:
            raise NonceAlreadyUsed('This nonce has been used already.')
        # Determine if the timestamp is too old compared to most recent
        # request.
        limit = date + timedelta(seconds=TIMESTAMP_ACCEPTANCE_WINDOW)
        match = store.find(OAuthNonce,
                           And(OAuthNonce.access_token==self,
                               OAuthNonce.request_timestamp>limit)
                           ).any()
        if match is not None:
            raise TimestampOrderingError(
                'Timestamp too old compared to most recent request')
        # Looks OK.  Give a Nonce object back.
        return OAuthNonce(
            access_token=self, nonce=nonce, request_timestamp=date)


class OAuthRequestToken(OAuthBase):
    """See `IOAuthRequestToken`."""
    implements(IOAuthRequestToken)

    consumer = ForeignKey(
        dbName='consumer', foreignKey='OAuthConsumer', notNull=True)
    person = ForeignKey(
        dbName='person', foreignKey='Person', notNull=False, default=None)
    date_created = UtcDateTimeCol(default=UTC_NOW, notNull=True)
    date_expires = UtcDateTimeCol(notNull=False, default=None)
    key = StringCol(notNull=True)
    secret = StringCol(notNull=False, default='')

    permission = EnumCol(enum=OAuthPermission, notNull=False, default=None)
    date_reviewed = UtcDateTimeCol(default=None, notNull=False)

    product = ForeignKey(
        dbName='product', foreignKey='Product', notNull=False, default=None)
    project = ForeignKey(
        dbName='project', foreignKey='ProjectGroup', notNull=False,
        default=None)
    sourcepackagename = ForeignKey(
        dbName='sourcepackagename', foreignKey='SourcePackageName',
        notNull=False, default=None)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution',
        notNull=False, default=None)

    @property
    def context(self):
        """See `IOAuthToken`."""
        if self.product:
            return self.product
        elif self.project:
            return self.project
        elif self.distribution:
            if self.sourcepackagename:
                return self.distribution.getSourcePackage(
                    self.sourcepackagename)
            else:
                return self.distribution
        else:
            return None

    @property
    def is_expired(self):
        now = datetime.now(pytz.timezone('UTC'))
        expires = self.date_created + timedelta(hours=REQUEST_TOKEN_VALIDITY)
        return expires <= now

    def review(self, user, permission, context=None, date_expires=None):
        """See `IOAuthRequestToken`."""
        if self.is_reviewed:
            raise AssertionError(
                "Request tokens can be reviewed only once.")
        if self.is_expired:
            raise AssertionError(
                'This request token has expired and can no longer be '
                'reviewed.')
        self.date_reviewed = datetime.now(pytz.timezone('UTC'))
        self.date_expires = date_expires
        self.person = user
        self.permission = permission
        if IProduct.providedBy(context):
            self.product = context
        elif IProjectGroup.providedBy(context):
            self.project = context
        elif IDistribution.providedBy(context):
            self.distribution = context
        elif IDistributionSourcePackage.providedBy(context):
            self.sourcepackagename = context.sourcepackagename
            self.distribution = context.distribution
        else:
            assert context is None, ("Unknown context type: %r." % context)

    def createAccessToken(self):
        """See `IOAuthRequestToken`."""
        if not self.is_reviewed:
            raise AssertionError(
                'Cannot create an access token from an unreviewed request '
                'token.')
        if self.permission == OAuthPermission.UNAUTHORIZED:
            raise AssertionError(
                'The user did not grant access to this consumer.')
        if self.is_expired:
            raise AssertionError(
                'This request token has expired and can no longer be '
                'exchanged for an access token.')

        key, secret = create_token_key_and_secret(table=OAuthAccessToken)
        access_level = AccessLevel.items[self.permission.name]
        access_token = OAuthAccessToken(
            consumer=self.consumer, person=self.person, key=key,
            secret=secret, permission=access_level,
            date_expires=self.date_expires, product=self.product,
            project=self.project, distribution=self.distribution,
            sourcepackagename=self.sourcepackagename)
        self.destroySelf()
        return access_token

    @property
    def is_reviewed(self):
        """See `IOAuthRequestToken`."""
        return self.date_reviewed is not None


class OAuthRequestTokenSet:
    """See `IOAuthRequestTokenSet`."""
    implements(IOAuthRequestTokenSet)

    def getByKey(self, key):
        """See `IOAuthRequestTokenSet`."""
        return OAuthRequestToken.selectOneBy(key=key)


class OAuthNonce(OAuthBase):
    """See `IOAuthNonce`."""
    implements(IOAuthNonce)

    access_token = ForeignKey(
        dbName='access_token', foreignKey='OAuthAccessToken', notNull=True)
    request_timestamp = UtcDateTimeCol(default=UTC_NOW, notNull=True)
    nonce = StringCol(notNull=True)


def create_token_key_and_secret(table):
    """Create a key and secret for an OAuth token.

    :table: The table in which the key/secret are going to be used. Must be
        one of OAuthAccessToken or OAuthRequestToken.

    The key will have a length of 20 and we'll make sure it's not yet in the
    given table.  The secret will have a length of 80.
    """
    key_length = 20
    key = create_unique_token_for_table(key_length, getattr(table, "key"))
    secret_length = 80
    secret = create_token(secret_length)
    return key, secret
