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
        self.base64_nonce = "neSSa2MUZlQU3XiipU2TfiaqW5nrVUpR"
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

        """self.latest_response is a Structure like:
         {
            "GET": {
                "/service-key": mock_response1,
            },
            "POST": {
                "/nonce": mock_response2
            }
        }
        """
        self.latest_responses = defaultdict(dict)

    def get_latest_json_response(self, method, endpoint):
        """Returns the latest JSON response for the given HTTP method and
        endpoint.
        """
        method = method.upper()
        resp = self.get_latest_response(method, endpoint)
        if resp is None:
            return None
        return resp.json.return_value

    def get_latest_response(self, method, endpoint):
        """Returns the latest response object for the given HTTP method and
        endpoint.
        """
        return self.latest_responses.get(method, {}).get(endpoint)

    def _get_mock_response(self, status_code, json):
        mock_response = mock.Mock(requests.Response)
        mock_response.status_code = status_code
        mock_response.json.return_value = json
        return mock_response

    def get_service_key(self, service_key):
        """Fake response for GET /service-key endpoint.
        """
        return self._get_mock_response(200, {"service-key": service_key})

    def post_nonce(self, nonce):
        """Fake response for POST /nonce endpoint.

        :param nonce: The base64-encoded nonce, as it would be returned by
                      the request.
        """
        return self._get_mock_response(200, {"nonce": nonce})

    def post_generate(self, public_key, finger_print):
        """Fake response for POST /generate endpoint.
        """
        return self._get_mock_response(
            200, {'fingerprint': finger_print, 'public-key': public_key})

    def post_sign(self, signed_message, public_key):
        b64_signed_msg = base64.b64encode(signed_message)
        return self._get_mock_response(
            200, {'signed-message': b64_signed_msg, 'public-key': public_key})

    def patch_requests(self, requests_module, method, responses):
        """Patch the mock "requests module" to return the given responses
        when certain endpoints are called.

        :param requests_module: The result of @mock.patch("requests"),
                                to be patched.
        :param method: HTTP method beign patched (GET or POST, for example)
        :param responses: A dict where keys are the endpoints and the values
                          are the mock requests.Response objects. E.g.:
                          {"/sign": mock.Mock(requests.Response), ...}
        """
        def side_effect(url, *args, **kwags):
            for endpoint, response in responses.items():
                if url.endswith(endpoint):
                    self.latest_responses[method.upper()][endpoint] = response
                    return response
            return mock.Mock()
        method = method.lower()
        requests_method = getattr(requests_module, method)
        requests_method.side_effect = side_effect
        return requests_module

    def patch(self, requests_module):
        """Patches all requests with default test values.

        This method gets a `requests` module mock, and sets the responses as
        if they were real calls to lp-signing. You can inspect the responses
        and called methods using some helpers provided by this class.

        The mock responses are available using self.get_latest_json_response
        and self.get_latest_response. Both methods receives the HTTP
        method and the endpoint (e.g. ("GET", "/service-key").

        You can easily checked if an API call was actually made by
        checking if the above mock_response.json was called or is None,
        for example.

        Other helpful attributes are:
            self.base64_service_public_key
            self.base64_nonce
            self.generated_public_key
            self.generated_fingerprint
        which holds the respective values used in the fake responses

        :param requests_module: The mock of `requests` module, patched with
                                mock.patch.
        """
        # HTTP GET responses
        get_service_key_response = self.get_service_key(
            self.base64_service_public_key)
        get_responses = {"/service-key": get_service_key_response}
        self.patch_requests(requests_module, "GET", get_responses)

        post_nonce_response = self.post_nonce(self.base64_nonce)
        post_generate_response = self.post_generate(
            self.generated_public_key, self.generated_fingerprint)

        post_sign_response = self.post_sign(
            'the-signed-msg', 'the-public-key')

        # Replace POST /nonce, /generate and /sign responses by our mocks.
        self.patch_requests(
            requests_module, "POST", {
                "/nonce": post_nonce_response,
                "/generate": post_generate_response,
                "/sign": post_sign_response})



@mock.patch("lp.services.signing.proxy.requests")
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

    def test_get_service_public_key(self, mock_requests):
        self.response_factory.patch(mock_requests)

        signing = SigningService()
        key = signing.service_public_key

        # Asserts that the public key is correct.
        self.assertIsInstance(key, PublicKey)
        self.assertEqual(
            key.encode(Base64Encoder),
            self.response_factory.base64_service_public_key)

        # Asserts that the endpoint was called.
        mock_requests.get.assert_called_once_with(
            signing.LP_SIGNING_ADDRESS + "/service-key")

    def test_get_nonce(self, mock_requests):
        # Server returns base64-encoded nonce, but the
        # SigningService.get_nonce method returns it already decoded.
        self.response_factory.patch(mock_requests)

        signing = SigningService()
        nonce = signing.get_nonce()

        self.assertEqual(
            base64.b64encode(nonce), self.response_factory.base64_nonce)

    def test_generate_unknown_key_type_raises_exception(self, mock_requests):
        signing = SigningService()
        self.assertRaises(
            ValueError, signing.generate, "banana", "Wrong key type")
        self.assertEqual(0, mock_requests.get.call_count)
        self.assertEqual(0, mock_requests.post.call_count)

    def test_generate_key(self, mock_requests):
        """Makes sure that the SigningService.generate method calls the
        correct endpoints
        """
        self.response_factory.patch(mock_requests)
        # Generate the key, and checks if we got back the correct dict.
        signing = SigningService()
        generated = signing.generate("UEFI", "my lp test key")

        self.assertEqual(generated, {
            'public-key': self.response_factory.generated_public_key,
            'fingerprint': self.response_factory.generated_fingerprint})

        # Asserts it tried to fetch service key, fetched the nonce and posted
        # to the /generate endpoint.
        mock_requests.get.assert_called_once_with(
            signing.LP_SIGNING_ADDRESS + "/service-key")

        responses = self.response_factory
        self.assertIsNotNone(
            responses.get_latest_json_response("POST", "/nonce"))
        self.assertIsNotNone(
            responses.get_latest_json_response("POST", "/generate"))

        mock_requests.post.assert_called_with(
            signing.LP_SIGNING_ADDRESS + "/generate",
            headers={
                "Content-Type": "application/x-boxed-json",
                "X-Client-Public-Key": signing.LOCAL_PUBLIC_KEY,
                "X-Nonce": self.response_factory.base64_nonce
            },
            data=ANY)  # XXX: check the encrypted data.

    def test_sign_invalid_mode(self, mock_requests):
        signing = SigningService()
        self.assertRaises(
            ValueError, signing.sign,
            'UEFI', 'fingerprint', 'message_name', 'message', 'NO-MODE')
        self.assertEqual(0, mock_requests.get.call_count)
        self.assertEqual(0, mock_requests.post.call_count)

    def test_sign_invalid_key_type(self, mock_requests):
        signing = SigningService()
        self.assertRaises(
            ValueError, signing.sign,
            'shrug', 'fingerprint', 'message_name', 'message', 'ATTACHED')
        self.assertEqual(0, mock_requests.get.call_count)
        self.assertEqual(0, mock_requests.post.call_count)

    def test_sign(self, mock_requests):
        """Runs through SignService.sign() flow"""
        # Replace GET /service-key response by our mock.
        resp_factory = self.response_factory
        resp_factory.patch(mock_requests)

        fingerprint = '338D218488DFD597D8FCB9C328C3E9D9ADA16CEE'
        key_type = 'KMOD'
        mode = 'DETACHED'
        message_name = 'my test msg'
        message = 'this is the message content'

        signing = SigningService()
        data = signing.sign(
            key_type, fingerprint, message_name, message, mode)

        # It should have returned the values from response.json(),
        # but decoding what is base64-encoded.
        resp_json = resp_factory.get_latest_json_response("POST", "/sign")
        self.assertEqual(2, len(data))
        self.assertEqual(data['public-key'], resp_json['public-key'])
        self.assertEqual(
            data['signed-message'],
            base64.b64decode(resp_json['signed-message']))

        self.assertIsNotNone(
            resp_factory.get_latest_response("POST", "/nonce"))
        self.assertIsNotNone(
            resp_factory.get_latest_response("POST", "/sign"))

        mock_requests.post.assert_called_with(
            signing.LP_SIGNING_ADDRESS + "/sign",
            headers={
                "Content-Type": "application/x-boxed-json",
                "X-Client-Public-Key": signing.LOCAL_PUBLIC_KEY,
                "X-Nonce": resp_factory.base64_nonce
            },
            data=ANY)  # XXX: check the encrypted data.