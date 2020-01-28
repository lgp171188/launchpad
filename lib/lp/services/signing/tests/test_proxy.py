# Copyright 2010-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import base64

import requests
from lp.services.signing.proxy import SigningService
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessLayer
import mock
from mock import ANY
from nacl.encoding import Base64Encoder
from nacl.public import PublicKey


class SigningServiceResponseFactory:
    """Factory for fake responses from lp-signing service
    """
    def _get_mock_response(self, status_code, json):
        mock_response = mock.Mock(requests.Response)
        mock_response.status_code = status_code
        mock_response.json.return_value = json
        return mock_response

    def get_service_key(self, service_key):
        """Fake response for GET /service-key endpoint
        """
        return self._get_mock_response(200, {"service-key": service_key})

    def post_nonce(self, nonce):
        """Fake response for POST /nonce endpoint

        :param nonce: The base64-encoded nonce, as it would be returned by
                      the request
        """
        return self._get_mock_response(200, {"nonce": nonce})

    def post_generate(self, public_key, finger_print):
        """Fake response for POST /generate endpoint
        """
        return self._get_mock_response(
            200, {'fingerprint': finger_print, 'public-key': public_key})

    def patch_post_requests(self, requests_module, responses):
        """Patch the fake "requests module" to return the given responses
        when certain endpoints are called

        """
        def side_effect(url, *args, **kwags):
            for endpoint, response in responses.items():
                if url.endswith(endpoint):
                    return response
            return mock.Mock()
        requests_module.post.side_effect = side_effect
        return requests_module


@mock.patch("lp.services.signing.proxy.requests")
class SigningServiceProxyTest(TestCaseWithFactory):
    """Tests signing service without actually making calls to lp-signing
    """
    layer = ZopelessLayer

    def setUp(self, *args, **kwargs):
        super(TestCaseWithFactory, self).setUp(*args, **kwargs)
        self.response_factory = SigningServiceResponseFactory()

    def test_get_service_public_key(self, mock_requests):
        base64_public_key = "x7vTtpmn0+DvKNdmtf047fn1JRQI5eMnOQRy3xJ1m10="
        mock_response = self.response_factory.get_service_key(
            base64_public_key)
        mock_requests.get.return_value = mock_response

        signing = SigningService()
        key = signing.service_public_key

        # Asserts that the public key is correct.
        self.assertIsInstance(key, PublicKey)
        self.assertEqual(key.encode(Base64Encoder), base64_public_key)

        # Asserts that the endpoint was called
        mock_requests.get.assert_called_once_with(
            signing.LP_SIGNING_ADDRESS + "/service-key")

    def test_get_nonce(self, mock_requests):
        # Server returns base64-encoded nonce, but the
        # SigningService.get_nonce method returns it already decoded
        base64_nonce = "neSSa2MUZlQU3XiipU2TfiaqW5nrVUpR"
        mock_response = self.response_factory.post_nonce(base64_nonce)
        mock_requests.post.return_value = mock_response

        signing = SigningService()
        nonce = signing.get_nonce()

        self.assertEqual(base64.b64encode(nonce), base64_nonce)

    def test_generate_unknown_key_type_raises_exception(self, mock_requests):
        signing = SigningService()
        self.assertRaises(
            ValueError, signing.generate, "banana", "Wrong key type")
        self.assertEqual(0, mock_requests.get.call_count)
        self.assertEqual(0, mock_requests.post.call_count)

    def test_generate_key(self, mock_requests):
        """Makes sure that the SigningService.generate method calls the
        correct endpoints

        This method is actually mocking a lot of things because most of the
        things are already unit-tested
        """
        b64_nonce = "neSSa2MUZlQU3XiipU2TfiaqW5nrVUpR"
        mock_nonce_response = self.response_factory.post_nonce(b64_nonce)

        public_key = (
            'LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSURFVENDQWZtZ0F3SUJBZ0l'
            'VZlgreHlFNUp4VVcyWVBYemVDMGtsQlZZQTBjd0RRWUpLb1pJaHZjTkFRRUwKQl'
            'FBd0dERVdNQlFHQTFVRUF3d05WR1Z6ZENCclpYa2dWVVZHU1RBZUZ3MHlNREF4T'
            'WpneE16UTVORGRhRncwegpNREF4TWpVeE16UTVORGRhTUJneEZqQVVCZ05WQkFN'
            'TURWUmxjM1FnYTJWNUlGVkZSa2t3Z2dFaU1BMEdDU3FHClNJYjNEUUVCQVFVQUE'
            '0SUJEd0F3Z2dFS0FvSUJBUURPc3Vvd3VGZllRK1g0TjVLZWtXMGxBbmMvemNrYk'
            '5mUmEKK2hZSE56RmJDa2hMUzZYTWdOY1d5eW8rTk4rd05FN3JEcUgwc3gweUZzc'
            'zJuVCtxWXM1WFdIYmRXMHBVNnpCTwp0bEh0MjhNQzYzWU03ZkpFZnVpM1RFRXph'
            'R1VKOUp2dFhENG16Vkd1cGxZczVBckkvc3RvdDVHY0J6bHVuNHJnCkNHNUdtWXR'
            'KVGw4YkpSWGFqckhMZFJJc2dIWCtXTXBKUCtnQVlnSE94M3Y5VHlXaDJMR0FnbU'
            'MyYVFSbFE3WEoKS1ZSRzVaYTJVMlRaZ3dnYzc0SkFBNjVIQSt2Z2xtcW5SZExad'
            '0RRTUluYjZ6djBsL0tDYkFRbldwL2hxMDB6VwoxRkVrR1k2Sm1Jb3BnR0lxTm9E'
            'WVJOSEllWCtiVHE2eWthcUg5M0pjV2NOYlBZdEZGMUFGQWdNQkFBR2pVekJSCk1'
            'CMEdBMVVkRGdRV0JCUXFpZXBwdkxOaWZIMjlKV3ByNk4zdmFpYzNDREFmQmdOVk'
            'hTTUVHREFXZ0JRcWllcHAKdkxOaWZIMjlKV3ByNk4zdmFpYzNDREFQQmdOVkhST'
            'UJBZjhFQlRBREFRSC9NQTBHQ1NxR1NJYjNEUUVCQ3dVQQpBNElCQVFCYXIzaGk5'
            'TXFabjJ4eUh5Z3pBQzhGMFlmU2lHNm5aV09jSEJPT1QveVhMOVloTlFxL292TWZ'
            'TUlJtCnl1SkE3eWlxcUhUU211ZDZ4QWxYZlhQYXpxaUxHSEdpMXl2dWVVOWtmOW'
            'dHRGp2NW5Kek1YMXBLeUZLcVZjaysKZVdyVEF6S21xL2FTWFRlcFhUNVBoRU14Y'
            'UdORHlJb3I3ck0rU2JZaWNFZGZoeEZiSTc1UWk3NERCdGlBdmZCbgpsK2JwMk1D'
            'dDNydS81YiszYUNjRm5Pa0dXQ3I0RW1RZktzSTlYanViblJYNTFVMTVleFdsQW1'
            'LaVNQRGd4aUcvCm5iSklYVHNUYXNqeVNuaEl0QkFQcWozdlgzRFhFZmlpVm5icH'
            'dSbEZ4YjhQRlI5cC9hQTExdVp2VXhMYTI1TDQKSEVhdW5sRWdpRnM4Ynl5Z2hTa'
            'GZJdU40aDZuMwotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg')
        fingerprint = '338D218488DFD597D8FCB9C328C3E9D9ADA16CEE'
        mock_generate_response = self.response_factory.post_generate(
            public_key, fingerprint)

        # Replace /nonce and /generate responses by our mocks
        self.response_factory.patch_post_requests(
            mock_requests, {"/nonce": mock_nonce_response,
                            "/generate": mock_generate_response})

        # Mock fetching service public key
        b64_service_pub_key = (
            "x7vTtpmn0+DvKNdmtf047fn1JRQI5eMnOQRy3xJ1m10=")
        mock_pub_key_response = self.response_factory.get_service_key(
            b64_service_pub_key)
        mock_requests.get.return_value = mock_pub_key_response

        # Generate the key, and checks if we got back the correct dict
        signing = SigningService()
        generated = signing.generate("UEFI", "my lp test key")

        self.assertEqual(generated, {
            'public-key': public_key, 'fingerprint': fingerprint})

        # Asserts it tried to fetch service key, fetched the nonce and posted
        # to the /generate endpoint
        mock_requests.get.assert_called_once_with(
            signing.LP_SIGNING_ADDRESS + "/service-key")
        mock_nonce_response.json.assert_called_with()
        mock_generate_response.json.assert_called_with()

        mock_requests.post.assert_called_with(
            signing.LP_SIGNING_ADDRESS + "/generate",
            headers={
                "Content-Type": "application/x-boxed-json",
                "X-Client-Public-Key": signing.LOCAL_PUBLIC_KEY,
                "X-Nonce": b64_nonce
            },
            data=ANY)  # XXX: check the encrypted data

