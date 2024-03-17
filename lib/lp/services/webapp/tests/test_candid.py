# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Candid interaction."""

import json
from base64 import b64encode
from urllib.parse import parse_qs, urlencode, urlsplit

import responses
from pymacaroons import Macaroon
from pymacaroons.serializers import JsonSerializer
from testtools.matchers import (
    AfterPreprocessing,
    ContainsDict,
    Equals,
    Is,
    MatchesDict,
    MatchesListwise,
    MatchesSetwise,
    MatchesStructure,
    Not,
)

from lp.services.config import config
from lp.services.webapp.candid import (
    BadCandidMacaroon,
    CandidFailure,
    CandidUnconfiguredError,
    extract_candid_caveat,
    request_candid_discharge,
)
from lp.services.webapp.interfaces import ISession
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import TestCase, TestCaseWithFactory, login_person
from lp.testing.layers import BaseLayer, DatabaseFunctionalLayer
from lp.testing.pages import extract_text, find_tags_by_class


class TestExtractCandidCaveat(TestCase):
    layer = BaseLayer

    def setUp(self):
        super().setUp()
        self.pushConfig(
            "launchpad", candid_service_root="https://candid.test/"
        )

    def test_no_candid_caveat(self):
        macaroon = Macaroon(version=2)
        self.assertRaisesWithContent(
            BadCandidMacaroon,
            "Macaroon has no Candid caveat (https://candid.test/)",
            extract_candid_caveat,
            macaroon,
        )

    def test_one_candid_caveat(self):
        macaroon = Macaroon(version=2)
        macaroon.add_third_party_caveat("https://example.test/", "", "example")
        macaroon.add_third_party_caveat("https://candid.test/", "", "identity")
        self.assertEqual(macaroon.caveats[1], extract_candid_caveat(macaroon))

    def test_multiple_candid_caveats(self):
        macaroon = Macaroon(version=2)
        macaroon.add_third_party_caveat("https://candid.test/", "", "one")
        macaroon.add_third_party_caveat("https://candid.test/", "", "two")
        self.assertRaisesWithContent(
            BadCandidMacaroon,
            "Macaroon has multiple Candid caveats (https://candid.test/)",
            extract_candid_caveat,
            macaroon,
        )


class TestRequestCandidDischarge(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_unconfigured(self):
        request = LaunchpadTestRequest()
        macaroon_raw = Macaroon(version=2).serialize(JsonSerializer())
        self.assertRaises(
            CandidUnconfiguredError,
            request_candid_discharge,
            request,
            macaroon_raw,
            "http://launchpad.test/after-candid",
            "field.discharge_macaroon",
        )
        self.pushConfig(
            "launchpad", candid_service_root="https://candid.test/"
        )
        self.assertRaises(
            CandidUnconfiguredError,
            request_candid_discharge,
            request,
            macaroon_raw,
            "http://launchpad.test/after-candid",
            "field.discharge_macaroon",
        )

    @responses.activate
    def test_initial_discharge_unexpected_success(self):
        self.pushConfig(
            "launchpad",
            candid_service_root="https://candid.test/",
            csrf_secret="test secret",
        )
        responses.add("POST", "https://candid.test/discharge", status=200)

        person = self.factory.makePerson()
        login_person(person)
        macaroon = Macaroon(version=2)
        macaroon.add_third_party_caveat("https://candid.test/", "", "identity")
        macaroon_raw = macaroon.serialize(JsonSerializer())
        request = LaunchpadTestRequest()
        self.assertRaisesWithContent(
            CandidFailure,
            "Initial discharge request unexpectedly succeeded without "
            "authorization",
            request_candid_discharge,
            request,
            macaroon_raw,
            "http://launchpad.test/after-candid",
            "field.discharge_macaroon",
        )

    @responses.activate
    def test_initial_discharge_failure(self):
        self.pushConfig(
            "launchpad",
            candid_service_root="https://candid.test/",
            csrf_secret="test secret",
        )
        responses.add("POST", "https://candid.test/discharge", status=500)

        person = self.factory.makePerson()
        login_person(person)
        macaroon = Macaroon(version=2)
        macaroon.add_third_party_caveat("https://candid.test/", "", "identity")
        macaroon_raw = macaroon.serialize(JsonSerializer())
        request = LaunchpadTestRequest()
        self.assertRaisesWithContent(
            CandidFailure,
            "500 Server Error: Internal Server Error",
            request_candid_discharge,
            request,
            macaroon_raw,
            "http://launchpad.test/after-candid",
            "field.discharge_macaroon",
        )

    @responses.activate
    def test_initial_discharge_missing_fields(self):
        self.pushConfig(
            "launchpad",
            candid_service_root="https://candid.test/",
            csrf_secret="test secret",
        )
        responses.add(
            "POST",
            "https://candid.test/discharge",
            status=401,
            json={"Info": {}},
        )

        person = self.factory.makePerson()
        login_person(person)
        macaroon = Macaroon(version=2)
        macaroon.add_third_party_caveat("https://candid.test/", "", "identity")
        macaroon_raw = macaroon.serialize(JsonSerializer())
        request = LaunchpadTestRequest()
        self.assertRaisesWithContent(
            CandidFailure,
            "Initial discharge request did not contain expected fields",
            request_candid_discharge,
            request,
            macaroon_raw,
            "http://launchpad.test/after-candid",
            "field.discharge_macaroon",
        )

    @responses.activate
    def test_requests_discharge(self):
        # Requesting a discharge saves some state in the session and
        # redirects to Candid.
        self.pushConfig(
            "launchpad",
            candid_service_root="https://candid.test/",
            csrf_secret="test secret",
        )
        responses.add(
            "POST",
            "https://candid.test/discharge",
            status=401,
            json={
                "Code": "interaction required",
                "Message": (
                    "macaroon discharge required: authentication required"
                ),
                "Info": {
                    "InteractionMethods": {
                        "browser-redirect": {
                            "LoginURL": "https://candid.test/login-redirect",
                            "DischargeTokenURL": (
                                "https://candid.test/discharge-token"
                            ),
                        },
                    },
                },
            },
        )

        person = self.factory.makePerson()
        login_person(person)
        macaroon = Macaroon(version=2)
        macaroon.add_third_party_caveat("https://candid.test/", "", "identity")
        caveat = macaroon.caveats[0]
        macaroon_raw = macaroon.serialize(JsonSerializer())
        request = LaunchpadTestRequest()
        login_url = request_candid_discharge(
            request,
            macaroon_raw,
            "http://launchpad.test/after-candid?extra_key=extra+value",
            "field.discharge_macaroon",
            discharge_macaroon_action="field.actions.complete",
        )

        # State was saved in the session.
        session_data = ISession(request)["launchpad.candid"]
        self.assertThat(
            session_data,
            MatchesDict(
                {
                    "macaroon": Equals(macaroon_raw),
                    "csrf-token": Not(Is(None)),
                }
            ),
        )

        # We made the appropriate requests to Candid to initiate
        # authorization.
        discharge_matcher = MatchesStructure(
            url=Equals("https://candid.test/discharge"),
            headers=ContainsDict(
                {
                    "Content-Type": Equals(
                        "application/x-www-form-urlencoded"
                    ),
                }
            ),
            body=AfterPreprocessing(
                parse_qs,
                MatchesDict(
                    {
                        "id64": Equals(
                            [b64encode(caveat.caveat_id_bytes).decode()]
                        ),
                    }
                ),
            ),
        )
        self.assertThat(
            responses.calls,
            MatchesListwise([MatchesStructure(request=discharge_matcher)]),
        )

        # We return the correct URL.
        return_to_matcher = AfterPreprocessing(
            urlsplit,
            MatchesStructure(
                scheme=Equals("http"),
                netloc=Equals("launchpad.test"),
                path=Equals("/+candid-callback"),
                query=AfterPreprocessing(
                    parse_qs,
                    MatchesDict(
                        {
                            "starting_url": Equals(
                                [
                                    "http://launchpad.test/after-candid"
                                    "?extra_key=extra+value"
                                ]
                            ),
                            "discharge_macaroon_action": Equals(
                                ["field.actions.complete"]
                            ),
                            "discharge_macaroon_field": Equals(
                                ["field.discharge_macaroon"]
                            ),
                        }
                    ),
                ),
                fragment=Equals(""),
            ),
        )
        self.assertThat(
            urlsplit(login_url),
            MatchesStructure(
                scheme=Equals("https"),
                netloc=Equals("candid.test"),
                path=Equals("/login-redirect"),
                query=AfterPreprocessing(
                    parse_qs,
                    MatchesDict(
                        {
                            "return_to": MatchesListwise([return_to_matcher]),
                            "state": Equals([session_data["csrf-token"]]),
                        }
                    ),
                ),
                fragment=Equals(""),
            ),
        )


class TestCandidCallbackView(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.pushConfig(
            "launchpad", candid_service_root="https://candid.test/"
        )

    @responses.activate
    def test_no_candid_session(self):
        browser = self.getUserBrowser()
        browser.open("http://launchpad.test/+candid-callback")
        [top_portlet] = find_tags_by_class(browser.contents, "top-portlet")
        self.assertEqual(
            "Authorization failed\nCandid session lost or not started",
            extract_text(top_portlet),
        )

    def _setUpBrowser(self, macaroon, csrf_token, form):
        person = self.factory.makePerson()
        login_person(person)
        request = LaunchpadTestRequest(form=form, PATH_INFO="/")
        request.setPrincipal(person)
        session = ISession(request)
        session_data = session["launchpad.candid"]
        session_data["macaroon"] = macaroon.serialize(JsonSerializer())
        session_data["csrf-token"] = csrf_token
        browser = self.getUserBrowser(user=person)
        browser.addHeader(
            "Cookie",
            f"{config.launchpad_session.cookie}={session.client_id}",
        )
        browser.open(
            f"http://launchpad.test/+candid-callback?{urlencode(form)}"
        )
        return request, browser

    @responses.activate
    def test_missing_starting_url_parameter(self):
        form = {
            "discharge_macaroon_field": "field.discharge_macaroon",
            "code": "test code",
        }
        request, browser = self._setUpBrowser(Macaroon(), "test token", form)
        [top_portlet] = find_tags_by_class(browser.contents, "top-portlet")
        self.assertEqual(
            "Authorization failed\nMissing parameters to Candid callback",
            extract_text(top_portlet),
        )
        self.assertEqual({}, ISession(request)["launchpad.candid"])

    @responses.activate
    def test_missing_discharge_macaroon_field_parameter(self):
        form = {
            "starting_url": "http://launchpad.test/after-login",
            "code": "test code",
        }
        request, browser = self._setUpBrowser(Macaroon(), "test token", form)
        [top_portlet] = find_tags_by_class(browser.contents, "top-portlet")
        self.assertEqual(
            "Authorization failed\nMissing parameters to Candid callback",
            extract_text(top_portlet),
        )
        self.assertEqual({}, ISession(request)["launchpad.candid"])

    @responses.activate
    def test_missing_code_parameter(self):
        form = {
            "starting_url": "http://launchpad.test/after-login",
            "discharge_macaroon_field": "field.discharge_macaroon",
        }
        request, browser = self._setUpBrowser(Macaroon(), "test token", form)
        [top_portlet] = find_tags_by_class(browser.contents, "top-portlet")
        self.assertEqual(
            "Authorization failed\nMissing parameters to Candid callback",
            extract_text(top_portlet),
        )
        self.assertEqual({}, ISession(request)["launchpad.candid"])

    @responses.activate
    def test_csrf_token_mismatch(self):
        form = {
            "starting_url": "http://launchpad.test/after-login",
            "discharge_macaroon_field": "field.discharge_macaroon",
            "code": "test code",
            "state": "wrong token",
        }
        request, browser = self._setUpBrowser(Macaroon(), "test token", form)
        [top_portlet] = find_tags_by_class(browser.contents, "top-portlet")
        self.assertEqual(
            "Authorization failed\nCSRF token mismatch",
            extract_text(top_portlet),
        )
        self.assertEqual({}, ISession(request)["launchpad.candid"])

    @responses.activate
    def test_discharge_token_failure(self):
        responses.add(
            "POST", "https://candid.test/discharge-token", status=500
        )

        macaroon = Macaroon(version=2)
        macaroon.add_third_party_caveat("https://candid.test/", "", "identity")
        csrf_token = "test token"
        form = {
            "starting_url": "http://launchpad.test/after-login",
            "discharge_macaroon_field": "field.discharge_macaroon",
            "code": "test code",
            "state": csrf_token,
        }
        request, browser = self._setUpBrowser(macaroon, csrf_token, form)
        [top_portlet] = find_tags_by_class(browser.contents, "top-portlet")
        self.assertEqual(
            "Authorization failed\n500 Server Error: Internal Server Error",
            extract_text(top_portlet),
        )
        self.assertEqual({}, ISession(request)["launchpad.candid"])

    @responses.activate
    def test_discharge_failure(self):
        responses.add(
            "POST",
            "https://candid.test/discharge-token",
            json={"token": {"kind": "macaroon", "value": "discharge token"}},
        )
        responses.add("POST", "https://candid.test/discharge", status=500)

        macaroon = Macaroon(version=2)
        macaroon.add_third_party_caveat("https://candid.test/", "", "identity")
        csrf_token = "test token"
        form = {
            "starting_url": "http://launchpad.test/after-login",
            "discharge_macaroon_field": "field.discharge_macaroon",
            "code": "test code",
            "state": csrf_token,
        }
        request, browser = self._setUpBrowser(macaroon, csrf_token, form)
        [top_portlet] = find_tags_by_class(browser.contents, "top-portlet")
        self.assertEqual(
            "Authorization failed\n500 Server Error: Internal Server Error",
            extract_text(top_portlet),
        )
        self.assertEqual({}, ISession(request)["launchpad.candid"])

    @responses.activate
    def test_discharge_macaroon(self):
        # If a discharge macaroon was requested and received, the view
        # returns a form that submits it to the starting URL.
        responses.add(
            "POST",
            "https://candid.test/discharge-token",
            json={"token": {"kind": "macaroon", "value": "discharge token"}},
        )
        discharge = Macaroon(identifier="test", version=2)
        discharge_raw = discharge.serialize(JsonSerializer())
        responses.add(
            "POST",
            "https://candid.test/discharge",
            json={"Macaroon": json.loads(discharge_raw)},
        )

        macaroon = Macaroon(version=2)
        macaroon.add_third_party_caveat("https://candid.test/", "", "identity")
        caveat = macaroon.caveats[0]
        csrf_token = "test token"
        form = {
            "starting_url": "http://launchpad.test/after-login",
            "discharge_macaroon_action": "field.actions.complete",
            "discharge_macaroon_field": "field.discharge_macaroon",
            "code": "test code",
            "state": csrf_token,
        }
        request, browser = self._setUpBrowser(macaroon, csrf_token, form)

        # We made the appropriate requests to Candid to complete
        # authorization.
        discharge_token_matcher = MatchesStructure(
            url=Equals("https://candid.test/discharge-token"),
            headers=ContainsDict(
                {
                    "Content-Type": Equals("application/json"),
                }
            ),
            body=AfterPreprocessing(
                json.loads, MatchesDict({"code": Equals("test code")})
            ),
        )
        discharge_matcher = MatchesStructure(
            url=Equals("https://candid.test/discharge"),
            headers=ContainsDict(
                {
                    "Content-Type": Equals(
                        "application/x-www-form-urlencoded"
                    ),
                }
            ),
            body=AfterPreprocessing(
                parse_qs,
                MatchesDict(
                    {
                        "id64": Equals(
                            [b64encode(caveat.caveat_id_bytes).decode()]
                        ),
                        "token64": Equals(["discharge token"]),
                        "token-kind": Equals(["macaroon"]),
                    }
                ),
            ),
        )
        self.assertThat(
            responses.calls,
            MatchesListwise(
                [
                    MatchesStructure(request=discharge_token_matcher),
                    MatchesStructure(request=discharge_matcher),
                ]
            ),
        )

        # The presented form has the proper structure and includes the
        # resulting discharge macaroon.
        self.assertThat(
            browser.getForm(id="discharge-form"),
            MatchesStructure(
                action=Equals("http://launchpad.test/after-login"),
                controls=MatchesSetwise(
                    MatchesStructure.byEquality(
                        name="field.actions.complete", type="hidden", value="1"
                    ),
                    MatchesStructure.byEquality(
                        name="field.discharge_macaroon",
                        type="hidden",
                        value=discharge_raw,
                    ),
                    MatchesStructure.byEquality(type="submit"),
                ),
            ),
        )

        # The state is removed from the session.
        self.assertEqual({}, ISession(request)["launchpad.candid"])
