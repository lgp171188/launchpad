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
    "BUILD_METADATA_FILENAME_FORMAT",
    "BuilderProxyMixin",
]

import base64
import os
import re
import time
from typing import Optional

from twisted.internet import defer

from lp.buildmaster.downloader import (
    EndFetchServiceSessionCommand,
    RequestFetchServiceSessionCommand,
    RequestProxyTokenCommand,
    RetrieveFetchServiceSessionCommand,
)
from lp.buildmaster.interactor import BuilderWorker
from lp.buildmaster.interfaces.builder import CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import BuildArgs
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
from lp.services.config import config

BUILD_METADATA_FILENAME_FORMAT = "{build_id}_metadata.json"


class ProxyServiceException(Exception):
    pass


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
    def startProxySession(
        self,
        args: BuildArgs,
        allow_internet: bool = True,
        use_fetch_service: bool = False,
    ):

        if not allow_internet:
            return

        proxy_service: IProxyService

        if not use_fetch_service and _get_proxy_config("builder_proxy_host"):
            proxy_service = BuilderProxy(worker=self._worker)
        elif use_fetch_service and _get_proxy_config("fetch_service_host"):
            proxy_service = FetchService(worker=self._worker)

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

        session_data = yield proxy_service.startSession(
            build_id=self.build.build_cookie
        )

        args["proxy_url"] = session_data["proxy_url"]
        args["revocation_endpoint"] = session_data["revocation_endpoint"]
        args["use_fetch_service"] = use_fetch_service

    @defer.inlineCallbacks
    def endProxySession(self, upload_path: str):
        """Handles all the necessary cleanup to be done at the end of a build.

        For the fetch service case, this means:
         - Retrieving the metadata, and storing into a file in `upload_path`
         - Closing the fetch service session (which deletes the session data
         from the fetch service system)

        Note that if retrieving or storing the metadata file fails, an
        exception will be raised, and we won't close the session. This could be
        useful for debbugging.
        Sessions will be closed automatically within the Fetch Service after
        a certain amount of time configured by its charm (default 6 hours).
        """

        proxy_info = yield self._worker.proxy_info()
        use_fetch_service = proxy_info.get("use_fetch_service")

        if not use_fetch_service:
            # No cleanup needed when not using the fetch service
            # This is true both when we use the builder proxy and when we don't
            # allow internet access to the builds.
            return

        proxy_service = FetchService(worker=self._worker)

        # XXX ines-almeida 2024-04-30: Getting the session_id from the
        # revocation_endpoint feels a little like going back and forwards
        # given the revocation_endpoint is created on `startProxySession()`.
        # Ideally, we would update `buildd` and `buildd-manager` to senf and
        # retrieve the session ID directly (instead of having to parse it).
        revocation_endpoint = proxy_info.get("revocation_endpoint")
        session_id = proxy_service.extractSessionIDFromRevocationEndpoint(
            revocation_endpoint
        )

        if session_id is None:
            raise ProxyServiceException(
                "Could not parse the revocation endpoint fetched from buildd "
                f"('{revocation_endpoint}') to get the fetch service "
                "`session_id` used within the build."
            )

        metadata_file_name = BUILD_METADATA_FILENAME_FORMAT.format(
            build_id=self.build.build_cookie
        )
        file_path = os.path.join(upload_path, metadata_file_name)
        yield proxy_service.retrieveMetadataFromSession(
            session_id=session_id,
            save_content_to=file_path,
        )

        yield proxy_service.endSession(session_id=session_id)


class IProxyService:
    """Interface for Proxy Services - either FetchService or BuilderProxy."""

    def __init__(self, worker: BuilderWorker):
        pass

    @defer.inlineCallbacks
    def startSession(self, build_id: str):
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

    def __init__(self, worker: BuilderWorker):
        self.control_endpoint = _get_value_from_config(
            "builder_proxy_auth_api_endpoint"
        )
        self.proxy_endpoint = "{host}:{port}".format(
            host=_get_value_from_config("builder_proxy_host"),
            port=_get_value_from_config("builder_proxy_port"),
        )
        self.auth_header = self._getAuthHeader()
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
    def startSession(self, build_id: str):
        """Request a token from the builder proxy to be used by the builders.

        See IProxyService.
        """
        timestamp = int(time.time())
        proxy_username = "{build_id}-{timestamp}".format(
            build_id=build_id, timestamp=timestamp
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

    def __init__(self, worker: BuilderWorker):
        self.control_endpoint = _get_value_from_config(
            "fetch_service_control_endpoint"
        )
        self.proxy_endpoint = "{host}:{port}".format(
            host=_get_value_from_config("fetch_service_host"),
            port=_get_value_from_config("fetch_service_port"),
        )
        self.auth_header = self._getAuthHeader()
        self.worker = worker

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
    def startSession(self, build_id: str):
        """Requests a fetch service session and returns session information.

        See IProxyService.
        """
        session_data = yield self.worker.process_pool.doWork(
            RequestFetchServiceSessionCommand,
            url=self.START_SESSION_ENDPOINT.format(
                control_endpoint=self.control_endpoint
            ),
            auth_header=self.auth_header,
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

    def extractSessionIDFromRevocationEndpoint(
        self, revocation_endpoint: str
    ) -> Optional[str]:
        """Helper method to get the session_id out of the revocation
        endpoint.

        Example `revocation_endpoint`:
        http://fetch-service.net:9999/session/913890402914ce3be9ffd4d0/token

        Would return: 913890402914ce3be9ffd4d0
        """
        re_pattern = self.TOKEN_REVOCATION.format(
            control_endpoint=self.control_endpoint,
            session_id="(?P<session_id>.*)",
        )
        match = re.match(re_pattern, revocation_endpoint)
        return match["session_id"] if match else None

    @defer.inlineCallbacks
    def retrieveMetadataFromSession(
        self, session_id: str, save_content_to: str
    ):
        """Make request to retrieve metadata from the current session.

        Data is stored directly into a file whose path is `save_content_to`

        :raises: RequestException if request to Fetch Service fails
        """
        url = self.RETRIEVE_METADATA_ENDPOINT.format(
            control_endpoint=self.control_endpoint,
            session_id=session_id,
        )
        yield self.worker.process_pool.doWork(
            RetrieveFetchServiceSessionCommand,
            url=url,
            auth_header=self.auth_header,
            save_content_to=save_content_to,
        )

    @defer.inlineCallbacks
    def endSession(self, session_id: str):
        """End the proxy session and do any cleanup needed.

        :raises: RequestException if request to Fetch Service fails
        """
        url = self.END_SESSION_ENDPOINT.format(
            control_endpoint=self.control_endpoint,
            session_id=session_id,
        )
        yield self.worker.process_pool.doWork(
            EndFetchServiceSessionCommand,
            url=url,
            auth_header=self.auth_header,
        )
