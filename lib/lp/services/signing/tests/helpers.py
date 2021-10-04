# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper functions for code testing live here."""

__all__ = [
    'SigningServiceClientFixture',
    ]

from unittest import mock

import fixtures
from nacl.public import PrivateKey

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

        self.inject = mock.Mock()
        self.inject.side_effect = self._inject

        self.generate_returns = []
        self.sign_returns = []
        self.inject_returns = []

    def _generate(self, key_type, description,
                  openpgp_key_algorithm=None, length=None):
        key = bytes(PrivateKey.generate().public_key)
        data = {
            "fingerprint": self.factory.getUniqueHexString(40).upper(),
            "public-key": key,
            }
        self.generate_returns.append((key_type, data))
        return data

    def _sign(self, key_type, fingerprint, message_name, message, mode):
        key = bytes(PrivateKey.generate().public_key)
        signed_msg = (
            "signed with key_type={} mode={}".format(
                key_type.name, mode.name).encode("UTF-8"))
        data = {
            'public-key': key,
            'signed-message': signed_msg,
            }
        self.sign_returns.append((key_type, data))
        return data

    def _inject(self, key_type, private_key, public_key, description,
                created_at):
        data = {'fingerprint': self.factory.getUniqueHexString(40).upper()}
        self.inject_returns.append(data)
        return data

    def _setUp(self):
        self.useFixture(ZopeUtilityFixture(self, ISigningServiceClient))

    def _cleanup(self):
        self.generate_returns = []
        self.sign_returns = []
