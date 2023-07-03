# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Registry credentials for use by an `OCIPushRule`."""

__all__ = [
    "OCIRegistryCredentials",
    "OCIRegistryCredentialsSet",
]

import base64
import json

from storm.databases.postgres import JSON
from storm.locals import Int, Reference, Unicode
from zope.component import getUtility
from zope.interface import implementer
from zope.schema import ValidationError
from zope.security.proxy import removeSecurityProxy

from lp.app.validators.url import validate_url
from lp.oci.interfaces.ociregistrycredentials import (
    IOCIRegistryCredentials,
    IOCIRegistryCredentialsSet,
    OCIRegistryCredentialsAlreadyExist,
    OCIRegistryCredentialsNotOwner,
)
from lp.services.config import config
from lp.services.crypto.interfaces import CryptoError, IEncryptedContainer
from lp.services.crypto.model import NaClEncryptedContainerBase
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(IEncryptedContainer)
class OCIRegistrySecretsEncryptedContainer(NaClEncryptedContainerBase):
    @property
    def public_key_bytes(self):
        if config.oci.registry_secrets_public_key is not None:
            return base64.b64decode(
                config.oci.registry_secrets_public_key.encode("UTF-8")
            )
        else:
            return None

    @property
    def private_key_bytes(self):
        if config.oci.registry_secrets_private_key is not None:
            return base64.b64decode(
                config.oci.registry_secrets_private_key.encode("UTF-8")
            )
        else:
            return None


def url_validator(allowed_schemes):
    def wrapped(obj, attr, value):
        if not validate_url(value, allowed_schemes):
            raise ValidationError(
                "%s is not a valid URL for '%s' attribute" % (value, attr)
            )
        return value

    return wrapped


@implementer(IOCIRegistryCredentials)
class OCIRegistryCredentials(StormBase):
    __storm_table__ = "OCIRegistryCredentials"

    id = Int(primary=True)

    owner_id = Int(name="owner", allow_none=False)
    owner = Reference(owner_id, "Person.id")

    url = Unicode(
        name="url",
        allow_none=False,
        validator=url_validator(
            IOCIRegistryCredentials["url"].allowed_schemes
        ),
    )

    _credentials = JSON(name="credentials", allow_none=True)

    # The list of dict keys that should not be encrypted when storing
    # _credentials attribute.
    _UNENCRYPTED_CREDENTIALS_FIELDS = ["username", "region"]

    def __init__(self, owner, url, credentials):
        self.owner = owner
        self.url = url
        self.setCredentials(credentials)

    def getCredentials(self):
        container = getUtility(IEncryptedContainer, "oci-registry-secrets")
        try:
            data = dict(self._credentials or {})
            decrypted_data = json.loads(
                container.decrypt(
                    self._credentials["credentials_encrypted"]
                ).decode("UTF-8")
            )
            if decrypted_data:
                data.update(decrypted_data)
            data.pop("credentials_encrypted")
            return data
        except CryptoError as e:
            # XXX twom 2020-03-18 This needs a better error
            # see SnapStoreClient.UnauthorizedUploadResponse
            # Waiting on OCIRegistryClient.
            raise e

    def setCredentials(self, value):
        container = getUtility(IEncryptedContainer, "oci-registry-secrets")
        copy = value.copy()
        # Remove fields that should not be encrypted.
        unencrypted_fields = {}
        for field in self._UNENCRYPTED_CREDENTIALS_FIELDS:
            unencrypted_fields[field] = copy.pop(field, None)
        # Encrypt the rest of the dict.
        data = {
            "credentials_encrypted": removeSecurityProxy(
                container.encrypt(json.dumps(copy).encode("UTF-8"))
            )
        }
        # Put back the fields that shouldn't be encrypted.
        for field in self._UNENCRYPTED_CREDENTIALS_FIELDS:
            value = unencrypted_fields[field]
            if value is not None:
                data[field] = value
        self._credentials = data

    @property
    def username(self):
        return self._credentials.get("username")

    @username.setter
    def username(self, value):
        self._credentials["username"] = value

    @property
    def region(self):
        return self._credentials.get("region")

    @region.setter
    def region(self, value):
        self._credentials["region"] = value

    def destroySelf(self):
        """See `IOCIRegistryCredentials`."""
        IStore(OCIRegistryCredentials).remove(self)


@implementer(IOCIRegistryCredentialsSet)
class OCIRegistryCredentialsSet:
    def _checkOwner(self, registrant, owner):
        if not registrant.inTeam(owner):
            if owner.is_team:
                raise OCIRegistryCredentialsNotOwner(
                    "%s is not a member of %s."
                    % (registrant.display_name, owner.display_name)
                )
            else:
                raise OCIRegistryCredentialsNotOwner(
                    "%s cannot create credentials owned by %s."
                    % (registrant.display_name, owner.display_name)
                )

    def _checkForExisting(self, owner, url, credentials):
        for existing in self.findByOwner(owner):
            url_match = existing.url == url
            username_match = existing.username == credentials.get("username")
            region_match = existing.region == credentials.get("region")
            if url_match and username_match and region_match:
                return existing
        return None

    def new(self, registrant, owner, url, credentials, override_owner=False):
        """See `IOCIRegistryCredentialsSet`."""
        if not override_owner:
            self._checkOwner(registrant, owner)
        if self._checkForExisting(owner, url, credentials):
            raise OCIRegistryCredentialsAlreadyExist()
        return OCIRegistryCredentials(owner, url, credentials)

    def getOrCreate(
        self, registrant, owner, url, credentials, override_owner=False
    ):
        """See `IOCIRegistryCredentialsSet`."""
        if not override_owner:
            self._checkOwner(registrant, owner)
        existing = self._checkForExisting(owner, url, credentials)
        if existing:
            return existing
        return self.new(
            registrant, owner, url, credentials, override_owner=override_owner
        )

    def findByOwner(self, owner):
        """See `IOCIRegistryCredentialsSet`."""
        store = IStore(OCIRegistryCredentials)
        return store.find(
            OCIRegistryCredentials, OCIRegistryCredentials.owner == owner
        )
