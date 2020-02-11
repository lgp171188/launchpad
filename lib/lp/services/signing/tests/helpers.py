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

    def __init__(self, signing_keys=None, generate=None):
        self.getSigningKeys = FakeMethod(result=signing_keys or {})
        self.generate = FakeMethod(result=generate)

    def setUpKeyGeneration(self, factory, archive):
        """Helper to make ArchiveSigningKeySet.generate calls to actually
        generate a new signing key every time, including it on
        ArchiveSigningKeySet.getSigningKeys call.
        """
        self.getSigningKeys.result = {}
        self.generate = mock.Mock()

        def fake_gen(key_type, *args, **kwargs):
            key = factory.makeSigningKey(key_type=key_type)
            key.sign = FakeMethod(result="signed with %s" % key_type.name)
            arch_signing_key = factory.makeArchiveSigningKey(
                archive=archive, signing_key=key)
            self.getSigningKeys.result[key_type] = (
                arch_signing_key)
            return arch_signing_key

        self.generate.side_effect = fake_gen

    def setUpAllKeyTypes(self, factory, archive):
        """Helper to make ArchiveSigningKeySet.getSigningKeys return one key
        of each type, making it virtually unnecessary for .generate to be
        called
        """
        # Setup, for self.archive, all key types and make
        # ArchiveSigningKeySet return them
        signing_keys_by_type = {}
        for key_type in SigningKeyType.items:
            signing_key = factory.makeSigningKey(key_type=key_type)
            signing_key.sign = FakeMethod(result="signed!")
            archive_signing_key = factory.makeArchiveSigningKey(
                archive=archive, signing_key=signing_key)
            signing_keys_by_type[key_type] = archive_signing_key

        gen_arch_signing_key = factory.makeArchiveSigningKey(archive=archive)
        gen_arch_signing_key.signing_key.sign = FakeMethod(
            result="gen-signed!")
        self.getSigningKeys.result = signing_keys_by_type

    def _setUp(self):
        self.useFixture(ZopeUtilityFixture(self, IArchiveSigningKeySet))
