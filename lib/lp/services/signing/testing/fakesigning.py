# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Twisted resources implementing a fake signing service."""

__all__ = [
    "SigningServiceResource",
]

import base64
import json
import os

from nacl.encoding import Base64Encoder
from nacl.public import Box, PrivateKey, PublicKey
from nacl.utils import random
from twisted.web import resource


class ServiceKeyResource(resource.Resource):
    """Resource implementing /service-key."""

    isLeaf = True

    def __init__(self, service_public_key):
        super().__init__()
        self.service_public_key = service_public_key

    def render_GET(self, request):
        request.setHeader(b"Content-Type", b"application/json")
        return json.dumps(
            {
                "service-key": self.service_public_key.encode(
                    encoder=Base64Encoder
                ).decode("UTF-8"),
            }
        ).encode("UTF-8")


class NonceResource(resource.Resource):
    """Resource implementing /nonce.

    Note that this fake signing service does not check that nonces are only
    used once.
    """

    isLeaf = True

    def __init__(self):
        super().__init__()
        self.nonces = []

    def render_POST(self, request):
        nonce = base64.b64encode(random(Box.NONCE_SIZE)).decode("UTF-8")
        self.nonces.append(nonce)
        request.setHeader(b"Content-Type", b"application/json")
        return json.dumps({"nonce": nonce}).encode("UTF-8")


class BoxedAuthenticationResource(resource.Resource):
    """Base for resources that use boxed authentication."""

    def __init__(self, service_private_key, client_public_key):
        super().__init__()
        self.box = Box(service_private_key, client_public_key)

    def _decrypt(self, request):
        """Authenticate and decrypt request data."""
        nonce = base64.b64decode(request.getHeader(b"X-Nonce"))
        return self.box.decrypt(
            request.content.read(), nonce, encoder=Base64Encoder
        )

    def _encrypt(self, request, data):
        """Encrypt and authenticate response data."""
        nonce = base64.b64decode(request.getHeader(b"X-Response-Nonce"))
        request.setHeader(b"Content-Type", b"application/x-boxed-json")
        return self.box.encrypt(data, nonce, encoder=Base64Encoder).ciphertext


class GenerateResource(BoxedAuthenticationResource):
    """Resource implementing /generate."""

    isLeaf = True

    def __init__(self, service_private_key, client_public_key, keys):
        super().__init__(service_private_key, client_public_key)
        self.keys = keys
        self.requests = []

    def render_POST(self, request):
        payload = json.loads(self._decrypt(request))
        self.requests.append(payload)
        # We don't need to bother with generating a real key here.  Just
        # make up some random data.
        private_key = random()
        public_key = random()
        fingerprint = base64.b64encode(random()).decode("UTF-8")
        self.keys[fingerprint] = (private_key, public_key)
        response_payload = {
            "fingerprint": fingerprint,
            "public-key": base64.b64encode(public_key).decode("UTF-8"),
        }
        return self._encrypt(
            request, json.dumps(response_payload).encode("UTF-8")
        )


class SignResource(BoxedAuthenticationResource):
    """Resource implementing /sign."""

    isLeaf = True

    def __init__(self, service_private_key, client_public_key, keys):
        super().__init__(service_private_key, client_public_key)
        self.keys = keys
        self.requests = []

    def render_POST(self, request):
        payload = json.loads(self._decrypt(request))
        self.requests.append(payload)
        _, public_key = self.keys[payload["fingerprint"]]
        # We don't need to bother with generating a real signature here.
        # Just make up some random data.
        signed_message = random()
        response_payload = {
            "public-key": base64.b64encode(public_key).decode("UTF-8"),
            "signed-message": base64.b64encode(signed_message).decode("UTF-8"),
        }
        return self._encrypt(
            request, json.dumps(response_payload).encode("UTF-8")
        )


class InjectResource(BoxedAuthenticationResource):
    """Resource implementing /inject."""

    isLeaf = True

    def __init__(self, service_private_key, client_public_key, keys):
        super().__init__(service_private_key, client_public_key)
        self.keys = keys
        self.requests = []

    def render_POST(self, request):
        payload = json.loads(self._decrypt(request))
        self.requests.append(payload)
        private_key = base64.b64decode(payload["private-key"].encode("UTF-8"))
        public_key = base64.b64decode(payload["public-key"].encode("UTF-8"))
        # We don't need to bother with generating a real fingerprint here.
        # Just make up some random data.
        fingerprint = base64.b64encode(random()).decode("UTF-8")
        self.keys[fingerprint] = (private_key, public_key)
        response_payload = {"fingerprint": fingerprint}
        return self._encrypt(
            request, json.dumps(response_payload).encode("UTF-8")
        )


class SigningServiceResource(resource.Resource):
    """Root resource for the fake signing service."""

    def __init__(self):
        resource.Resource.__init__(self)
        self.service_private_key = PrivateKey.generate()
        self.client_public_key = PublicKey(
            os.environ["FAKE_SIGNING_CLIENT_PUBLIC_KEY"], encoder=Base64Encoder
        )
        self.keys = {}
        self.putChild(
            b"service-key",
            ServiceKeyResource(self.service_private_key.public_key),
        )
        self.putChild(b"nonce", NonceResource())
        self.putChild(
            b"generate",
            GenerateResource(
                self.service_private_key, self.client_public_key, self.keys
            ),
        )
        self.putChild(
            b"sign",
            SignResource(
                self.service_private_key, self.client_public_key, self.keys
            ),
        )
        self.putChild(
            b"inject",
            InjectResource(
                self.service_private_key, self.client_public_key, self.keys
            ),
        )
