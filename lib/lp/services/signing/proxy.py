# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Proxy calls to lp-signing service"""

import base64
import json
from urllib.parse import urljoin

from lazr.restful.utils import get_current_browser_request
from nacl.encoding import Base64Encoder
from nacl.public import Box, PrivateKey, PublicKey
from nacl.utils import random
from zope.interface import implementer

from lp.services.config import config
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.services.signing.enums import SigningKeyType, SigningMode
from lp.services.signing.interfaces.signingserviceclient import (
    ISigningServiceClient,
)
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.services.timeout import urlfetch


@implementer(ISigningServiceClient)
class SigningServiceClient:
    """Representation of lp-signing service REST interface

    To benefit from caching, use this class as a singleton through
    getUtility(ISigningServiceClient).
    """

    def _cleanCaches(self):
        """Cleanup cached properties"""
        del get_property_cache(self).service_public_key

    def getUrl(self, path):
        """Shortcut to concatenate lp-signing address with the desired
        endpoint path.

        :param path: The REST endpoint to be joined.
        """
        base_url = config.signing.signing_endpoint
        return urljoin(base_url, path)

    def _makeResponseNonce(self):
        return random(Box.NONCE_SIZE)

    def _decryptResponseJson(self, response, response_nonce):
        box = Box(self.private_key, self.service_public_key)
        return json.loads(
            box.decrypt(
                response.content, response_nonce, encoder=Base64Encoder
            ).decode("UTF-8")
        )

    def _requestJson(self, path, method="GET", encrypt=False, **kwargs):
        """Helper method to do an HTTP request and get back a json from  the
        signing service, raising exception if status code != 2xx.

        :param path: The endpoint path
        :param method: The HTTP method to be used (GET, POST, etc)
        :param encrypt: If True, make an encrypted and authenticated
            request.
        """
        kwargs = dict(kwargs)

        timeline = get_request_timeline(get_current_browser_request())
        if encrypt:
            nonce = self.getNonce()
            response_nonce = self._makeResponseNonce()
            headers = kwargs.setdefault("headers", {})
            headers.update(self._getAuthHeaders(nonce, response_nonce))
            if "data" in kwargs:
                data = kwargs.pop("data")
            elif "json" in kwargs:
                data = json.dumps(kwargs.pop("json")).encode("UTF-8")
            else:
                data = b""
            # The data will be encrypted, so shouldn't be exposed to OOPSes.
            # It may also be very large.
            redacted_kwargs = dict(kwargs)
            # Stuff the encrypted data back into the arguments.
            kwargs["data"] = self._encryptPayload(nonce, data)
        else:
            redacted_kwargs = kwargs
        action = timeline.start(
            "services-signing-proxy-%s" % method,
            "%s %s" % (path, json.dumps(redacted_kwargs)),
        )

        try:
            url = self.getUrl(path)
            response = urlfetch(url, method=method.lower(), **kwargs)
            response.raise_for_status()
            if encrypt:
                return self._decryptResponseJson(response, response_nonce)
            else:
                return response.json()
        finally:
            action.finish()

    @cachedproperty
    def service_public_key(self):
        """Returns the lp-signing service's public key."""
        data = self._requestJson("/service-key")
        return PublicKey(data["service-key"], encoder=Base64Encoder)

    @property
    def private_key(self):
        return PrivateKey(
            config.signing.client_private_key, encoder=Base64Encoder
        )

    def getNonce(self):
        data = self._requestJson("/nonce", "POST")
        return base64.b64decode(data["nonce"].encode("UTF-8"))

    def _getAuthHeaders(self, nonce, response_nonce):
        """Get headers to call authenticated endpoints.

        :param nonce: The nonce bytes to be used (not the base64 encoded one!)
        :param response_nonce: The X-Response-Nonce bytes to be used to
            decrypt the boxed response.
        :return: Header dict, ready to be used by requests
        """
        return {
            "Content-Type": "application/x-boxed-json",
            "X-Client-Public-Key": config.signing.client_public_key,
            "X-Nonce": base64.b64encode(nonce).decode("UTF-8"),
            "X-Response-Nonce": (
                base64.b64encode(response_nonce).decode("UTF-8")
            ),
        }

    def _encryptPayload(self, nonce, message):
        """Returns the encrypted version of message, base64 encoded and
        ready to be sent on a HTTP request to lp-signing service.

        :param nonce: The original (non-base64 encoded) nonce
        :param message: The str message to be encrypted
        """
        box = Box(self.private_key, self.service_public_key)
        encrypted_message = box.encrypt(message, nonce, encoder=Base64Encoder)
        return encrypted_message.ciphertext

    def generate(
        self, key_type, description, openpgp_key_algorithm=None, length=None
    ):
        if key_type not in SigningKeyType.items:
            raise ValueError("%s is not a valid key type" % key_type)
        if key_type == SigningKeyType.OPENPGP:
            if openpgp_key_algorithm is None:
                raise ValueError(
                    "SigningKeyType.OPENPGP requires openpgp_key_algorithm"
                )
            if length is None:
                raise ValueError("SigningKeyType.OPENPGP requires length")

        payload = {
            "key-type": key_type.name,
            "description": description,
        }
        if key_type == SigningKeyType.OPENPGP:
            payload.update(
                {
                    "openpgp-key-algorithm": openpgp_key_algorithm.name,
                    "length": length,
                }
            )

        ret = self._requestJson(
            "/generate", "POST", encrypt=True, json=payload
        )
        return {
            "fingerprint": ret["fingerprint"],
            "public-key": base64.b64decode(ret["public-key"].encode("UTF-8")),
        }

    def sign(self, key_type, fingerprints, message_name, message, mode):
        valid_modes = {SigningMode.ATTACHED, SigningMode.DETACHED}
        if key_type == SigningKeyType.OPENPGP:
            valid_modes.add(SigningMode.CLEAR)
        if mode not in valid_modes:
            raise ValueError("%s is not a valid mode" % mode)
        if key_type not in SigningKeyType.items:
            raise ValueError("%s is not a valid key type" % key_type)
        if not fingerprints:
            raise ValueError("Not even one fingerprint was provided")
        if len(fingerprints) > 1 and key_type != SigningKeyType.OPENPGP:
            raise ValueError(
                "Multi-signing is not supported for non-OpenPGP keys"
            )

        # The signing service accepts either a single fingerprint
        # string (for all key types) or a list of two or more
        # fingerprints (only for OpenPGP keys) for the 'fingerprint'
        # property.
        fingerprint = (
            fingerprints[0] if len(fingerprints) == 1 else fingerprints
        )
        payload = {
            "key-type": key_type.name,
            "fingerprint": fingerprint,
            "message-name": message_name,
            "message": base64.b64encode(message).decode("UTF-8"),
            "mode": mode.name,
        }

        ret = self._requestJson("/sign", "POST", encrypt=True, json=payload)
        if isinstance(ret["public-key"], str):
            public_key = base64.b64decode(ret["public-key"].encode("UTF-8"))
        else:  # is a list of public key strings
            public_key = [
                base64.b64decode(x).encode("UTF-8") for x in ret["public-key"]
            ]
        return {
            "public-key": public_key,
            "signed-message": base64.b64decode(
                ret["signed-message"].encode("UTF-8")
            ),
        }

    def inject(
        self, key_type, private_key, public_key, description, created_at
    ):
        if key_type not in SigningKeyType.items:
            raise ValueError("%s is not a valid key type" % key_type)

        payload = {
            "key-type": key_type.name,
            "private-key": base64.b64encode(private_key).decode("UTF-8"),
            "public-key": base64.b64encode(public_key).decode("UTF-8"),
            "created-at": created_at.isoformat(),
            "description": description,
        }

        ret = self._requestJson("/inject", "POST", encrypt=True, json=payload)
        return {"fingerprint": ret["fingerprint"]}

    def addAuthorization(self, key_type, fingerprint, client_name):
        if key_type not in SigningKeyType.items:
            raise ValueError("%s is not a valid key type" % key_type)

        payload = {
            "key-type": key_type.name,
            "fingerprint": fingerprint,
            "client-name": client_name,
        }

        self._requestJson(
            "/authorizations/add", "POST", encrypt=True, json=payload
        )
