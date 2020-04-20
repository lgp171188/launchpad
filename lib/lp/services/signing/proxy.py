# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Proxy calls to lp-signing service"""

from __future__ import absolute_import, print_function, unicode_literals

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
from nacl.utils import random
from six.moves.urllib.parse import urljoin
from zope.interface import implementer

from lp.services.config import config
from lp.services.propertycache import (
    cachedproperty,
    get_property_cache,
    )
from lp.services.signing.enums import (
    SigningKeyType,
    SigningMode,
    )
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
        return json.loads(box.decrypt(
            response.content, response_nonce, encoder=Base64Encoder))

    def _requestJson(self, path, method="GET", **kwargs):
        """Helper method to do an HTTP request and get back a json from  the
        signing service, raising exception if status code != 2xx.

        :param path: The endpoint path
        :param method: The HTTP method to be used (GET, POST, etc)
        :param needs_resp_nonce: Indicates if the endpoint requires us to
            include a X-Response-Nonce, and returns back an encrypted
            response JSON.
        """
        timeline = get_request_timeline(get_current_browser_request())
        action = timeline.start(
            "services-signing-proxy-%s" % method, "%s %s" %
            (path, json.dumps(kwargs)))

        headers = kwargs.get("headers", {})
        response_nonce = None
        if "X-Response-Nonce" in headers:
            response_nonce = base64.b64decode(headers["X-Response-Nonce"])

        try:
            url = self.getUrl(path)
            response = urlfetch(url, method=method.lower(), **kwargs)
            response.raise_for_status()
            if response_nonce is None:
                return response.json()
            else:
                return self._decryptResponseJson(response, response_nonce)
        finally:
            action.finish()

    @cachedproperty
    def service_public_key(self):
        """Returns the lp-signing service's public key.
        """
        data = self._requestJson("/service-key")
        return PublicKey(data["service-key"], encoder=Base64Encoder)

    @property
    def private_key(self):
        return PrivateKey(
            config.signing.client_private_key, encoder=Base64Encoder)

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
            "X-Nonce": base64.b64encode(nonce),
            "X-Response-Nonce": base64.b64encode(response_nonce),
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

    def generate(self, key_type, description):
        if key_type not in SigningKeyType.items:
            raise ValueError("%s is not a valid key type" % key_type)

        nonce = self.getNonce()
        response_nonce = self._makeResponseNonce()
        data = json.dumps({
            "key-type": key_type.name,
            "description": description,
            }).encode("UTF-8")
        ret = self._requestJson(
            "/generate", "POST",
            headers=self._getAuthHeaders(nonce, response_nonce),
            data=self._encryptPayload(nonce, data))
        return {
            "fingerprint": ret["fingerprint"],
            "public-key": base64.b64decode(ret["public-key"])}

    def sign(self, key_type, fingerprint, message_name, message, mode):
        if mode not in {SigningMode.ATTACHED, SigningMode.DETACHED}:
            raise ValueError("%s is not a valid mode" % mode)
        if key_type not in SigningKeyType.items:
            raise ValueError("%s is not a valid key type" % key_type)

        nonce = self.getNonce()
        response_nonce = self._makeResponseNonce()
        data = json.dumps({
            "key-type": key_type.name,
            "fingerprint": fingerprint,
            "message-name": message_name,
            "message": base64.b64encode(message).decode("UTF-8"),
            "mode": mode.name,
            }).encode("UTF-8")
        data = self._requestJson(
            "/sign", "POST",
            headers=self._getAuthHeaders(nonce, response_nonce),
            data=self._encryptPayload(nonce, data))

        return {
            'public-key': base64.b64decode(data['public-key']),
            'signed-message': base64.b64decode(data['signed-message'])}

    def inject(self, key_type, private_key, public_key, description,
               created_at):
        payload = json.dumps({
            "key-type": key_type.name,
            "private-key": base64.b64encode(private_key).decode("UTF-8"),
            "public-key": base64.b64encode(public_key).decode("UTF-8"),
            "created-at": created_at.isoformat(),
            "description": description,
        }).encode("UTF-8")

        nonce = self.getNonce()
        response_nonce = self._makeResponseNonce()

        data = self._requestJson(
            "/inject", "POST",
            headers=self._getAuthHeaders(nonce, response_nonce),
            data=self._encryptPayload(nonce, payload))
        return {"fingerprint": data["fingerprint"]}
