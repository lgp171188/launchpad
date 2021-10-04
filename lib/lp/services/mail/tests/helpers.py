# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Functions to accomodate testing of the email system."""

__all__ = ['read_test_message']

import os.path

from lp.services.mail.signedmessage import signed_message_from_bytes


testmails_path = os.path.join(os.path.dirname(__file__), 'emails')


def read_test_message(filename):
    """Reads a test message and returns it as ISignedMessage.

    The test messages are located in lp/services/mail/tests/emails
    """
    with open(os.path.join(testmails_path, filename), 'rb') as f:
        message_string = f.read()
    return signed_message_from_bytes(message_string)
