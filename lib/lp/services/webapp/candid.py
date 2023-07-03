# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interaction with the Candid identity service."""

__all__ = [
    "BadCandidMacaroon",
    "CandidCallbackView",
    "CandidFailure",
    "CandidUnconfiguredError",
    "extract_candid_caveat",
    "request_candid_discharge",
]

import hashlib
import hmac
import http.client
import json
import uuid
from base64 import b64encode
from urllib.parse import urlencode

from lazr.restful.declarations import error_status
from pymacaroons import Macaroon
from pymacaroons.serializers import JsonSerializer
from requests import HTTPError
from zope.browserpage import ViewPageTemplateFile

from lp.services.config import config
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.services.timeout import raise_for_status_redacted, urlfetch
from lp.services.webapp.interfaces import ISession
from lp.services.webapp.publisher import LaunchpadView
from lp.services.webapp.url import urlappend
from lp.services.webapp.vhosts import allvhosts


class CandidUnconfiguredError(Exception):
    """The Candid service is not configured."""


class BadCandidMacaroon(Exception):
    """The macaroon is unsuitable for being discharged by Candid."""


@error_status(http.client.BAD_REQUEST)
class CandidFailure(Exception):
    """Candid authorization failed."""

    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


def _make_candid_request(request, endpoint_name, expect_401=False, **kwargs):
    """Make a POST request to the Candid API."""
    url = urlappend(config.launchpad.candid_service_root, endpoint_name)
    base_headers = {"Bakery-Protocol-Version": "2"}
    timeline = get_request_timeline(request)
    action = timeline.start("candid", url)
    try:
        response = urlfetch(
            url,
            method="POST",
            headers=base_headers,
            check_status=not expect_401,
            **kwargs,
        )
        if expect_401 and response.status_code != 401:
            raise_for_status_redacted(response)
            raise CandidFailure(
                "Initial discharge request unexpectedly succeeded without "
                "authorization",
                response=response,
            )
        return response
    except HTTPError as e:
        raise CandidFailure(str(e), response=e.response)
    finally:
        action.finish()


def _deserialize_json_macaroon(macaroon_raw):
    """Deserialize a macaroon serialized using JSON."""
    return Macaroon.deserialize(macaroon_raw, JsonSerializer())


def extract_candid_caveat(macaroon):
    """Extract the Candid third-party caveat from a macaroon."""
    caveats = [
        caveat
        for caveat in macaroon.caveats
        if caveat.location == config.launchpad.candid_service_root
    ]
    if not caveats:
        raise BadCandidMacaroon(
            "Macaroon has no Candid caveat ({})".format(
                config.launchpad.candid_service_root
            )
        )
    elif len(caveats) > 1:
        raise BadCandidMacaroon(
            "Macaroon has multiple Candid caveats ({})".format(
                config.launchpad.candid_service_root
            )
        )
    return caveats[0]


def _get_candid_login_url_for_discharge(
    request, macaroon, state, callback_url
):
    """Get the login URL to web-discharge a third-party caveat."""
    caveat = extract_candid_caveat(macaroon)
    response = _make_candid_request(
        request,
        "discharge",
        data={"id64": b64encode(caveat.caveat_id_bytes)},
        expect_401=True,
    )
    try:
        interaction_methods = response.json()["Info"]["InteractionMethods"]
        browser_redirect = interaction_methods["browser-redirect"]
        return "{}?{}".format(
            browser_redirect["LoginURL"],
            urlencode({"return_to": callback_url, "state": state}),
        )
    except KeyError:
        raise CandidFailure(
            "Initial discharge request did not contain expected fields",
            response=response,
        )


def request_candid_discharge(
    request,
    macaroon_raw,
    starting_url,
    discharge_macaroon_field,
    discharge_macaroon_action=None,
):
    """Request a discharge for a given macaroon from Candid.

    Returns a Candid URL.  The caller should redirect to it by whatever
    means is appropriate in context.
    """
    if (
        not config.launchpad.candid_service_root
        or not config.launchpad.csrf_secret
    ):
        raise CandidUnconfiguredError("The Candid service is not configured.")

    macaroon = _deserialize_json_macaroon(macaroon_raw)

    csrf_token = hashlib.sha256(
        (uuid.uuid4().hex + config.launchpad.csrf_secret).encode()
    ).hexdigest()

    session_data = ISession(request)["launchpad.candid"]
    session_data["macaroon"] = macaroon_raw
    session_data["csrf-token"] = csrf_token

    # Once the user authenticates with Candid, they will be redirected to
    # the /+candid-callback page, which must send them back to the URL they
    # were when they started the authorization process.  To help with that,
    # we encode that URL and some additional data as query parameters in the
    # return_to URL passed to Candid.
    starting_data = [
        ("starting_url", starting_url),
        ("discharge_macaroon_field", discharge_macaroon_field),
    ]
    if discharge_macaroon_action is not None:
        starting_data.append(
            ("discharge_macaroon_action", discharge_macaroon_action)
        )
    return_to = "%s?%s" % (
        urlappend(allvhosts.configs["mainsite"].rooturl, "+candid-callback"),
        urlencode(starting_data),
    )

    return _get_candid_login_url_for_discharge(
        request, macaroon, csrf_token, return_to
    )


class CandidErrorView(LaunchpadView):
    page_title = "Authorization error"
    template = ViewPageTemplateFile("templates/candid-error.pt")

    def __init__(self, context, request, candid_error):
        super().__init__(context, request)
        self.candid_error = candid_error


class CandidCallbackView(LaunchpadView):
    """Callback view for Candid authorization."""

    template = ViewPageTemplateFile("templates/login-discharge-macaroon.pt")

    def _gatherParams(self, request):
        params = dict(request.form)
        for key, value in request.query_string_params.items():
            if len(value) > 1:
                raise ValueError("Did not expect multi-valued fields.")
            params[key] = value[0]
        return params

    def _get_serialized_discharge(self, request, macaroon, code):
        """Get the discharge macaroon generated after a Candid web login."""
        caveat = extract_candid_caveat(macaroon)
        response = _make_candid_request(
            request, "discharge-token", json={"code": code}
        )
        token = response.json()["token"]
        data = {
            "id64": b64encode(caveat.caveat_id_bytes),
            "token64": token["value"],
            "token-kind": token["kind"],
        }
        response = _make_candid_request(request, "discharge", data=data)
        return json.dumps(response.json()["Macaroon"])

    def initialize(self):
        self.params = self._gatherParams(self.request)
        session_data = ISession(self.request)["launchpad.candid"]

        try:
            if (
                "macaroon" not in session_data
                or "csrf-token" not in session_data
            ):
                raise CandidFailure("Candid session lost or not started")
            if (
                "starting_url" not in self.params
                or "discharge_macaroon_field" not in self.params
                or "code" not in self.params
            ):
                raise CandidFailure("Missing parameters to Candid callback")

            # Validate CSRF token.
            if not hmac.compare_digest(
                self.params.get("state", ""), session_data["csrf-token"]
            ):
                raise CandidFailure("CSRF token mismatch")

            # Get unbound discharge macaroon from Candid.
            code = self.params["code"]
            macaroon = _deserialize_json_macaroon(session_data["macaroon"])
            self.discharge_macaroon_raw = self._get_serialized_discharge(
                self.request, macaroon, code
            )
            self.candid_error = None
        except CandidFailure as e:
            self.candid_error = str(e)
        finally:
            # Prevent replay attacks.  PGSessionPkgData.__delitem__ ensures
            # that this succeeds even if the key does not exist.
            del session_data["macaroon"]
            del session_data["csrf-token"]

    def render(self):
        if self.candid_error is not None:
            return CandidErrorView(
                self.context, self.request, self.candid_error
            )()
        else:
            return super().render()
