# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for communication with Charmhub."""

import base64
import json

from lazr.restful.utils import get_current_browser_request
from pymacaroons import Macaroon
from pymacaroons.serializers import JsonSerializer
import responses
from testtools.matchers import (
    AfterPreprocessing,
    ContainsDict,
    Equals,
    MatchesAll,
    MatchesStructure,
    )
from zope.component import getUtility

from lp.charms.interfaces.charmhubclient import (
    BadExchangeMacaroonsResponse,
    BadRequestPackageUploadResponse,
    ICharmhubClient,
    )
from lp.charms.interfaces.charmrecipe import CHARM_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class RequestMatches(MatchesStructure):
    """Matches a request with the specified attributes."""

    def __init__(self, macaroons=None, json_data=None, **kwargs):
        kwargs = dict(kwargs)
        if macaroons is not None:
            headers_matcher = ContainsDict({
                "Macaroons": AfterPreprocessing(
                    lambda v: json.loads(
                        base64.b64decode(v.encode()).decode()),
                    Equals([json.loads(m) for m in macaroons])),
                })
            if kwargs.get("headers"):
                headers_matcher = MatchesAll(
                    kwargs["headers"], headers_matcher)
            kwargs["headers"] = headers_matcher
        if json_data is not None:
            body_matcher = AfterPreprocessing(
                lambda b: json.loads(b.decode()), Equals(json_data))
            if kwargs.get("body"):
                body_matcher = MatchesAll(kwargs["body"], body_matcher)
            kwargs["body"] = body_matcher
        super().__init__(**kwargs)


class TestCharmhubClient(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))
        self.pushConfig("charms", charmhub_url="http://charmhub.example/")
        self.client = getUtility(ICharmhubClient)

    @responses.activate
    def test_requestPackageUploadPermission(self):
        responses.add(
            "POST", "http://charmhub.example/v1/tokens",
            json={"macaroon": "sentinel"})
        macaroon = self.client.requestPackageUploadPermission("test-charm")
        self.assertThat(responses.calls[-1].request, RequestMatches(
            url=Equals("http://charmhub.example/v1/tokens"),
            method=Equals("POST"),
            json_data={
                "description": "test-charm for launchpad.test",
                "packages": [{"type": "charm", "name": "test-charm"}],
                "permissions": [
                    "package-manage-releases",
                    "package-manage-revisions",
                    ],
                }))
        self.assertEqual("sentinel", macaroon)
        request = get_current_browser_request()
        start, stop = get_request_timeline(request).actions[-2:]
        self.assertThat(start, MatchesStructure.byEquality(
            category="request-charm-upload-macaroon-start",
            detail="test-charm"))
        self.assertThat(stop, MatchesStructure.byEquality(
            category="request-charm-upload-macaroon-stop",
            detail="test-charm"))

    @responses.activate
    def test_requestPackageUploadPermission_missing_macaroon(self):
        responses.add("POST", "http://charmhub.example/v1/tokens", json={})
        self.assertRaisesWithContent(
            BadRequestPackageUploadResponse, "{}",
            self.client.requestPackageUploadPermission, "test-charm")

    @responses.activate
    def test_requestPackageUploadPermission_error(self):
        responses.add(
            "POST", "http://charmhub.example/v1/tokens",
            status=503, json={"error_list": [{"message": "Failed"}]})
        self.assertRaisesWithContent(
            BadRequestPackageUploadResponse, "Failed",
            self.client.requestPackageUploadPermission, "test-charm")

    @responses.activate
    def test_requestPackageUploadPermission_404(self):
        responses.add("POST", "http://charmhub.example/v1/tokens", status=404)
        self.assertRaisesWithContent(
            BadRequestPackageUploadResponse,
            "404 Client Error: Not Found",
            self.client.requestPackageUploadPermission, "test-charm")

    @responses.activate
    def test_exchangeMacaroons(self):
        responses.add(
            "POST", "http://charmhub.example/v1/tokens/exchange",
            json={"macaroon": "sentinel"})
        root_macaroon = Macaroon(version=2)
        root_macaroon_raw = root_macaroon.serialize(JsonSerializer())
        unbound_discharge_macaroon = Macaroon(version=2)
        unbound_discharge_macaroon_raw = unbound_discharge_macaroon.serialize(
            JsonSerializer())
        discharge_macaroon_raw = root_macaroon.prepare_for_request(
            unbound_discharge_macaroon).serialize(JsonSerializer())
        exchanged_macaroon_raw = self.client.exchangeMacaroons(
            root_macaroon_raw, unbound_discharge_macaroon_raw)
        self.assertThat(responses.calls[-1].request, RequestMatches(
            url=Equals("http://charmhub.example/v1/tokens/exchange"),
            method=Equals("POST"),
            macaroons=[root_macaroon_raw, discharge_macaroon_raw],
            json_data={}))
        self.assertEqual("sentinel", exchanged_macaroon_raw)
        request = get_current_browser_request()
        start, stop = get_request_timeline(request).actions[-2:]
        self.assertThat(start, MatchesStructure.byEquality(
            category="exchange-macaroons-start", detail=""))
        self.assertThat(stop, MatchesStructure.byEquality(
            category="exchange-macaroons-stop", detail=""))

    @responses.activate
    def test_exchangeMacaroons_missing_macaroon(self):
        responses.add(
            "POST", "http://charmhub.example/v1/tokens/exchange", json={})
        root_macaroon_raw = Macaroon(version=2).serialize(JsonSerializer())
        discharge_macaroon_raw = Macaroon(version=2).serialize(
            JsonSerializer())
        self.assertRaisesWithContent(
            BadExchangeMacaroonsResponse, "{}",
            self.client.exchangeMacaroons,
            root_macaroon_raw, discharge_macaroon_raw)

    @responses.activate
    def test_exchangeMacaroons_error(self):
        responses.add(
            "POST", "http://charmhub.example/v1/tokens/exchange",
            status=401,
            json={"error_list": [{"message": "Exchange window expired"}]})
        root_macaroon_raw = Macaroon(version=2).serialize(JsonSerializer())
        discharge_macaroon_raw = Macaroon(version=2).serialize(
            JsonSerializer())
        self.assertRaisesWithContent(
            BadExchangeMacaroonsResponse, "Exchange window expired",
            self.client.exchangeMacaroons,
            root_macaroon_raw, discharge_macaroon_raw)

    @responses.activate
    def test_exchangeMacaroons_404(self):
        responses.add(
            "POST", "http://charmhub.example/v1/tokens/exchange", status=404)
        root_macaroon_raw = Macaroon(version=2).serialize(JsonSerializer())
        discharge_macaroon_raw = Macaroon(version=2).serialize(
            JsonSerializer())
        self.assertRaisesWithContent(
            BadExchangeMacaroonsResponse,
            "404 Client Error: Not Found",
            self.client.exchangeMacaroons,
            root_macaroon_raw, discharge_macaroon_raw)
