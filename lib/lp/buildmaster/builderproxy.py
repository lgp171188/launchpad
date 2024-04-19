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
from typing import Dict, Generator, Type

from twisted.internet import defer

from lp.buildmaster.downloader import (
    RequestFetchServiceSessionCommand,
    RequestProxyTokenCommand,
)
from lp.buildmaster.interactor import BuilderWorker
from lp.buildmaster.interfaces.builder import CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import BuildArgs
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
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

    # Variables that are set up by the class that uses the Mixin
    build: BuildFarmJob
    _worker: BuilderWorker

    @defer.inlineCallbacks
    def addProxyArgs(
        self,
        args: BuildArgs,
        allow_internet: bool = True,
        use_fetch_service: bool = False,
    ) -> Generator[None, Dict[str, str], None]:

        self.proxy_service = None

        if not allow_internet:
            return

        if not use_fetch_service and _get_proxy_config("builder_proxy_host"):
            proxy_service: Type[IProxyService] = BuilderProxy
        elif use_fetch_service and _get_proxy_config("fetch_service_host"):
            proxy_service = FetchService

            # Append the fetch-service certificate to BuildArgs secrets.
            if "secrets" not in args:
                args["secrets"] = {}
            args["secrets"]["fetch_service_mitm_certificate"] = (
                _get_value_from_config("fetch_service_mitm_certificate")
            )
        else:
            # If the required config values aren't set, we skip adding proxy
            # args or starting a proxy session. This might be relevant for
            # non-production environments.
            return

        self.proxy_service = proxy_service(
            build_id=self.build.build_cookie, worker=self._worker
        )
        new_session = yield self.proxy_service.startSession()
        args["proxy_url"] = new_session["proxy_url"]
        args["revocation_endpoint"] = new_session["revocation_endpoint"]


class IProxyService:
    """Interface for Proxy Services - either FetchService or BuilderProxy."""

    def __init__(self, build_id: str, worker: BuilderWorker):
        pass

    @defer.inlineCallbacks
    def startSession(self):
        """Start a proxy session and request required

        :returns: dictionary with an authenticated `proxy_url` for the builder
        to use, and a `revocation_endpoint` to revoke the token when it's no
        longer required.
        """
        pass


class BuilderProxy(IProxyService):
    """Handler for the Builder Proxy.

    Handles the life-cycle of the proxy session used by a builder by
    making API requests directly to the builder proxy control endpoint.
    """

    def __init__(self, build_id: str, worker: BuilderWorker):
        self.control_endpoint = _get_value_from_config(
            "builder_proxy_auth_api_endpoint"
        )
        self.proxy_endpoint = "{host}:{port}".format(
            host=_get_value_from_config("builder_proxy_host"),
            port=_get_value_from_config("builder_proxy_port"),
        )
        self.auth_header = self._getAuthHeader()

        self.build_id = build_id
        self.worker = worker

    @staticmethod
    def _getAuthHeader():
        """Helper method to generate authentication needed to call the
        builder proxy authentication endpoint."""

        admin_username = _get_value_from_config(
            "builder_proxy_auth_api_admin_username"
        )
        admin_secret = _get_value_from_config(
            "builder_proxy_auth_api_admin_secret"
        )
        auth_string = f"{admin_username}:{admin_secret}".strip()
        return b"Basic " + base64.b64encode(auth_string.encode("ASCII"))

    @defer.inlineCallbacks
    def startSession(self):
        """Request a token from the builder proxy to be used by the builders.

        See IProxyService.
        """
        timestamp = int(time.time())
        proxy_username = "{build_id}-{timestamp}".format(
            build_id=self.build_id, timestamp=timestamp
        )

        token = yield self.worker.process_pool.doWork(
            RequestProxyTokenCommand,
            url=self.control_endpoint,
            auth_header=self.auth_header,
            proxy_username=proxy_username,
        )

        proxy_url = "http://{username}:{password}@{proxy_endpoint}".format(
            username=token["username"],
            password=token["secret"],
            proxy_endpoint=self.proxy_endpoint,
        )
        revocation_endpoint = "{endpoint}/{token}".format(
            endpoint=self.control_endpoint,
            token=token["username"],
        )

        return {
            "proxy_url": proxy_url,
            "revocation_endpoint": revocation_endpoint,
        }


class FetchService(IProxyService):
    """Handler for the Fetch Service.

    Handles the life-cycle of the fetch service session used by a builder by
    making API requests directly to the fetch service control endpoint.
    """

    PROXY_URL = "http://{session_id}:{token}@{proxy_endpoint}"
    START_SESSION_ENDPOINT = "{control_endpoint}/session"
    TOKEN_REVOCATION = "{control_endpoint}/session/{session_id}/token"
    RETRIEVE_METADATA_ENDPOINT = "{control_endpoint}/session/{session_id}"
    END_SESSION_ENDPOINT = "{control_endpoint}/session/{session_id}"

    def __init__(self, build_id: str, worker: BuilderWorker):
        self.control_endpoint = _get_value_from_config(
            "fetch_service_control_endpoint"
        )
        self.proxy_endpoint = "{host}:{port}".format(
            host=_get_value_from_config("fetch_service_host"),
            port=_get_value_from_config("fetch_service_port"),
        )
        self.auth_header = self._getAuthHeader()

        self.build_id = build_id
        self.worker = worker
        self.session_id = None

    @staticmethod
    def _getAuthHeader():
        """Helper method to generate authentication needed to call the
        fetch service control endpoint."""
        admin_username = _get_value_from_config(
            "fetch_service_control_admin_username"
        )
        secret = _get_value_from_config("fetch_service_control_admin_secret")
        auth_string = f"{admin_username}:{secret}".strip()
        return b"Basic " + base64.b64encode(auth_string.encode("ASCII"))

    @defer.inlineCallbacks
    def startSession(self):
        """Requests a fetch service session and returns session information.

        See IProxyService.
        """
        timestamp = int(time.time())
        proxy_username = "{build_id}-{timestamp}".format(
            build_id=self.build_id, timestamp=timestamp
        )

        session_data = yield self.worker.process_pool.doWork(
            RequestFetchServiceSessionCommand,
            url=self.START_SESSION_ENDPOINT.format(
                control_endpoint=self.control_endpoint
            ),
            auth_header=self.auth_header,
            proxy_username=proxy_username,
        )

        self.session_id = session_data["id"]
        token = session_data["token"]

        proxy_url = self.PROXY_URL.format(
            session_id=self.session_id,
            token=token,
            proxy_endpoint=self.proxy_endpoint,
        )
        revocation_endpoint = self.TOKEN_REVOCATION.format(
            control_endpoint=self.control_endpoint,
            session_id=self.session_id,
        )

        return {
            "proxy_url": proxy_url,
            "revocation_endpoint": revocation_endpoint,
        }
