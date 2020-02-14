# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper functions for code testing live here."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'ArchiveSigningKeySetFixture',
    ]

import fixtures
import mock

from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import IArchiveSigningKeySet
from lp.testing.fakemethod import FakeMethod
from lp.testing.fixture import ZopeUtilityFixture


class ArchiveSigningKeySetFixture(fixtures.Fixture):
    """A fixture that temporarily registers a fake ArchiveSigningKeySet."""

    def __init__(self, signing_key=None, generate=None):
        self.getSigningKey = mock.Mock()
        self.getSigningKey.return_value = signing_key

        self.generate = mock.Mock()
        self.generate.return_value = generate

    def setUpKeyGeneration(self, factory, archive):
        """Helper to make ArchiveSigningKeySet.generate calls to actually
        generate a new signing key every time, including it on
        ArchiveSigningKeySet.getSigningKeys call.

        :return: A dict like {key_type: signing_key} where all generated
                 keys will be stored.
        """
        self.getSigningKey.result = mock.Mock()
        self.generate = mock.Mock()

        generated_keys = {}
        def fake_gen(key_type, *args, **kwargs):
            key = factory.makeSigningKey(key_type=key_type)
            key.sign = FakeMethod(result="signed with %s" % key_type.name)
            arch_signing_key = factory.makeArchiveSigningKey(
                archive=archive, signing_key=key)
            generated_keys[key_type] = key
            return arch_signing_key

        def fake_get_key(key_type, *args, **kwargs):
            return generated_keys.get(key_type)

        self.generate.side_effect = fake_gen
        self.getSigningKey.side_effect = fake_get_key
        return generated_keys

    def setUpAllKeyTypes(self, factory, archive):
        """Helper to make ArchiveSigningKeySet.getSigningKeys return one key
        of each type, making it unnecessary for ArchiveSigningKeySet.generate
        to be called.

        :return: A dict like {key_type: signing_key} with all keys available.
        """
        # Setup, for self.archive, all key types and make
        # ArchiveSigningKeySet return them
        signing_keys_by_type = {}
        for key_type in SigningKeyType.items:
            signing_key = factory.makeSigningKey(key_type=key_type)
            signing_key.sign = FakeMethod(result="signed!")
            archive_signing_key = factory.makeArchiveSigningKey(
                archive=archive, signing_key=signing_key)
            signing_keys_by_type[key_type] = archive_signing_key.signing_key

        def fake_get_key(key_type, *args, **kwargs):
            return signing_keys_by_type.get(key_type)

        self.getSigningKey = mock.Mock()
        self.getSigningKey.side_effect = fake_get_key
        return signing_keys_by_type

    def setUpSigningKeys(self, keys_per_type):
        """
        Sets the return of getSigningKey to be the given dict of {key_type:
        signing_key} given by keys_per_type parameter.

        :return: A dict like {key_type: signing_key} with all keys available.
        """
        def fake_get_key(key_type, *args, **kwargs):
            return keys_per_type.get(key_type)
        self.getSigningKey = mock.Mock()
        self.getSigningKey.side_effect = fake_get_key
        return keys_per_type

    def _setUp(self):
        self.useFixture(ZopeUtilityFixture(self, IArchiveSigningKeySet))
