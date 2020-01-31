# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import base64
from collections import defaultdict

import mock
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
        self.generated_public_key = (
            u'LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSURFVENDQWZtZ0F3SUJBZ0l'
            u'VZlgreHlFNUp4VVcyWVBYemVDMGtsQlZZQTBjd0RRWUpLb1pJaHZjTkFRRUwKQl'
            u'FBd0dERVdNQlFHQTFVRUF3d05WR1Z6ZENCclpYa2dWVVZHU1RBZUZ3MHlNREF4T'
            u'WpneE16UTVORGRhRncwegpNREF4TWpVeE16UTVORGRhTUJneEZqQVVCZ05WQkFN'
            u'TURWUmxjM1FnYTJWNUlGVkZSa2t3Z2dFaU1BMEdDU3FHClNJYjNEUUVCQVFVQUE'
            u'0SUJEd0F3Z2dFS0FvSUJBUURPc3Vvd3VGZllRK1g0TjVLZWtXMGxBbmMvemNrYk'
            u'5mUmEKK2hZSE56RmJDa2hMUzZYTWdOY1d5eW8rTk4rd05FN3JEcUgwc3gweUZzc'
            u'zJuVCtxWXM1WFdIYmRXMHBVNnpCTwp0bEh0MjhNQzYzWU03ZkpFZnVpM1RFRXph'
            u'R1VKOUp2dFhENG16Vkd1cGxZczVBckkvc3RvdDVHY0J6bHVuNHJnCkNHNUdtWXR'
            u'KVGw4YkpSWGFqckhMZFJJc2dIWCtXTXBKUCtnQVlnSE94M3Y5VHlXaDJMR0FnbU'
            u'MyYVFSbFE3WEoKS1ZSRzVaYTJVMlRaZ3dnYzc0SkFBNjVIQSt2Z2xtcW5SZExad'
            u'0RRTUluYjZ6djBsL0tDYkFRbldwL2hxMDB6VwoxRkVrR1k2Sm1Jb3BnR0lxTm9E'
            u'WVJOSEllWCtiVHE2eWthcUg5M0pjV2NOYlBZdEZGMUFGQWdNQkFBR2pVekJSCk1'
            u'CMEdBMVVkRGdRV0JCUXFpZXBwdkxOaWZIMjlKV3ByNk4zdmFpYzNDREFmQmdOVk'
            u'hTTUVHREFXZ0JRcWllcHAKdkxOaWZIMjlKV3ByNk4zdmFpYzNDREFQQmdOVkhST'
            u'UJBZjhFQlRBREFRSC9NQTBHQ1NxR1NJYjNEUUVCQ3dVQQpBNElCQVFCYXIzaGk5'
            u'TXFabjJ4eUh5Z3pBQzhGMFlmU2lHNm5aV09jSEJPT1QveVhMOVloTlFxL292TWZ'
            u'TUlJtCnl1SkE3eWlxcUhUU211ZDZ4QWxYZlhQYXpxaUxHSEdpMXl2dWVVOWtmOW'
            u'dHRGp2NW5Kek1YMXBLeUZLcVZjaysKZVdyVEF6S21xL2FTWFRlcFhUNVBoRU14Y'
            u'UdORHlJb3I3ck0rU2JZaWNFZGZoeEZiSTc1UWk3NERCdGlBdmZCbgpsK2JwMk1D'
            u'dDNydS81YiszYUNjRm5Pa0dXQ3I0RW1RZktzSTlYanViblJYNTFVMTVleFdsQW1'
            u'LaVNQRGd4aUcvCm5iSklYVHNUYXNqeVNuaEl0QkFQcWozdlgzRFhFZmlpVm5icH'
            u'dSbEZ4YjhQRlI5cC9hQTExdVp2VXhMYTI1TDQKSEVhdW5sRWdpRnM4Ynl5Z2hTa'
            u'GZJdU40aDZuMwotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg')
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
                  'public-key': self.generated_public_key},
            status=201)

        responses.add(
            responses.POST, self.get_url("/sign"),
            json={'signed-message': self.b64_signed_msg,
                  'public-key': self.generated_public_key},
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
        generated = signing.generate("UEFI", "my lp test key")

        self.assertEqual(generated, {
            'public-key': self.response_factory.generated_public_key,
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
            'UEFI', 'fingerprint', 'message_name', 'message', 'NO-MODE')
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
        key_type = 'KMOD'
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