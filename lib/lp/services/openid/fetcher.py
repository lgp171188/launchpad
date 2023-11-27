# Copyright 2009-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OpenID consumer configuration."""

__all__ = [
    "set_default_openid_fetcher",
]

import os.path
from functools import partial
from urllib.request import urlopen

from openid.fetchers import Urllib2Fetcher, setDefaultFetcher

from lp.services.config import config
from lp.services.encoding import wsgi_native_string


class WSGIFriendlyUrllib2Fetcher(Urllib2Fetcher):
    def fetch(self, url, body=None, headers=None):
        if headers is not None:
            headers = {
                wsgi_native_string(key): wsgi_native_string(value)
                for key, value in headers.items()
            }
        return super().fetch(url, body=body, headers=headers)


def set_default_openid_fetcher():
    # Make sure we're using the same fetcher that we use in production, even
    # if pycurl is installed.
    fetcher = WSGIFriendlyUrllib2Fetcher()
    if config.launchpad.enable_test_openid_provider:
        # Tests have an instance name that looks like 'testrunner-appserver'
        # or similar. We're in 'development' there, so just use that config.
        if config.instance_name.startswith("testrunner"):
            instance_name = "development"
        else:
            instance_name = config.instance_name
        cert_path = f"configs/{instance_name}/launchpad.crt"
        cafile = os.path.join(config.root, cert_path)
        fetcher.urlopen = partial(urlopen, cafile=cafile)
    setDefaultFetcher(fetcher)
