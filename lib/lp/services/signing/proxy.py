# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Proxy calls to lp-signing service"""

from __future__ import division

__metaclass__ = type

import base64
import json

from lazr.restful.utils import get_current_browser_request
from nacl.encoding import Base64Encoder
from nacl.public import (
    Box,
    PrivateKey,
    PublicKey,
    )
import six

from lp.services.config import config
from lp.services.propertycache import cachedproperty
from lp.services.signing.enums import (
    SigningKeyType,
    SigningMode,
    )
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.services.timeout import urlfetch


class SigningServiceClient:
    """Representation of lp-signing service REST interface

    This class is a singleton (see __new__ method and _instance attribute).
    """
    LP_SIGNING_ADDRESS = config.signing.lp_signing_address
    LOCAL_PRIVATE_KEY = config.signing.local_private_key
    LOCAL_PUBLIC_KEY = config.signing.local_public_key

    _instance = None

    def __new__(cls, *args, **kwargs):
        """Builder for this class to return a singleton instance.

        At first, there will be no way to have multiple different instances
        of lp-signing running (at least not in a way that launchpad should
        be aware of). So, keeping this class as a singleton creates the
        benefit of keeping cached across several points of the system the
        @cachedproperties we have here (service_public_key, for example,
        costs an HTTP request every time it needs to fill the cache).
        """
        if not isinstance(cls._instance, cls):
            cls._instance = object.__new__(cls, *args, **kwargs)
        return cls._instance

    def getUrl(self, path):
        """Shotcut to concatenate LP_SIGNING_ADDRESS with the desired
        endpoint path.

        :param path: The REST endpoint to be joined.
        """
        base_url = config.signing.lp_signing_address
        return six.moves.urllib.parse.urljoin(base_url, path)

    def _getJson(self, path, method="GET", **kwargs):
        """Helper method to do an HTTP request and get back a json from  the
        signing service, raising exception if status code != 2xx.
        """
        timeline = get_request_timeline(get_current_browser_request())
        action = timeline.start(
            "services-signing-proxy-%s" % method, "%s %s" %
            (path, json.dumps(kwargs)))

        try:
            url = self.getUrl(path)
            response = urlfetch(url, method=method.lower(), **kwargs)
            response.raise_for_status()
            return response.json()
        finally:
            action.finish()

    @cachedproperty
    def service_public_key(self):
        """Returns the lp-signing service's public key.
        """
        data = self._getJson("/service-key")
        return PublicKey(data["service-key"], encoder=Base64Encoder)

    @property
    def private_key(self):
        return PrivateKey(self.LOCAL_PRIVATE_KEY, encoder=Base64Encoder)

    def getNonce(self):
        """Get nonce, to be used when sending messages.
        """
        data = self._getJson("/nonce", "POST")
        return base64.b64decode(data["nonce"].encode("UTF-8"))

    def _getAuthHeaders(self, nonce):
        """Get headers to call authenticated endpoints.

        :param nonce: The nonce bytes to be used (not the base64 encoded one!)
        :return: Header dict, ready to be used by requests
        """
        return {
            "Content-Type": "application/x-boxed-json",
            "X-Client-Public-Key": self.LOCAL_PUBLIC_KEY,
            "X-Nonce": base64.b64encode(nonce)}

    def _encryptPayload(self, nonce, message):
        """Returns the encrypted version of message, base64 encoded and
        ready to be sent on a HTTP request to lp-signing service.

        :param nonce: The original (non-base64 encoded) nonce
        :param message: The str message to be encrypted
        """
        box = Box(self.private_key, self.service_public_key)
        encrypted_message = box.encrypt(message, nonce, encoder=Base64Encoder)
        return encrypted_message.ciphertext

    def generate(self, key_type, description):
        """Generate a key to be used when signing.

        :param key_type: One of available key types at SigningKeyType
        :param description: String description of the generated key
        :return: A dict with 'fingerprint' (str) and 'public-key' (a
                Base64-encoded NaCl public key)
        """
        if key_type not in SigningKeyType.items:
            raise ValueError("%s is not a valid key type" % key_type)
        nonce = self.getNonce()
        data = json.dumps({
            "key-type": key_type.name,
            "description": description,
            }).encode("UTF-8")
        return self._getJson(
            "/generate", "POST", headers=self._getAuthHeaders(nonce),
            data=self._encryptPayload(nonce, data))

    def sign(self, key_type, fingerprint, message_name, message, mode):
        """Sign the given message using the specified key_type and a
        pre-generated fingerprint (see `generate` method).

        :param key_type: One of the key types from SigningKeyType enum
        :param fingerprint: The fingerprint of the signing key, generated by
                            the `generate` method
        :param message_name: A description of the message being signed
        :param message: The message to be signed
        :param mode: SigningMode.ATTACHED or SigningMode.DETACHED
        :return: A dict with 'public-key' and 'signed-message'
        """
        if mode not in {SigningMode.ATTACHED, SigningMode.DETACHED}:
            raise ValueError("%s is not a valid mode" % mode)
        if key_type not in SigningKeyType.items:
            raise ValueError("%s is not a valid key type" % key_type)

        nonce = self.getNonce()
        data = json.dumps({
            "key-type": key_type.name,
            "fingerprint": fingerprint,
            "message-name": message_name,
            "message": base64.b64encode(message).decode("UTF-8"),
            "mode": mode.name,
            }).encode("UTF-8")
        data = self._getJson(
            "/sign", "POST",
            headers=self._getAuthHeaders(nonce),
            data=self._encryptPayload(nonce, data))

        return {
            'public-key': data['public-key'],
            'signed-message': base64.b64decode(data['signed-message'])}
