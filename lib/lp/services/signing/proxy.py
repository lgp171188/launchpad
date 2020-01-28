# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Proxy calls to lp-signing service"""

from __future__ import division

__metaclass__ = type

import requests


class SigningServiceException(Exception):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('response', None)
        super(SigningServiceException, self).__init__(*args, **kwargs)


class SigningService:
    # XXX: Move it to configuration
    LP_SIGNING_ADDRESS = "http://signing.launchpad.test:8000"

    def __init__(self):
        pass

    def get_url(self, path):
        """Shotcut to concatenate LP_SIGNING_ADDRESS with the desired
        endpoint path

        :param path: The REST endpoint to be joined"""
        return self.LP_SIGNING_ADDRESS + path

    def _get_json(self, path):
        response = requests.get(self.get_url("/service-key"))
        if response.status_code // 100 != 2:
            raise SigningServiceException(
                "Error on GET %s: %s" % (path, response.content),
                response=response)
        return response.json()

    def get_service_public_key(self):
        """Returns the lp-signing service's public key"""
        json = self._get_json("/service-key")
        return json['service-key']