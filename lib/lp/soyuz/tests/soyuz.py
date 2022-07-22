# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper functions/classes for Soyuz tests."""

__all__ = [
    "Base64KeyMatches",
]

import base64

from testtools.matchers import Equals, Matcher
from zope.component import getUtility

from lp.services.gpg.interfaces import IGPGHandler


class Base64KeyMatches(Matcher):
    """Matches if base64-encoded key material has a given fingerprint."""

    def __init__(self, fingerprint):
        self.fingerprint = fingerprint

    def match(self, encoded_key):
        key = base64.b64decode(encoded_key.encode("ASCII"))
        return Equals(self.fingerprint).match(
            getUtility(IGPGHandler).importPublicKey(key).fingerprint
        )

    def __str__(self):
        return "Base64KeyMatches(%s)" % self.fingerprint
