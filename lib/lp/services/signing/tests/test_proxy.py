# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import base64
from collections import defaultdict

import mock
from lp.services.signing.enums import SigningKeyType
from mock import ANY
from nacl.encoding import Base64Encoder
from nacl.public import PublicKey
import requests
import responses

from lp.services.signing.proxy import SigningService
from lp.testing import TestCaseWithFactory
from lp.testing.layers import BaseLayer


class SigningServiceResponseFactory:
    """Factory for fake responses from lp-signing service.

    This class is a helper to pretend that lp-signing service is running by
    mocking `requests` module, and returning fake responses from
    response.get(url) and response.post(url). See `patch` method.
    """
    def __init__(self):
        self.base64_service_public_key = (
            u"x7vTtpmn0+DvKNdmtf047fn1JRQI5eMnOQRy3xJ1m10=")
        self.base64_nonce = u"neSSa2MUZlQU3XiipU2TfiaqW5nrVUpR"
        self.b64_generated_public_key = (
            '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')
        self.generated_fingerprint = (
            u'338D218488DFD597D8FCB9C328C3E9D9ADA16CEE')
        self.b64_signed_msg = base64.b64encode("the-signed-msg")

    @classmethod
    def get_url(cls, path):
        """Shortcut to get full path of an endpoint at lp-signing.
        """
        return SigningService().get_url(path)

    def patch(self):
        """Patches all requests with default test values.

        This method uses `responses` module to mock `requests`. You should use
        @responses.activate decorator in your test method before
        calling this method.

        See https://github.com/getsentry/responses for details on how to
        inspect the HTTP calls made.

        Other helpful attributes are:
            - self.base64_service_public_key
            - self.base64_nonce
            - self.generated_public_key
            - self.generated_fingerprint
            - self.base64_signed_msg
        which holds the respective values used in the default fake responses.
        """
        responses.add(
            responses.GET, self.get_url("/service-key"),
            json={"service-key": self.base64_service_public_key}, status=200)

        responses.add(
            responses.POST, self.get_url("/nonce"),
            json={"nonce": self.base64_nonce}, status=201)

        responses.add(
            responses.POST, self.get_url("/generate"),
            json={'fingerprint': self.generated_fingerprint,
                  'public-key': self.b64_generated_public_key},
            status=201)

        responses.add(
            responses.POST, self.get_url("/sign"),
            json={'signed-message': self.b64_signed_msg,
                  'public-key': self.b64_generated_public_key},
            status=201)


class SigningServiceProxyTest(TestCaseWithFactory):
    """Tests signing service without actually making calls to lp-signing.

    Every REST call is mocked using self.response_factory, and most of this
    class's work is actually calling those endpoints. So, many things are
    mocked here, returning fake responses created at
    SigningServiceResponseFactory.
    """
    layer = BaseLayer

    def setUp(self, *args, **kwargs):
        super(TestCaseWithFactory, self).setUp(*args, **kwargs)
        self.response_factory = SigningServiceResponseFactory()

    def assertHeaderContains(self, request, headers):
        """Checks if the request's header contains the headers dictionary
        provided

        :param request: The requests.Request object
        :param headers: Dictionary of expected headers
        """
        missing_headers = []
        # List of tuples like (header key, got, expected)
        different_headers = []
        for k, v in headers.items():
            if k not in request.headers:
                missing_headers.append(k)
                continue
            if v != request.headers[k]:
                different_headers.append((k, request.headers[k], v))
                continue
        failure_msgs = []
        if missing_headers:
            text = ", ".join(missing_headers)
            failure_msgs.append("Missing headers: %s" % text)
        if different_headers:
            text = "; ".join(
                "Header '%s': [got: %s / expected: %s]" % (k, got, expected)
                for k, got, expected in different_headers)
            failure_msgs.append(text)
        if failure_msgs:
            text = "\n".join(failure_msgs)
            self.fail(
                "Request header does not contain expected items:\n%s" % text)

    @responses.activate
    def test_get_service_public_key(self):
        self.response_factory.patch()

        signing = SigningService()
        key = signing.service_public_key

        # Asserts that the public key is correct.
        self.assertIsInstance(key, PublicKey)
        self.assertEqual(
            key.encode(Base64Encoder),
            self.response_factory.base64_service_public_key)

        # Checks that the HTTP call was made
        self.assertEqual(1, len(responses.calls))
        call = responses.calls[0]
        self.assertEqual("GET", call.request.method)
        self.assertEqual(
            self.response_factory.get_url("/service-key"), call.request.url)

    @responses.activate
    def test_get_nonce(self):
        self.response_factory.patch()

        signing = SigningService()
        nonce = signing.get_nonce()

        self.assertEqual(
            base64.b64encode(nonce), self.response_factory.base64_nonce)

        # Checks that the HTTP call was made
        self.assertEqual(1, len(responses.calls))
        call = responses.calls[0]
        self.assertEqual("POST", call.request.method)
        self.assertEqual(
            self.response_factory.get_url("/nonce"), call.request.url)

    @responses.activate
    def test_generate_unknown_key_type_raises_exception(self):
        self.response_factory.patch()

        signing = SigningService()
        self.assertRaises(
            ValueError, signing.generate, "banana", "Wrong key type")
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_generate_key(self):
        """Makes sure that the SigningService.generate method calls the
        correct endpoints
        """
        self.response_factory.patch()
        # Generate the key, and checks if we got back the correct dict.
        signing = SigningService()
        generated = signing.generate(SigningKeyType.UEFI, "my lp test key")

        self.assertEqual(generated, {
            'public-key': self.response_factory.b64_generated_public_key,
            'fingerprint': self.response_factory.generated_fingerprint})

        self.assertEqual(3, len(responses.calls))

        # expected order of HTTP calls
        http_nonce, http_service_key, http_generate = responses.calls

        self.assertEqual("POST", http_nonce.request.method)
        self.assertEqual(
            self.response_factory.get_url("/nonce"), http_nonce.request.url)

        self.assertEqual("GET", http_service_key.request.method)
        self.assertEqual(
            self.response_factory.get_url("/service-key"),
            http_service_key.request.url)

        self.assertEqual("POST", http_generate.request.method)
        self.assertEqual(
            self.response_factory.get_url("/generate"),
            http_generate.request.url)
        self.assertHeaderContains(http_generate.request, {
            "Content-Type": "application/x-boxed-json",
            "X-Client-Public-Key": signing.LOCAL_PUBLIC_KEY,
            "X-Nonce": self.response_factory.base64_nonce})
        self.assertIsNotNone(http_generate.request.body)

    @responses.activate
    def test_sign_invalid_mode(self):
        signing = SigningService()
        self.assertRaises(
            ValueError, signing.sign,
            SigningKeyType.UEFI, 'fingerprint', 'message_name', 'message',
            'NO-MODE')
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_sign_invalid_key_type(self):
        signing = SigningService()
        self.assertRaises(
            ValueError, signing.sign,
            'shrug', 'fingerprint', 'message_name', 'message', 'ATTACHED')
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_sign(self):
        """Runs through SignService.sign() flow"""
        # Replace GET /service-key response by our mock.
        resp_factory = self.response_factory
        resp_factory.patch()

        fingerprint = '338D218488DFD597D8FCB9C328C3E9D9ADA16CEE'
        key_type = SigningKeyType.KMOD
        mode = 'DETACHED'
        message_name = 'my test msg'
        message = 'this is the message content'

        signing = SigningService()
        data = signing.sign(
            key_type, fingerprint, message_name, message, mode)

        self.assertEqual(3, len(responses.calls))
        # expected order of HTTP calls
        http_nonce, http_service_key, http_sign = responses.calls

        self.assertEqual("POST", http_nonce.request.method)
        self.assertEqual(
            self.response_factory.get_url("/nonce"), http_nonce.request.url)

        self.assertEqual("GET", http_service_key.request.method)
        self.assertEqual(
            self.response_factory.get_url("/service-key"),
            http_service_key.request.url)

        self.assertEqual("POST", http_sign.request.method)
        self.assertEqual(
            self.response_factory.get_url("/sign"),
            http_sign.request.url)
        self.assertHeaderContains(http_sign.request, {
            "Content-Type": "application/x-boxed-json",
            "X-Client-Public-Key": signing.LOCAL_PUBLIC_KEY,
            "X-Nonce": self.response_factory.base64_nonce})
        self.assertIsNotNone(http_sign.request.body)

        # It should have returned the values from response.json(),
        # but decoding what is base64-encoded.
        self.assertEqual(2, len(data))
        resp_json = http_sign.response.json()
        self.assertEqual(data['public-key'], resp_json['public-key'])
        self.assertEqual(
            data['signed-message'],
            base64.b64decode(resp_json['signed-message']))