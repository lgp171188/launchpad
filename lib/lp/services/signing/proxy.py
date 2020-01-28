# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Proxy calls to lp-signing service"""

from __future__ import division

__metaclass__ = type

import base64
import json

import requests
from lp.services.propertycache import cachedproperty
from nacl.encoding import Base64Encoder
from nacl.public import (
    Box,
    PrivateKey,
    PublicKey,
)


class SigningService:
    # XXX: Move it to configuration
    LP_SIGNING_ADDRESS = "http://signing.launchpad.test:8000"

    # XXX: Temporary test keys. Should be moved to configuration files
    LOCAL_PRIVATE_KEY = "O73bJzd3hybyBxUKk0FaR6K9CbbmxBYkw6vCrIWZkSY="
    LOCAL_PUBLIC_KEY = "xEtwSS7kdGmo0ElcN2fR/mcHS0A42zhYbo/+5KV4xRs="

    def __init__(self):
        pass

    def get_url(self, path):
        """Shotcut to concatenate LP_SIGNING_ADDRESS with the desired
        endpoint path

        :param path: The REST endpoint to be joined"""
        return self.LP_SIGNING_ADDRESS + path

    def _get_json(self, path, method="GET", **kwargs):
        """Helper method to do an HTTP request and get back a json from  the
        signing service, raising exception if status code != 200
        """
        url = self.get_url(path)
        if method == "GET":
            response = requests.get(url)
        elif method == "POST":
            response = requests.post(url, **kwargs)
        else:
            raise NotImplemented("Only GET and POST are allowed for now")

        response.raise_for_status()
        return response.json()

    @cachedproperty
    def service_public_key(self):
        """Returns the lp-signing service's public key
        """
        data = self._get_json("/service-key")
        return PublicKey(data["service-key"], encoder=Base64Encoder)

    @property
    def private_key(self):
        return PrivateKey(self.LOCAL_PRIVATE_KEY, encoder=Base64Encoder)

    def get_nonce(self):
        """Get nonce, to be used when sending messages
        """
        data = self._get_json("/nonce", "POST")
        return base64.b64decode(data["nonce"].encode("UTF-8"))

    def _get_auth_headers(self, nonce):
        """Get headers to call authenticated endpoints

        :param nonce: The nonce bytes to be used (not the base64 encoded one!)
        :return: Header dict, ready to be used by requests
        """
        return {
            "Content-Type": "application/x-boxed-json",
            "X-Client-Public-Key": self.LOCAL_PUBLIC_KEY,
            "X-Nonce": base64.b64encode(nonce)}

    def generate(self, key_type, description):
        """Generate a key to be used when signing

        :param key_type: One of available key types at lp-signing: ["UEFI",
                         "KMOD", "OPAL", "SIPL", "FIT"]
        :param description: String description of the generated key
        :return: A dict with 'fingerprint' (str) and 'public-key' (a
                Base64-encoded NaCl public key)
        """
        if key_type not in {"UEFI", "KMOD", "OPAL", "SIPL", "FIT"}:
            raise ValueError("%s is not a valid key type" % key_type)
        nonce = self.get_nonce()
        data = json.dumps({
            "key-type": key_type,
            "description": description,
            }).encode("UTF-8")
        box = Box(self.private_key, self.service_public_key)
        encrypted_message = box.encrypt(data, nonce, encoder=Base64Encoder)
        return self._get_json(
            "/generate", "POST", headers=self._get_auth_headers(nonce),
            data=encrypted_message.ciphertext)

