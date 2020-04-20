# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Registry credentials for use by an `OCIPushRule`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRegistryCredentials',
    'OCIRegistryCredentialsSet',
    ]

import base64
import json

from storm.databases.postgres import JSON
from storm.locals import (
    Int,
    Reference,
    Storm,
    Unicode,
    )
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.oci.interfaces.ociregistrycredentials import (
    IOCIRegistryCredentials,
    IOCIRegistryCredentialsSet,
    )
from lp.services.config import config
from lp.services.crypto.interfaces import (
    CryptoError,
    IEncryptedContainer,
    )
from lp.services.crypto.model import NaClEncryptedContainerBase
from lp.services.database.interfaces import IStore


@implementer(IEncryptedContainer)
class OCIRegistrySecretsEncryptedContainer(NaClEncryptedContainerBase):

    @property
    def public_key_bytes(self):
        if config.oci.registry_secrets_public_key is not None:
            return base64.b64decode(
                config.oci.registry_secrets_public_key.encode('UTF-8'))
        else:
            return None

    @property
    def private_key_bytes(self):
        if config.oci.registry_secrets_private_key is not None:
            return base64.b64decode(
                config.oci.registry_secrets_private_key.encode('UTF-8'))
        else:
            return None


@implementer(IOCIRegistryCredentials)
class OCIRegistryCredentials(Storm):

    __storm_table__ = 'OCIRegistryCredentials'

    id = Int(primary=True)

    owner_id = Int(name='owner', allow_none=False)
    owner = Reference(owner_id, 'Person.id')

    url = Unicode(name="url", allow_none=False)

    _credentials = JSON(name="credentials", allow_none=True)

    def __init__(self, owner, url, credentials):
        self.owner = owner
        self.url = url
        self.setCredentials(credentials)

    def getCredentials(self):
        container = getUtility(IEncryptedContainer, "oci-registry-secrets")
        try:
            return json.loads(container.decrypt(
                self._credentials['credentials_encrypted']).decode("UTF-8"))
        except CryptoError as e:
            # XXX twom 2020-03-18 This needs a better error
            # see SnapStoreClient.UnauthorizedUploadResponse
            # Waiting on OCIRegistryClient.
            raise e

    def setCredentials(self, value):
        container = getUtility(IEncryptedContainer, "oci-registry-secrets")
        self._credentials = {
            "credentials_encrypted": removeSecurityProxy(
                container.encrypt(json.dumps(value).encode('UTF-8')))}

    def destroySelf(self):
        """See `IOCIRegistryCredentials`."""
        store = IStore(OCIRegistryCredentials)
        store.find(
            OCIRegistryCredentials, OCIRegistryCredentials.id == self).remove()


@implementer(IOCIRegistryCredentialsSet)
class OCIRegistryCredentialsSet:

    def new(self, owner, url,  credentials):
        """See `IOCIRegistryCredentialsSet`."""
        return OCIRegistryCredentials(owner, url, credentials)

    def findByOwner(self, owner):
        """See `IOCIRegistryCredentialsSet`."""
        store = IStore(OCIRegistryCredentials)
        return store.find(
            OCIRegistryCredentials,
            OCIRegistryCredentials.owner == owner)
