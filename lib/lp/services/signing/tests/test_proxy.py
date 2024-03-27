# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import base64
import json
from datetime import datetime

import responses
from fixtures import MockPatch
from fixtures.testcase import TestWithFixtures
from nacl.encoding import Base64Encoder
from nacl.public import Box, PrivateKey, PublicKey
from nacl.utils import random
from testtools.matchers import (
    AfterPreprocessing,
    ContainsDict,
    Equals,
    MatchesDict,
    MatchesListwise,
    MatchesStructure,
)
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.services.config import config
from lp.services.signing.enums import (
    OpenPGPKeyAlgorithm,
    SigningKeyType,
    SigningMode,
)
from lp.services.signing.interfaces.signingserviceclient import (
    ISigningServiceClient,
)
from lp.services.signing.proxy import SigningServiceClient
from lp.testing import TestCaseWithFactory
from lp.testing.fixture import CaptureTimeline
from lp.testing.layers import ZopelessLayer


class SigningServiceResponseFactory:
    """Factory for fake responses from lp-signing service.

    This class is a helper to pretend that lp-signing service is running by
    mocking `requests` module, and returning fake responses from
    response.get(url) and response.post(url). See `patch` method.
    """

    def __init__(self):
        self.service_private_key = PrivateKey.generate()
        self.service_public_key = self.service_private_key.public_key
        self.b64_service_public_key = self.service_public_key.encode(
            encoder=Base64Encoder
        ).decode("UTF-8")

        self.client_private_key = PrivateKey(
            config.signing.client_private_key, encoder=Base64Encoder
        )
        self.client_public_key = self.client_private_key.public_key

        self.nonce = random(Box.NONCE_SIZE)
        self.b64_nonce = base64.b64encode(self.nonce).decode("UTF-8")

        self.response_nonce = random(Box.NONCE_SIZE)
        self.b64_response_nonce = base64.b64encode(self.response_nonce).decode(
            "UTF-8"
        )

        self.generated_public_key = PrivateKey.generate().public_key
        self.b64_generated_public_key = base64.b64encode(
            bytes(self.generated_public_key)
        ).decode("UTF-8")
        self.generated_fingerprint = "338D218488DFD597D8FCB9C328C3E9D9ADA16CEE"

        self.signed_msg_template = b"%d::signed!"

    @classmethod
    def getUrl(cls, path):
        """Shortcut to get full path of an endpoint at lp-signing."""
        return SigningServiceClient().getUrl(path)

    def _encryptPayload(self, data, nonce):
        """Translated the given data dict as a boxed json, encrypted as
        lp-signing would do."""
        box = Box(self.service_private_key, self.client_public_key)
        return box.encrypt(
            json.dumps(data).encode("UTF-8"), nonce, encoder=Base64Encoder
        ).ciphertext

    def _decryptPayload(self, value):
        """Decrypt a payload we encrypted.

        This is intended for use with `AfterPreprocessing` matchers.
        """
        box = Box(self.service_private_key, self.client_public_key)
        decrypted = box.decrypt(value, self.nonce, encoder=Base64Encoder)
        return json.loads(decrypted)

    def getAPISignedContent(self, call_index=0):
        """Returns the signed message returned by the API.

        This is a shortcut to avoid inspecting and decrypting API calls,
        since we know that the content of /sign calls are hardcoded by this
        fixture.
        """
        return self.signed_msg_template % (call_index + 1)

    def addResponses(self, test_case):
        """Patches all requests with default test values.

        This method uses `responses` module to mock `requests`. You should use
        @responses.activate decorator in your test method before
        calling this method.

        See https://github.com/getsentry/responses for details on how to
        inspect the HTTP calls made.

        Other helpful attributes are:
            - self.b64_service_public_key
            - self.b64_nonce
            - self.generated_public_key
            - self.generated_fingerprint
        which holds the respective values used in the default fake responses.

        The /sign endpoint will return, as signed message, "$n::signed!",
        where $n is the call number (base64-encoded, as lp-signing would
        return). This could be useful on black-box tests, where several
        calls to /sign would be done and the response should be checked.
        """
        # Patch SigningServiceClient._makeResponseNonce to return always the
        # same nonce, to simplify the tests.
        test_case.useFixture(
            MockPatch(
                "lp.services.signing.proxy.SigningServiceClient."
                "_makeResponseNonce",
                return_value=self.response_nonce,
            )
        )

        responses.add(
            responses.GET,
            self.getUrl("/service-key"),
            json={"service-key": self.b64_service_public_key},
            status=200,
        )

        responses.add(
            responses.POST,
            self.getUrl("/nonce"),
            json={"nonce": self.b64_nonce},
            status=201,
        )

        responses.add(
            responses.POST,
            self.getUrl("/generate"),
            body=self._encryptPayload(
                {
                    "fingerprint": self.generated_fingerprint,
                    "public-key": self.b64_generated_public_key,
                },
                nonce=self.response_nonce,
            ),
            status=201,
        )

        responses.add(
            responses.POST,
            self.getUrl("/inject"),
            body=self._encryptPayload(
                {
                    "fingerprint": self.generated_fingerprint,
                },
                nonce=self.response_nonce,
            ),
            status=200,
        )

        responses.add(
            responses.POST,
            self.getUrl("/authorizations/add"),
            body=self._encryptPayload({}, nonce=self.response_nonce),
            status=200,
        )

        call_counts = {"/sign": 0}

        def sign_callback(request):
            call_counts["/sign"] += 1
            signed_msg = self.signed_msg_template % call_counts["/sign"]
            signed = base64.b64encode(signed_msg)
            data = {
                "signed-message": signed.decode("utf8"),
                "public-key": self.b64_generated_public_key,
            }
            return 201, {}, self._encryptPayload(data, self.response_nonce)

        responses.add_callback(
            responses.POST, self.getUrl("/sign"), callback=sign_callback
        )


class SigningServiceProxyTest(TestCaseWithFactory, TestWithFixtures):
    """Tests signing service without actually making calls to lp-signing.

    Every REST call is mocked using self.response_factory, and most of this
    class's work is actually calling those endpoints. So, many things are
    mocked here, returning fake responses created at
    SigningServiceResponseFactory.
    """

    layer = ZopelessLayer

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        self.response_factory = SigningServiceResponseFactory()

        client = removeSecurityProxy(getUtility(ISigningServiceClient))
        self.addCleanup(client._cleanCaches)

        self.timeline = self.useFixture(CaptureTimeline()).timeline

    def assertTimeline(self, expected_details):
        matchers = []
        for method, path, kwargs in expected_details:
            matchers.append(
                MatchesStructure(
                    category=Equals("services-signing-proxy-%s" % method),
                    detail=AfterPreprocessing(
                        lambda detail: detail.split(" ", 1),
                        MatchesListwise(
                            [
                                Equals(path),
                                AfterPreprocessing(json.loads, Equals(kwargs)),
                            ]
                        ),
                    ),
                )
            )
        self.assertThat(self.timeline.actions, MatchesListwise(matchers))

    @responses.activate
    def test_get_service_public_key(self):
        self.response_factory.addResponses(self)

        signing = getUtility(ISigningServiceClient)
        key = removeSecurityProxy(signing.service_public_key)

        # Asserts that the public key is correct.
        self.assertIsInstance(key, PublicKey)
        self.assertEqual(
            key.encode(Base64Encoder),
            self.response_factory.b64_service_public_key.encode("UTF-8"),
        )

        # Checks that the HTTP call was made
        self.assertEqual(1, len(responses.calls))
        call = responses.calls[0]
        self.assertEqual("GET", call.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/service-key"), call.request.url
        )

        self.assertTimeline([("GET", "/service-key", {})])

    @responses.activate
    def test_get_nonce(self):
        self.response_factory.addResponses(self)

        signing = getUtility(ISigningServiceClient)
        nonce = signing.getNonce()

        self.assertEqual(
            base64.b64encode(nonce),
            self.response_factory.b64_nonce.encode("UTF-8"),
        )

        # Checks that the HTTP call was made
        self.assertEqual(1, len(responses.calls))
        call = responses.calls[0]
        self.assertEqual("POST", call.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/nonce"), call.request.url
        )

        self.assertTimeline([("POST", "/nonce", {})])

    @responses.activate
    def test_generate_unknown_key_type_raises_exception(self):
        self.response_factory.addResponses(self)

        signing = getUtility(ISigningServiceClient)
        self.assertRaises(
            ValueError, signing.generate, "banana", "Wrong key type"
        )
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_generate_key(self):
        """Makes sure that the SigningService.generate method calls the
        correct endpoints
        """
        self.response_factory.addResponses(self)
        # Generate the key, and checks if we got back the correct dict.
        signing = getUtility(ISigningServiceClient)
        generated = signing.generate(SigningKeyType.UEFI, "my lp test key")

        self.assertEqual(
            generated,
            {
                "public-key": bytes(
                    self.response_factory.generated_public_key
                ),
                "fingerprint": self.response_factory.generated_fingerprint,
            },
        )

        self.assertEqual(3, len(responses.calls))

        # expected order of HTTP calls
        http_nonce, http_service_key, http_generate = responses.calls

        self.assertEqual("POST", http_nonce.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/nonce"), http_nonce.request.url
        )

        self.assertEqual("GET", http_service_key.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/service-key"),
            http_service_key.request.url,
        )

        self.assertEqual("POST", http_generate.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/generate"),
            http_generate.request.url,
        )
        self.assertThat(
            http_generate.request.headers,
            ContainsDict(
                {
                    "Content-Type": Equals("application/x-boxed-json"),
                    "X-Client-Public-Key": Equals(
                        config.signing.client_public_key
                    ),
                    "X-Nonce": Equals(self.response_factory.b64_nonce),
                    "X-Response-Nonce": Equals(
                        self.response_factory.b64_response_nonce
                    ),
                }
            ),
        )
        self.assertThat(
            http_generate.request.body,
            AfterPreprocessing(
                self.response_factory._decryptPayload,
                MatchesDict(
                    {
                        "key-type": Equals("UEFI"),
                        "description": Equals("my lp test key"),
                    }
                ),
            ),
        )

        self.assertTimeline(
            [
                ("POST", "/nonce", {}),
                ("GET", "/service-key", {}),
                (
                    "POST",
                    "/generate",
                    {
                        "headers": {
                            "Content-Type": "application/x-boxed-json",
                            "X-Client-Public-Key": (
                                config.signing.client_public_key
                            ),
                            "X-Nonce": self.response_factory.b64_nonce,
                            "X-Response-Nonce": (
                                self.response_factory.b64_response_nonce
                            ),
                        },
                    },
                ),
            ]
        )

    @responses.activate
    def test_generate_key_openpgp_missing_algorithm(self):
        self.response_factory.addResponses(self)

        signing = getUtility(ISigningServiceClient)
        self.assertRaises(
            ValueError,
            signing.generate,
            SigningKeyType.OPENPGP,
            "Missing OpenPGP algorithm",
        )
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_generate_key_openpgp(self):
        self.response_factory.addResponses(self)
        # Generate the key, and checks if we got back the correct dict.
        signing = getUtility(ISigningServiceClient)
        generated = signing.generate(
            SigningKeyType.OPENPGP,
            "my lp test key",
            openpgp_key_algorithm=OpenPGPKeyAlgorithm.RSA,
            length=4096,
        )

        self.assertEqual(
            generated,
            {
                "public-key": bytes(
                    self.response_factory.generated_public_key
                ),
                "fingerprint": self.response_factory.generated_fingerprint,
            },
        )

        self.assertEqual(3, len(responses.calls))

        # expected order of HTTP calls
        http_nonce, http_service_key, http_generate = responses.calls

        self.assertEqual("POST", http_nonce.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/nonce"), http_nonce.request.url
        )

        self.assertEqual("GET", http_service_key.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/service-key"),
            http_service_key.request.url,
        )

        self.assertEqual("POST", http_generate.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/generate"),
            http_generate.request.url,
        )
        self.assertThat(
            http_generate.request.headers,
            ContainsDict(
                {
                    "Content-Type": Equals("application/x-boxed-json"),
                    "X-Client-Public-Key": Equals(
                        config.signing.client_public_key
                    ),
                    "X-Nonce": Equals(self.response_factory.b64_nonce),
                    "X-Response-Nonce": Equals(
                        self.response_factory.b64_response_nonce
                    ),
                }
            ),
        )
        self.assertThat(
            http_generate.request.body,
            AfterPreprocessing(
                self.response_factory._decryptPayload,
                MatchesDict(
                    {
                        "key-type": Equals("OPENPGP"),
                        "description": Equals("my lp test key"),
                        "openpgp-key-algorithm": Equals("RSA"),
                        "length": Equals(4096),
                    }
                ),
            ),
        )

        self.assertTimeline(
            [
                ("POST", "/nonce", {}),
                ("GET", "/service-key", {}),
                (
                    "POST",
                    "/generate",
                    {
                        "headers": {
                            "Content-Type": "application/x-boxed-json",
                            "X-Client-Public-Key": (
                                config.signing.client_public_key
                            ),
                            "X-Nonce": self.response_factory.b64_nonce,
                            "X-Response-Nonce": (
                                self.response_factory.b64_response_nonce
                            ),
                        },
                    },
                ),
            ]
        )

    @responses.activate
    def test_sign_invalid_mode(self):
        signing = getUtility(ISigningServiceClient)
        self.assertRaises(
            ValueError,
            signing.sign,
            SigningKeyType.UEFI,
            "fingerprint",
            "message_name",
            "message",
            "NO-MODE",
        )
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_sign_invalid_key_type(self):
        signing = getUtility(ISigningServiceClient)
        self.assertRaises(
            ValueError,
            signing.sign,
            "shrug",
            "fingerprint",
            "message_name",
            "message",
            SigningMode.ATTACHED,
        )
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_sign(self):
        """Runs through SignService.sign() flow"""
        # Replace GET /service-key response by our mock.
        resp_factory = self.response_factory
        resp_factory.addResponses(self)

        fingerprint = self.factory.getUniqueHexString(40).upper()
        key_type = SigningKeyType.KMOD
        mode = SigningMode.DETACHED
        message_name = "my test msg"
        message = b"this is the message content"

        signing = getUtility(ISigningServiceClient)
        data = signing.sign(key_type, fingerprint, message_name, message, mode)

        self.assertEqual(3, len(responses.calls))
        # expected order of HTTP calls
        http_nonce, http_service_key, http_sign = responses.calls

        self.assertEqual("POST", http_nonce.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/nonce"), http_nonce.request.url
        )

        self.assertEqual("GET", http_service_key.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/service-key"),
            http_service_key.request.url,
        )

        self.assertEqual("POST", http_sign.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/sign"), http_sign.request.url
        )
        self.assertThat(
            http_sign.request.headers,
            ContainsDict(
                {
                    "Content-Type": Equals("application/x-boxed-json"),
                    "X-Client-Public-Key": Equals(
                        config.signing.client_public_key
                    ),
                    "X-Nonce": Equals(self.response_factory.b64_nonce),
                    "X-Response-Nonce": Equals(
                        self.response_factory.b64_response_nonce
                    ),
                }
            ),
        )
        self.assertThat(
            http_sign.request.body,
            AfterPreprocessing(
                self.response_factory._decryptPayload,
                MatchesDict(
                    {
                        "key-type": Equals("KMOD"),
                        "fingerprint": Equals(fingerprint),
                        "message-name": Equals(message_name),
                        "message": Equals(
                            base64.b64encode(message).decode("UTF-8")
                        ),
                        "mode": Equals("DETACHED"),
                    }
                ),
            ),
        )

        self.assertTimeline(
            [
                ("POST", "/nonce", {}),
                ("GET", "/service-key", {}),
                (
                    "POST",
                    "/sign",
                    {
                        "headers": {
                            "Content-Type": "application/x-boxed-json",
                            "X-Client-Public-Key": (
                                config.signing.client_public_key
                            ),
                            "X-Nonce": self.response_factory.b64_nonce,
                            "X-Response-Nonce": (
                                self.response_factory.b64_response_nonce
                            ),
                        },
                    },
                ),
            ]
        )

        # It should have returned the correct JSON content, with signed
        # message from the API and the public-key.
        self.assertEqual(2, len(data))
        self.assertEqual(
            self.response_factory.getAPISignedContent(), data["signed-message"]
        )
        self.assertEqual(
            bytes(self.response_factory.generated_public_key),
            data["public-key"],
        )

    @responses.activate
    def test_inject_key(self):
        """Makes sure that the SigningService.inject method calls the
        correct endpoints, and actually injects key contents.
        """
        self.response_factory.addResponses(self)
        private_key = PrivateKey.generate()
        public_key = private_key.public_key
        now = datetime.now()

        # Generate the key, and checks if we got back the correct dict.
        signing = getUtility(ISigningServiceClient)
        response_data = signing.inject(
            SigningKeyType.UEFI,
            bytes(private_key),
            bytes(public_key),
            "This is a test key injected.",
            now,
        )

        self.assertEqual(
            response_data,
            {"fingerprint": self.response_factory.generated_fingerprint},
        )

        self.assertEqual(3, len(responses.calls))

        # expected order of HTTP calls
        http_nonce, http_service_key, http_inject = responses.calls

        self.assertEqual("POST", http_nonce.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/nonce"), http_nonce.request.url
        )

        self.assertEqual("GET", http_service_key.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/service-key"),
            http_service_key.request.url,
        )

        self.assertEqual("POST", http_inject.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/inject"), http_inject.request.url
        )
        self.assertThat(
            http_inject.request.headers,
            ContainsDict(
                {
                    "Content-Type": Equals("application/x-boxed-json"),
                    "X-Client-Public-Key": Equals(
                        config.signing.client_public_key
                    ),
                    "X-Nonce": Equals(self.response_factory.b64_nonce),
                    "X-Response-Nonce": Equals(
                        self.response_factory.b64_response_nonce
                    ),
                }
            ),
        )
        self.assertThat(
            http_inject.request.body,
            AfterPreprocessing(
                self.response_factory._decryptPayload,
                MatchesDict(
                    {
                        "key-type": Equals("UEFI"),
                        "private-key": Equals(
                            base64.b64encode(bytes(private_key)).decode(
                                "UTF-8"
                            )
                        ),
                        "public-key": Equals(
                            base64.b64encode(bytes(public_key)).decode("UTF-8")
                        ),
                        "created-at": Equals(now.isoformat()),
                        "description": Equals("This is a test key injected."),
                    }
                ),
            ),
        )

        self.assertTimeline(
            [
                ("POST", "/nonce", {}),
                ("GET", "/service-key", {}),
                (
                    "POST",
                    "/inject",
                    {
                        "headers": {
                            "Content-Type": "application/x-boxed-json",
                            "X-Client-Public-Key": (
                                config.signing.client_public_key
                            ),
                            "X-Nonce": self.response_factory.b64_nonce,
                            "X-Response-Nonce": (
                                self.response_factory.b64_response_nonce
                            ),
                        },
                    },
                ),
            ]
        )

    @responses.activate
    def test_inject_invalid_key_type(self):
        signing = getUtility(ISigningServiceClient)
        private_key = PrivateKey.generate()
        public_key = private_key.public_key

        self.assertRaises(
            ValueError,
            signing.inject,
            "shrug",
            bytes(private_key),
            bytes(public_key),
            "This is a test key injected.",
            datetime.now(),
        )
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_addAuthorization_invalid_key_type(self):
        signing = getUtility(ISigningServiceClient)
        self.assertRaises(
            ValueError,
            signing.addAuthorization,
            "shrug",
            "fingerprint",
            "test-client",
        )
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_addAuthorization(self):
        # Replace GET /service-key response by our mock.
        resp_factory = self.response_factory
        resp_factory.addResponses(self)

        fingerprint = self.factory.getUniqueHexString(40).upper()
        key_type = SigningKeyType.KMOD
        client_name = "test-client"

        signing = getUtility(ISigningServiceClient)
        self.assertIsNone(
            signing.addAuthorization(key_type, fingerprint, client_name)
        )

        self.assertEqual(3, len(responses.calls))
        # expected order of HTTP calls
        http_nonce, http_service_key, http_add_authorization = responses.calls

        self.assertEqual("POST", http_nonce.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/nonce"), http_nonce.request.url
        )

        self.assertEqual("GET", http_service_key.request.method)
        self.assertEqual(
            self.response_factory.getUrl("/service-key"),
            http_service_key.request.url,
        )
        self.assertThat(
            http_add_authorization.request.headers,
            ContainsDict(
                {
                    "Content-Type": Equals("application/x-boxed-json"),
                    "X-Client-Public-Key": Equals(
                        config.signing.client_public_key
                    ),
                    "X-Nonce": Equals(self.response_factory.b64_nonce),
                    "X-Response-Nonce": Equals(
                        self.response_factory.b64_response_nonce
                    ),
                }
            ),
        )
        self.assertThat(
            http_add_authorization.request.body,
            AfterPreprocessing(
                self.response_factory._decryptPayload,
                MatchesDict(
                    {
                        "key-type": Equals("KMOD"),
                        "fingerprint": Equals(fingerprint),
                        "client-name": Equals(client_name),
                    }
                ),
            ),
        )

        self.assertTimeline(
            [
                ("POST", "/nonce", {}),
                ("GET", "/service-key", {}),
                (
                    "POST",
                    "/authorizations/add",
                    {
                        "headers": {
                            "Content-Type": "application/x-boxed-json",
                            "X-Client-Public-Key": (
                                config.signing.client_public_key
                            ),
                            "X-Nonce": self.response_factory.b64_nonce,
                            "X-Response-Nonce": (
                                self.response_factory.b64_response_nonce
                            ),
                        },
                    },
                ),
            ]
        )
