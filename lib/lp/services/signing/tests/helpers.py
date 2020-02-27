# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper functions for code testing live here."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'SigningServiceClientFixture',
    ]

import fixtures
import mock
from nacl.public import PrivateKey
from six import text_type

from lp.services.signing.interfaces.signingserviceclient import (
    ISigningServiceClient,
    )
from lp.testing.fixture import ZopeUtilityFixture


class SigningServiceClientFixture(fixtures.Fixture):
    """Mock for SigningServiceClient class.

    This method fakes the API calls on generate and sign methods,
    and provides a nice way of getting the fake returned values on
    self.generate_returns and self.sign_returns attributes.

    Both generate_returns and sign_returns format is the following:
        [(key_type, api_return_dict), (key_type, api_return_dict), ...]"""
    def __init__(self, factory):
        self.factory = factory

        self.generate = mock.Mock()
        self.generate.side_effect = self._generate

        self.sign = mock.Mock()
        self.sign.side_effect = self._sign

        self.generate_returns = []
        self.sign_returns = []

    def _generate(self, key_type, description):
        key = bytes(PrivateKey.generate().public_key)
        data = {
            "fingerprint": text_type(self.factory.getUniqueHexString(40)),
            "public-key": key}
        self.generate_returns.append((key_type, data))
        return data

    def _sign(self, key_type, fingerprint, message_name, message, mode):
        key = bytes(PrivateKey.generate().public_key)
        signed_msg = "signed with key_type={}".format(key_type.name)
        data = {
            'public-key': key,
            'signed-message': signed_msg}
        self.sign_returns.append((key_type, data))
        return data

    def _setUp(self):
        self.useFixture(ZopeUtilityFixture(self, ISigningServiceClient))

    def _cleanup(self):
        self.generate_returns = []
        self.sign_returns = []
