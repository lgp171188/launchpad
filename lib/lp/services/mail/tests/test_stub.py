# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from doctest import DocTestSuite
import re

from zope.testing.renormalizing import OutputChecker

from lp.testing.layers import LaunchpadFunctionalLayer


def test_simple_sendmail():
    r"""
    Send an email (faked by TestMailer - no actual email is sent)

    >>> from email import message_from_bytes
    >>> from email.mime.text import MIMEText
    >>> import transaction
    >>> from lp.services.mail import stub
    >>> from lp.services.mail.sendmail import simple_sendmail

    >>> body = 'The email body'
    >>> subject = 'The email subject'
    >>> message_id1 = simple_sendmail(
    ...     'nobody1@example.com', ['nobody2@example.com'], subject, body
    ...     )

    We should have a message id, a string

    >>> bool(message_id1)
    True
    >>> isinstance(message_id1,str)
    True

    We can also send arbitrary headers through. Note how Python's
    email package handles Message-Id headers

    >>> message_id2 = simple_sendmail(
    ...     'nobody@example.com', ['nobody2@example.com'], subject, body,
    ...     {'Message-Id': '<myMessageId>', 'X-Fnord': 'True'}
    ...     )
    >>> message_id2
    'myMessageId'

    The TestMailer stores sent emails in memory (which we cleared in the
    setUp() method). But the actual email has yet to be sent, as that
    happens when the transaction is committed.

    >>> len(stub.test_emails)
    0
    >>> transaction.commit()
    >>> len(stub.test_emails)
    2
    >>> stub.test_emails[0] == stub.test_emails[1]
    False

    We have two emails, but we have no idea what order they are in!

    Let's sort them by their From: fields, and verify that the second one is
    the one we want because only the second one contains the string
    'nobody@example.com' in its raw message.

    >>> sorted_test_emails = sorted(
    ...     list(stub.test_emails),
    ...     key=lambda email: message_from_bytes(email[2])['From'])
    >>> for from_addr, to_addrs, raw_message in sorted_test_emails:
    ...     print(from_addr, to_addrs, b'nobody@example.com' in raw_message)
    bounces@canonical.com ['nobody2@example.com'] False
    bounces@canonical.com ['nobody2@example.com'] True

    >>> from_addr, to_addrs, raw_message = sorted_test_emails[1]
    >>> from_addr
    'bounces@canonical.com'
    >>> to_addrs
    ['nobody2@example.com']

    The message should be a sane RFC2822 document

    >>> message = message_from_bytes(raw_message)
    >>> message['From']
    'nobody@example.com'
    >>> message['To']
    'nobody2@example.com'
    >>> message['Subject'] == subject
    True
    >>> message['Message-Id']
    '<myMessageId>'
    >>> message.get_payload() == body
    True

    Character set should be utf-8 as per Bug #39758. utf8 isn't good enough.

    >>> message['Content-Type']
    'text/plain; charset="utf-8"'

    And we want quoted printable, as it generally makes things readable
    and for languages it doesn't help, the only downside to base64 is bloat.

    >>> message['Content-Transfer-Encoding']
    'quoted-printable'

    The message has a number of additional headers added by default.
    'X-Generated-By' not only indicates that the source is Launchpad, but
    shows the git revision and instance name.

    >>> message.get_params(header='X-Generated-By')
    ... # doctest: +NORMALIZE_WHITESPACE,+ELLIPSIS
    [('Launchpad (canonical.com)', ''),
     ('revision', '0000000000000000000000000000000000000000'),
     ('instance', 'testrunner_...')]
    """


def test_suite():
    suite = DocTestSuite(checker=OutputChecker([
        (re.compile(r"'revision', '[0-9a-f]+'"),
         "'revision', '%s'" % ('0' * 40))]))
    suite.layer = LaunchpadFunctionalLayer
    return suite
