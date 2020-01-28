# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Proxy calls to lp-signing service"""

from __future__ import division

__metaclass__ = type

import base64

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

    def _get_json(self, path, method="GET", payload=None):
        """Helper method to do an HTTP request and get back a json from  the
        signing service, raising exception if status code != 200
        """
        url = self.get_url(path)
        if method == "GET":
            response = requests.get(url)
        elif method == "POST":
            response = requests.post(url, data=payload)
        else:
            raise NotImplemented("Only GET and POST are allowed for now")

        response.raise_for_status()
        return response.json()

    @cachedproperty
    def service_public_key(self):
        """Returns the lp-signing service's public key"""
        json = self._get_json("/service-key")
        return PublicKey(json["service-key"], encoder=Base64Encoder)

    def get_nonce(self):
        json = self._get_json("/nonce", "POST")
        return base64.b64decode(json["nonce"].encode("UTF-8"))

