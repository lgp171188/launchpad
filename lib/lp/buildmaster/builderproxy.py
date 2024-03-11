# Copyright 2015-2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Builder proxy support.

Some build types require general internet access; others require that
general internet access not be available (for reproducibility, auditability,
and so on).  To resolve this dilemma, the build farm may include an
authenticated proxy; we provide builds with the necessary authentication
token if and only if they are allowed general internet access.
"""

__all__ = [
    "BuilderProxyMixin",
]

import base64
import time
from typing import Dict, Generator

from twisted.internet import defer

from lp.buildmaster.downloader import (
    RequestFetchServiceSessionCommand,
    RequestProxyTokenCommand,
)
from lp.buildmaster.interfaces.builder import CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import BuildArgs
from lp.services.config import config


def _get_proxy_config(name):
    """Get a config item from builddmaster (current) or snappy (deprecated)."""
    return getattr(config.builddmaster, name) or getattr(config.snappy, name)


def _get_value_from_config(key: str):
    value = _get_proxy_config(key)
    if not value:
        raise CannotBuild(f"{key} is not configured.")
    return value


class BuilderProxyMixin:
    """Methods for handling builds with the Snap Build Proxy enabled."""

    @defer.inlineCallbacks
    def addProxyArgs(
        self,
        args: BuildArgs,
        allow_internet: bool = True,
        fetch_service: bool = False,
    ) -> Generator[None, Dict[str, str], None]:
        if not allow_internet:
            return
        if not fetch_service and _get_proxy_config("builder_proxy_host"):
            token = yield self._requestProxyToken()
            args["proxy_url"] = (
                "http://{username}:{password}@{host}:{port}".format(
                    username=token["username"],
                    password=token["secret"],
                    host=_get_proxy_config("builder_proxy_host"),
                    port=_get_proxy_config("builder_proxy_port"),
                )
            )
            args["revocation_endpoint"] = "{endpoint}/{token}".format(
                endpoint=_get_proxy_config("builder_proxy_auth_api_endpoint"),
                token=token["username"],
            )
        elif fetch_service and _get_proxy_config("fetch_service_host"):
            session = yield self._requestFetchServiceSession()
            args["proxy_url"] = (
                "http://{session_id}:{token}@{host}:{port}".format(
                    session_id=session["id"],
                    token=session["token"],
                    host=_get_proxy_config("fetch_service_host"),
                    port=_get_proxy_config("fetch_service_port"),
                )
            )
            args["revocation_endpoint"] = "{endpoint}/session/{id}".format(
                endpoint=_get_proxy_config("fetch_service_control_endpoint"),
                id=session["id"],
            )

    @defer.inlineCallbacks
    def _requestProxyToken(self):
        admin_username = _get_value_from_config(
            "builder_proxy_auth_api_admin_username"
        )
        secret = _get_value_from_config("builder_proxy_auth_api_admin_secret")
        url = _get_value_from_config("builder_proxy_auth_api_endpoint")
        timestamp = int(time.time())
        proxy_username = "{build_id}-{timestamp}".format(
            build_id=self.build.build_cookie, timestamp=timestamp
        )
        auth_string = f"{admin_username}:{secret}".strip()
        auth_header = b"Basic " + base64.b64encode(auth_string.encode("ASCII"))

        token = yield self._worker.process_pool.doWork(
            RequestProxyTokenCommand,
            url=url,
            auth_header=auth_header,
            proxy_username=proxy_username,
        )
        return token

    @defer.inlineCallbacks
    def _requestFetchServiceSession(self):
        admin_username = _get_value_from_config(
            "fetch_service_control_admin_username"
        )
        secret = _get_value_from_config("fetch_service_control_admin_secret")
        url = _get_value_from_config("fetch_service_control_endpoint")
        timestamp = int(time.time())
        proxy_username = "{build_id}-{timestamp}".format(
            build_id=self.build.build_cookie, timestamp=timestamp
        )
        auth_string = f"{admin_username}:{secret}".strip()
        auth_header = b"Basic " + base64.b64encode(auth_string.encode("ASCII"))

        session = yield self._worker.process_pool.doWork(
            RequestFetchServiceSessionCommand,
            url=url,
            auth_header=auth_header,
            proxy_username=proxy_username,
        )
        return session
