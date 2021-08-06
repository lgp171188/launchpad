# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Communication with Charmhub."""

__all__ = [
    "CharmhubClient",
    ]

from base64 import b64encode

from lazr.restful.utils import get_current_browser_request
from pymacaroons import Macaroon
from pymacaroons.serializers import JsonSerializer
import requests
from zope.interface import implementer

from lp.charms.interfaces.charmhubclient import (
    BadExchangeMacaroonsResponse,
    BadRequestPackageUploadResponse,
    ICharmhubClient,
    )
from lp.services.config import config
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.services.timeout import urlfetch
from lp.services.webapp.url import urlappend


@implementer(ICharmhubClient)
class CharmhubClient:
    """A client for the API provided by Charmhub."""

    @staticmethod
    def _getTimeline():
        # XXX cjwatson 2021-08-05: This can be simplified once jobs have
        # timeline support.
        request = get_current_browser_request()
        if request is None:
            return None
        return get_request_timeline(request)

    @classmethod
    def _makeCharmhubError(cls, error_class, requests_error):
        error_message = requests_error.args[0]
        if requests_error.response.content:
            try:
                response_data = requests_error.response.json()
            except ValueError:
                pass
            else:
                if "error_list" in response_data:
                    error_message = "\n".join(
                        error["message"]
                        for error in response_data["error_list"])
        detail = requests_error.response.content.decode(errors="replace")
        can_retry = requests_error.response.status_code in (502, 503)
        return error_class(error_message, detail=detail, can_retry=can_retry)

    @classmethod
    def requestPackageUploadPermission(cls, package_name):
        """See `ICharmhubClient`."""
        assert config.charms.charmhub_url is not None
        request_url = urlappend(config.charms.charmhub_url, "v1/tokens")
        request = get_current_browser_request()
        timeline_action = get_request_timeline(request).start(
            "request-charm-upload-macaroon", package_name, allow_nested=True)
        try:
            response = urlfetch(
                request_url, method="POST",
                json={
                    "description": "{} for {}".format(
                        package_name, config.vhost.mainsite.hostname),
                    "packages": [{"type": "charm", "name": package_name}],
                    "permissions": [
                        "package-manage-releases",
                        "package-manage-revisions",
                        ],
                    })
            response_data = response.json()
            if "macaroon" not in response_data:
                raise BadRequestPackageUploadResponse(response.text)
            return response_data["macaroon"]
        except requests.HTTPError as e:
            raise cls._makeCharmhubError(BadRequestPackageUploadResponse, e)
        finally:
            timeline_action.finish()

    @classmethod
    def exchangeMacaroons(cls, root_macaroon_raw,
                          unbound_discharge_macaroon_raw):
        """See `ICharmhubClient`."""
        assert config.charms.charmhub_url is not None
        root_macaroon = Macaroon.deserialize(
            root_macaroon_raw, JsonSerializer())
        unbound_discharge_macaroon = Macaroon.deserialize(
            unbound_discharge_macaroon_raw, JsonSerializer())
        discharge_macaroon_raw = root_macaroon.prepare_for_request(
            unbound_discharge_macaroon).serialize(JsonSerializer())
        request_url = urlappend(
            config.charms.charmhub_url, "v1/tokens/exchange")
        request = get_current_browser_request()
        timeline_action = get_request_timeline(request).start(
            "exchange-macaroons", "", allow_nested=True)
        try:
            all_macaroons = b64encode("[{}, {}]".format(
                root_macaroon_raw, discharge_macaroon_raw).encode()).decode()
            response = urlfetch(
                request_url, method="POST",
                headers={"Macaroons": all_macaroons}, json={})
            response_data = response.json()
            if "macaroon" not in response_data:
                raise BadExchangeMacaroonsResponse(response.text)
            return response_data["macaroon"]
        except requests.HTTPError as e:
            raise cls._makeCharmhubError(BadExchangeMacaroonsResponse, e)
        finally:
            timeline_action.finish()
