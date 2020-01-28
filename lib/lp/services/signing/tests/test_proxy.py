# Copyright 2010-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import requests
from lp.services.signing.proxy import SigningService
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessLayer
import mock


@mock.patch("lp.services.signing.proxy.requests")
class SigningServiceProxyTest(TestCaseWithFactory):
    layer = ZopelessLayer

    def test_get_service_public_key(self, mock_requests):
        mock_response = mock.Mock(requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'service-key': 'test-foo'}
        mock_requests.get.return_value = mock_response

        signing = SigningService()
        key = signing.get_service_public_key()

        self.assertEqual("test-foo", key)
        mock_requests.get.assert_called_once_with(
            signing.LP_SIGNING_ADDRESS + "/service-key")
