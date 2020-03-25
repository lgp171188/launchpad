# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper methods and mixins for OCI tests."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = []

import base64

from nacl.public import PrivateKey


class OCIConfigHelperMixin:

    def setConfig(self):
        self.private_key = PrivateKey.generate()
        self.pushConfig(
            "oci",
            registry_secrets_public_key=base64.b64encode(
                bytes(self.private_key.public_key)).decode("UTF-8"))
        self.pushConfig(
            "oci",
            registry_secrets_private_key=base64.b64encode(
                bytes(self.private_key)).decode("UTF-8"))
