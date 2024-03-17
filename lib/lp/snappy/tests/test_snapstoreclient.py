# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for communication with the snap store."""

import base64
import hashlib
import io
import json
from cgi import FieldStorage

import responses
import transaction
from lazr.restful.utils import get_current_browser_request
from nacl.public import PrivateKey
from pymacaroons import Macaroon, Verifier
from requests import Request
from requests.utils import parse_dict_header
from testtools.matchers import (
    Contains,
    ContainsDict,
    Equals,
    Matcher,
    MatchesDict,
    MatchesListwise,
    MatchesStructure,
    Mismatch,
    StartsWith,
)
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.services.config import config
from lp.services.crypto.interfaces import IEncryptedContainer
from lp.services.log.logger import BufferLogger
from lp.services.memcache.interfaces import IMemcacheClient
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.snappy.interfaces.snapstoreclient import (
    BadRequestPackageUploadResponse,
    BadScanStatusResponse,
    ISnapStoreClient,
    ScanFailedResponse,
    SnapNotFoundResponse,
    UnauthorizedUploadResponse,
    UploadFailedResponse,
    UploadNotScannedYetResponse,
)
from lp.snappy.model.snapstoreclient import (
    InvalidStoreSecretsError,
    MacaroonAuth,
)
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.layers import LaunchpadZopelessLayer


class MacaroonsVerify(Matcher):
    """Matches if serialised macaroons pass verification."""

    def __init__(self, key):
        self.key = key

    def __str__(self):
        return f"MacaroonsVerify({self.key!r})"

    def match(self, macaroons):
        mismatch = Contains("root").match(macaroons)
        if mismatch is not None:
            return mismatch
        root_macaroon = Macaroon.deserialize(macaroons["root"])
        if "discharge" in macaroons:
            discharge_macaroons = [
                Macaroon.deserialize(macaroons["discharge"])
            ]
        else:
            discharge_macaroons = []
        try:
            Verifier().verify(root_macaroon, self.key, discharge_macaroons)
        except Exception as e:
            return Mismatch("Macaroons do not verify: %s" % e)


class TestMacaroonAuth(TestCase):
    def test_good(self):
        r = Request()
        root_key = hashlib.sha256(b"root").hexdigest()
        root_macaroon = Macaroon(key=root_key)
        discharge_key = hashlib.sha256(b"discharge").hexdigest()
        discharge_caveat_id = '{"secret": "thing"}'
        root_macaroon.add_third_party_caveat(
            "sso.example", discharge_key, discharge_caveat_id
        )
        unbound_discharge_macaroon = Macaroon(
            location="sso.example",
            key=discharge_key,
            identifier=discharge_caveat_id,
        )
        MacaroonAuth(
            root_macaroon.serialize(), unbound_discharge_macaroon.serialize()
        )(r)
        auth_value = r.headers["Authorization"]
        self.assertThat(auth_value, StartsWith("Macaroon "))
        self.assertThat(
            parse_dict_header(auth_value[len("Macaroon ") :]),
            MacaroonsVerify(root_key),
        )

    def test_good_no_discharge(self):
        r = Request()
        root_key = hashlib.sha256(b"root").hexdigest()
        root_macaroon = Macaroon(key=root_key)
        MacaroonAuth(root_macaroon.serialize())(r)
        auth_value = r.headers["Authorization"]
        self.assertThat(auth_value, StartsWith("Macaroon "))
        self.assertThat(
            parse_dict_header(auth_value[len("Macaroon ") :]),
            MacaroonsVerify(root_key),
        )

    def test_bad_framing(self):
        r = Request()
        self.assertRaises(
            InvalidStoreSecretsError, MacaroonAuth('ev"il', 'wic"ked'), r
        )
        # Test _makeAuthParam's behaviour directly in case somebody somehow
        # convinces Macaroon.serialize to emit data that breaks framing.
        self.assertRaises(
            InvalidStoreSecretsError,
            MacaroonAuth(None)._makeAuthParam,
            'ev"il',
            "good",
        )
        self.assertRaises(
            InvalidStoreSecretsError,
            MacaroonAuth(None)._makeAuthParam,
            "good",
            'ev"il',
        )

    def test_logging(self):
        r = Request()
        root_key = hashlib.sha256(b"root").hexdigest()
        root_macaroon = Macaroon(key=root_key)
        discharge_key = hashlib.sha256(b"discharge").hexdigest()
        discharge_caveat_id = '{"secret": "thing"}'
        root_macaroon.add_third_party_caveat(
            "sso.example", discharge_key, discharge_caveat_id
        )
        root_macaroon.add_first_party_caveat(
            "store.example|package_id|{}".format(
                json.dumps(["example-package"])
            )
        )
        unbound_discharge_macaroon = Macaroon(
            location="sso.example",
            key=discharge_key,
            identifier=discharge_caveat_id,
        )
        unbound_discharge_macaroon.add_first_party_caveat(
            "sso.example|account|{}".format(
                base64.b64encode(
                    json.dumps(
                        {
                            "openid": "1234567",
                            "email": "user@example.org",
                        }
                    ).encode("ASCII")
                ).decode("ASCII")
            )
        )
        logger = BufferLogger()
        MacaroonAuth(
            root_macaroon.serialize(),
            unbound_discharge_macaroon.serialize(),
            logger=logger,
        )(r)
        self.assertEqual(
            [
                'DEBUG root macaroon: snap-ids: ["example-package"]',
                "DEBUG discharge macaroon: OpenID identifier: 1234567",
            ],
            logger.getLogBuffer().splitlines(),
        )


class RequestMatches(Matcher):
    """Matches a request with the specified attributes."""

    def __init__(
        self, url, auth=None, json_data=None, form_data=None, **kwargs
    ):
        self.url = url
        self.auth = auth
        self.json_data = json_data
        self.form_data = form_data
        self.kwargs = kwargs

    def __str__(self):
        return (
            "RequestMatches({!r}, auth={}, json_data={}, form_data={}, "
            "**{})".format(
                self.url,
                self.auth,
                self.json_data,
                self.form_data,
                self.kwargs,
            )
        )

    def match(self, request):
        mismatch = MatchesStructure(url=self.url, **self.kwargs).match(request)
        if mismatch is not None:
            return mismatch
        if self.auth is not None:
            mismatch = Contains("Authorization").match(request.headers)
            if mismatch is not None:
                return mismatch
            auth_value = request.headers["Authorization"]
            auth_scheme, auth_params_matcher = self.auth
            mismatch = StartsWith(auth_scheme + " ").match(auth_value)
            if mismatch is not None:
                return mismatch
            mismatch = auth_params_matcher.match(
                parse_dict_header(auth_value[len(auth_scheme + " ") :])
            )
            if mismatch is not None:
                return mismatch
        if self.json_data is not None:
            mismatch = Equals(self.json_data).match(json.loads(request.body))
            if mismatch is not None:
                return mismatch
        if self.form_data is not None:
            if hasattr(request.body, "read"):
                body = request.body.read()
            else:
                body = request.body
            fs = FieldStorage(
                fp=io.BytesIO(body),
                environ={"REQUEST_METHOD": request.method},
                headers=request.headers,
            )
            mismatch = MatchesDict(self.form_data).match(fs)
            if mismatch is not None:
                return mismatch


class TestSnapStoreClient(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.pushConfig(
            "snappy",
            store_url="http://sca.example/",
            store_upload_url="http://updown.example/",
        )
        self.pushConfig(
            "launchpad", openid_provider_root="http://sso.example/"
        )
        self.client = getUtility(ISnapStoreClient)
        self.unscanned_upload_requests = []
        self.channels = [
            {"name": "stable", "display_name": "Stable"},
            {"name": "edge", "display_name": "Edge"},
        ]
        self.channels_memcache_key = b"search.example:channels"

    def _make_store_secrets(self, encrypted=False):
        self.root_key = hashlib.sha256(
            self.factory.getUniqueBytes()
        ).hexdigest()
        root_macaroon = Macaroon(key=self.root_key)
        self.discharge_key = hashlib.sha256(
            self.factory.getUniqueBytes()
        ).hexdigest()
        self.discharge_caveat_id = self.factory.getUniqueString()
        root_macaroon.add_third_party_caveat(
            "sso.example", self.discharge_key, self.discharge_caveat_id
        )
        unbound_discharge_macaroon = Macaroon(
            location="sso.example",
            key=self.discharge_key,
            identifier=self.discharge_caveat_id,
        )
        secrets = {"root": root_macaroon.serialize()}
        if encrypted:
            container = getUtility(IEncryptedContainer, "snap-store-secrets")
            secrets["discharge_encrypted"] = removeSecurityProxy(
                container.encrypt(
                    unbound_discharge_macaroon.serialize().encode("UTF-8")
                )
            )
        else:
            secrets["discharge"] = unbound_discharge_macaroon.serialize()
        return secrets

    def _addUnscannedUploadResponse(self):
        responses.add(
            "POST",
            "http://updown.example/unscanned-upload/",
            json={"successful": True, "upload_id": 1},
        )

    def _addSnapPushResponse(self):
        responses.add(
            "POST",
            "http://sca.example/dev/api/snap-push/",
            status=202,
            json={
                "success": True,
                "status_details_url": (
                    "http://sca.example/dev/api/snaps/1/builds/1/status"
                ),
            },
        )

    def _addMacaroonRefreshResponse(self):
        def callback(request):
            new_macaroon = Macaroon(
                location="sso.example",
                key=self.discharge_key,
                identifier=self.discharge_caveat_id,
            )
            new_macaroon.add_first_party_caveat("sso|expires|tomorrow")
            return (
                200,
                {},
                json.dumps({"discharge_macaroon": new_macaroon.serialize()}),
            )

        responses.add_callback(
            "POST",
            "http://sso.example/api/v2/tokens/refresh",
            callback=callback,
            content_type="application/json",
        )

    def _addChannelsResponse(self):
        responses.add(
            "GET",
            "http://search.example/api/v1/channels",
            json={"_embedded": {"clickindex:channel": self.channels}},
        )
        self.addCleanup(
            getUtility(IMemcacheClient).delete, self.channels_memcache_key
        )

    @responses.activate
    def test_requestPackageUploadPermission(self):
        snappy_series = self.factory.makeSnappySeries(name="rolling")
        responses.add(
            "POST",
            "http://sca.example/dev/api/acl/",
            json={"macaroon": "dummy"},
        )
        macaroon = self.client.requestPackageUploadPermission(
            snappy_series, "test-snap"
        )
        self.assertThat(
            responses.calls[-1].request,
            RequestMatches(
                url=Equals("http://sca.example/dev/api/acl/"),
                method=Equals("POST"),
                json_data={
                    "packages": [{"name": "test-snap", "series": "rolling"}],
                    "permissions": ["package_upload"],
                },
            ),
        )
        self.assertEqual("dummy", macaroon)
        request = get_current_browser_request()
        start, stop = get_request_timeline(request).actions[-2:]
        self.assertEqual("request-snap-upload-macaroon-start", start.category)
        self.assertEqual("rolling/test-snap", start.detail)
        self.assertEqual("request-snap-upload-macaroon-stop", stop.category)
        self.assertEqual("rolling/test-snap", stop.detail)

    @responses.activate
    def test_requestPackageUploadPermission_missing_macaroon(self):
        snappy_series = self.factory.makeSnappySeries()
        responses.add("POST", "http://sca.example/dev/api/acl/", json={})
        self.assertRaisesWithContent(
            BadRequestPackageUploadResponse,
            "{}",
            self.client.requestPackageUploadPermission,
            snappy_series,
            "test-snap",
        )

    @responses.activate
    def test_requestPackageUploadPermission_error(self):
        snappy_series = self.factory.makeSnappySeries()
        responses.add(
            "POST",
            "http://sca.example/dev/api/acl/",
            status=503,
            json={"error_list": [{"message": "Failed"}]},
        )
        self.assertRaisesWithContent(
            BadRequestPackageUploadResponse,
            "Failed",
            self.client.requestPackageUploadPermission,
            snappy_series,
            "test-snap",
        )

    @responses.activate
    def test_requestPackageUploadPermission_404(self):
        snappy_series = self.factory.makeSnappySeries()
        responses.add("POST", "http://sca.example/dev/api/acl/", status=404)
        self.assertRaisesWithContent(
            SnapNotFoundResponse,
            "404 Client Error: Not Found",
            self.client.requestPackageUploadPermission,
            snappy_series,
            "test-snap",
        )

    def makeUploadableSnapBuild(self, store_secrets=None, encrypted=False):
        if store_secrets is None:
            store_secrets = self._make_store_secrets(encrypted=encrypted)
        snap = self.factory.makeSnap(
            store_upload=True,
            store_series=self.factory.makeSnappySeries(name="rolling"),
            store_name="test-snap",
            store_secrets=store_secrets,
        )
        snapbuild = self.factory.makeSnapBuild(snap=snap)
        snap_lfa = self.factory.makeLibraryFileAlias(
            filename="test-snap.snap", content=b"dummy snap content"
        )
        self.factory.makeSnapFile(snapbuild=snapbuild, libraryfile=snap_lfa)
        manifest_lfa = self.factory.makeLibraryFileAlias(
            filename="test-snap.manifest", content=b"dummy manifest content"
        )
        self.factory.makeSnapFile(
            snapbuild=snapbuild, libraryfile=manifest_lfa
        )
        snapbuild.updateStatus(BuildStatus.BUILDING)
        snapbuild.updateStatus(BuildStatus.FULLYBUILT)
        return snapbuild

    @responses.activate
    def test_uploadFile(self):
        snap_lfa = self.factory.makeLibraryFileAlias(
            filename="test-snap.snap", content=b"dummy snap content"
        )
        transaction.commit()
        self._addUnscannedUploadResponse()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.assertEqual(1, self.client.uploadFile(snap_lfa))
        requests = [call.request for call in responses.calls]
        self.assertThat(
            requests,
            MatchesListwise(
                [
                    RequestMatches(
                        url=Equals("http://updown.example/unscanned-upload/"),
                        method=Equals("POST"),
                        form_data={
                            "binary": MatchesStructure.byEquality(
                                name="binary",
                                filename="test-snap.snap",
                                value=b"dummy snap content",
                                type="application/octet-stream",
                            )
                        },
                    ),
                ]
            ),
        )

    @responses.activate
    def test_uploadFile_error(self):
        snap_lfa = self.factory.makeLibraryFileAlias(
            filename="test-snap.snap", content=b"dummy snap content"
        )
        transaction.commit()
        responses.add(
            "POST",
            "http://updown.example/unscanned-upload/",
            status=502,
            body="The proxy exploded.\n",
        )
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            err = self.assertRaises(
                UploadFailedResponse, self.client.uploadFile, snap_lfa
            )
            self.assertEqual("502 Server Error: Bad Gateway", str(err))
            self.assertEqual("The proxy exploded.\n", err.detail)
            self.assertTrue(err.can_retry)

    @responses.activate
    def test_push(self):
        snapbuild = self.makeUploadableSnapBuild()
        transaction.commit()
        self._addSnapPushResponse()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.assertEqual(
                "http://sca.example/dev/api/snaps/1/builds/1/status",
                self.client.push(snapbuild, 1),
            )
        requests = [call.request for call in responses.calls]
        self.assertThat(
            requests,
            MatchesListwise(
                [
                    RequestMatches(
                        url=Equals("http://sca.example/dev/api/snap-push/"),
                        method=Equals("POST"),
                        headers=ContainsDict(
                            {"Content-Type": Equals("application/json")}
                        ),
                        auth=("Macaroon", MacaroonsVerify(self.root_key)),
                        json_data={
                            "name": "test-snap",
                            "updown_id": 1,
                            "series": "rolling",
                            "built_at": snapbuild.date_started.isoformat(),
                        },
                    ),
                ]
            ),
        )

    @responses.activate
    def test_push_with_release_intent(self):
        snapbuild = self.makeUploadableSnapBuild()
        snapbuild.snap.store_channels = ["beta", "edge"]
        transaction.commit()
        self._addSnapPushResponse()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.assertEqual(
                "http://sca.example/dev/api/snaps/1/builds/1/status",
                self.client.push(snapbuild, 1),
            )
        requests = [call.request for call in responses.calls]
        self.assertThat(
            requests,
            MatchesListwise(
                [
                    RequestMatches(
                        url=Equals("http://sca.example/dev/api/snap-push/"),
                        method=Equals("POST"),
                        headers=ContainsDict(
                            {"Content-Type": Equals("application/json")}
                        ),
                        auth=("Macaroon", MacaroonsVerify(self.root_key)),
                        json_data={
                            "name": "test-snap",
                            "updown_id": 1,
                            "series": "rolling",
                            "built_at": snapbuild.date_started.isoformat(),
                            "only_if_newer": True,
                            "channels": ["beta", "edge"],
                        },
                    ),
                ]
            ),
        )

    @responses.activate
    def test_push_no_discharge(self):
        root_key = hashlib.sha256(self.factory.getUniqueBytes()).hexdigest()
        root_macaroon = Macaroon(key=root_key)
        snapbuild = self.makeUploadableSnapBuild(
            store_secrets={"root": root_macaroon.serialize()}
        )
        transaction.commit()
        self._addSnapPushResponse()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.assertEqual(
                "http://sca.example/dev/api/snaps/1/builds/1/status",
                self.client.push(snapbuild, 1),
            )
        requests = [call.request for call in responses.calls]
        self.assertThat(
            requests,
            MatchesListwise(
                [
                    RequestMatches(
                        url=Equals("http://sca.example/dev/api/snap-push/"),
                        method=Equals("POST"),
                        headers=ContainsDict(
                            {"Content-Type": Equals("application/json")}
                        ),
                        auth=("Macaroon", MacaroonsVerify(root_key)),
                        json_data={
                            "name": "test-snap",
                            "updown_id": 1,
                            "series": "rolling",
                            "built_at": snapbuild.date_started.isoformat(),
                        },
                    ),
                ]
            ),
        )

    @responses.activate
    def test_push_encrypted_discharge(self):
        private_key = PrivateKey.generate()
        self.pushConfig(
            "snappy",
            store_secrets_public_key=base64.b64encode(
                bytes(private_key.public_key)
            ).decode("UTF-8"),
            store_secrets_private_key=base64.b64encode(
                bytes(private_key)
            ).decode("UTF-8"),
        )
        snapbuild = self.makeUploadableSnapBuild(encrypted=True)
        transaction.commit()
        self._addSnapPushResponse()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.assertEqual(
                "http://sca.example/dev/api/snaps/1/builds/1/status",
                self.client.push(snapbuild, 1),
            )
        requests = [call.request for call in responses.calls]
        self.assertThat(
            requests,
            MatchesListwise(
                [
                    RequestMatches(
                        url=Equals("http://sca.example/dev/api/snap-push/"),
                        method=Equals("POST"),
                        headers=ContainsDict(
                            {"Content-Type": Equals("application/json")}
                        ),
                        auth=("Macaroon", MacaroonsVerify(self.root_key)),
                        json_data={
                            "name": "test-snap",
                            "updown_id": 1,
                            "series": "rolling",
                            "built_at": snapbuild.date_started.isoformat(),
                        },
                    ),
                ]
            ),
        )

    @responses.activate
    def test_push_unauthorized(self):
        store_secrets = self._make_store_secrets()
        snapbuild = self.makeUploadableSnapBuild(store_secrets=store_secrets)
        transaction.commit()
        snap_push_error = {
            "code": "macaroon-permission-required",
            "message": "Permission is required: package_push",
        }
        responses.add(
            "POST",
            "http://sca.example/dev/api/snap-push/",
            status=401,
            headers={"WWW-Authenticate": 'Macaroon realm="Devportal"'},
            json={"error_list": [snap_push_error]},
        )
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.assertRaisesWithContent(
                UnauthorizedUploadResponse,
                "Permission is required: package_push",
                self.client.push,
                snapbuild,
                1,
            )

    @responses.activate
    def test_push_needs_discharge_macaroon_refresh(self):
        store_secrets = self._make_store_secrets()
        snapbuild = self.makeUploadableSnapBuild(store_secrets=store_secrets)
        transaction.commit()
        responses.add(
            "POST",
            "http://sca.example/dev/api/snap-push/",
            status=401,
            headers={"WWW-Authenticate": "Macaroon needs_refresh=1"},
        )
        self._addMacaroonRefreshResponse()
        self._addSnapPushResponse()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.assertEqual(
                "http://sca.example/dev/api/snaps/1/builds/1/status",
                self.client.push(snapbuild, 1),
            )
        requests = [call.request for call in responses.calls]
        self.assertThat(
            requests,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(
                        path_url="/dev/api/snap-push/"
                    ),
                    MatchesStructure.byEquality(
                        path_url="/api/v2/tokens/refresh"
                    ),
                    MatchesStructure.byEquality(
                        path_url="/dev/api/snap-push/"
                    ),
                ]
            ),
        )
        self.assertNotEqual(
            store_secrets["discharge"],
            snapbuild.snap.store_secrets["discharge"],
        )

    @responses.activate
    def test_push_needs_encrypted_discharge_macaroon_refresh(self):
        private_key = PrivateKey.generate()
        self.pushConfig(
            "snappy",
            store_secrets_public_key=base64.b64encode(
                bytes(private_key.public_key)
            ).decode("UTF-8"),
            store_secrets_private_key=base64.b64encode(
                bytes(private_key)
            ).decode("UTF-8"),
        )
        store_secrets = self._make_store_secrets(encrypted=True)
        snapbuild = self.makeUploadableSnapBuild(store_secrets=store_secrets)
        transaction.commit()
        responses.add(
            "POST",
            "http://sca.example/dev/api/snap-push/",
            status=401,
            headers={"WWW-Authenticate": "Macaroon needs_refresh=1"},
        )
        self._addMacaroonRefreshResponse()
        self._addSnapPushResponse()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.assertEqual(
                "http://sca.example/dev/api/snaps/1/builds/1/status",
                self.client.push(snapbuild, 1),
            )
        requests = [call.request for call in responses.calls]
        self.assertThat(
            requests,
            MatchesListwise(
                [
                    MatchesStructure.byEquality(
                        path_url="/dev/api/snap-push/"
                    ),
                    MatchesStructure.byEquality(
                        path_url="/api/v2/tokens/refresh"
                    ),
                    MatchesStructure.byEquality(
                        path_url="/dev/api/snap-push/"
                    ),
                ]
            ),
        )
        self.assertNotEqual(
            store_secrets["discharge_encrypted"],
            snapbuild.snap.store_secrets["discharge_encrypted"],
        )

    @responses.activate
    def test_push_unsigned_agreement(self):
        store_secrets = self._make_store_secrets()
        snapbuild = self.makeUploadableSnapBuild(store_secrets=store_secrets)
        transaction.commit()
        snap_push_error = {"message": "Developer has not signed agreement."}
        responses.add(
            "POST",
            "http://sca.example/dev/api/snap-push/",
            status=403,
            json={"error_list": [snap_push_error]},
        )
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            err = self.assertRaises(
                UploadFailedResponse, self.client.push, snapbuild, 1
            )
            self.assertEqual("Developer has not signed agreement.", str(err))
            self.assertFalse(err.can_retry)

    @responses.activate
    def test_refresh_discharge_macaroon(self):
        store_secrets = self._make_store_secrets()
        snap = self.factory.makeSnap(
            store_upload=True,
            store_series=self.factory.makeSnappySeries(name="rolling"),
            store_name="test-snap",
            store_secrets=store_secrets,
        )
        self._addMacaroonRefreshResponse()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.client.refreshDischargeMacaroon(snap)
        self.assertThat(
            responses.calls[-1].request,
            RequestMatches(
                url=Equals("http://sso.example/api/v2/tokens/refresh"),
                method=Equals("POST"),
                headers=ContainsDict(
                    {"Content-Type": Equals("application/json")}
                ),
                json_data={"discharge_macaroon": store_secrets["discharge"]},
            ),
        )
        self.assertNotEqual(
            store_secrets["discharge"], snap.store_secrets["discharge"]
        )

    @responses.activate
    def test_refresh_encrypted_discharge_macaroon(self):
        private_key = PrivateKey.generate()
        self.pushConfig(
            "snappy",
            store_secrets_public_key=base64.b64encode(
                bytes(private_key.public_key)
            ).decode("UTF-8"),
            store_secrets_private_key=base64.b64encode(
                bytes(private_key)
            ).decode("UTF-8"),
        )
        store_secrets = self._make_store_secrets(encrypted=True)
        snap = self.factory.makeSnap(
            store_upload=True,
            store_series=self.factory.makeSnappySeries(name="rolling"),
            store_name="test-snap",
            store_secrets=store_secrets,
        )
        self._addMacaroonRefreshResponse()
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            self.client.refreshDischargeMacaroon(snap)
        container = getUtility(IEncryptedContainer, "snap-store-secrets")
        self.assertThat(
            responses.calls[-1].request,
            RequestMatches(
                url=Equals("http://sso.example/api/v2/tokens/refresh"),
                method=Equals("POST"),
                headers=ContainsDict(
                    {"Content-Type": Equals("application/json")}
                ),
                json_data={
                    "discharge_macaroon": container.decrypt(
                        store_secrets["discharge_encrypted"]
                    ).decode("UTF-8"),
                },
            ),
        )
        self.assertNotEqual(
            store_secrets["discharge_encrypted"],
            snap.store_secrets["discharge_encrypted"],
        )

    @responses.activate
    def test_checkStatus_pending(self):
        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        responses.add(
            "GET",
            status_url,
            json={
                "code": "being_processed",
                "processed": False,
                "can_release": False,
            },
        )
        self.assertRaises(
            UploadNotScannedYetResponse, self.client.checkStatus, status_url
        )

    @responses.activate
    def test_checkStatus_error(self):
        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        responses.add(
            "GET",
            status_url,
            json={
                "code": "processing_error",
                "processed": True,
                "can_release": False,
                "errors": [
                    {
                        "code": None,
                        "message": "You cannot use that reserved namespace.",
                        "link": "http://example.com",
                    }
                ],
            },
        )
        self.assertRaisesWithContent(
            ScanFailedResponse,
            "You cannot use that reserved namespace.",
            self.client.checkStatus,
            status_url,
        )

    @responses.activate
    def test_checkStatus_review_error(self):
        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        responses.add(
            "GET",
            status_url,
            json={
                "code": "processing_error",
                "processed": True,
                "can_release": False,
                "errors": [{"code": None, "message": "Review failed."}],
                "url": "http://sca.example/dev/click-apps/1/rev/1/",
            },
        )
        self.assertRaisesWithContent(
            ScanFailedResponse,
            "Review failed.",
            self.client.checkStatus,
            status_url,
        )

    @responses.activate
    def test_checkStatus_complete(self):
        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        responses.add(
            "GET",
            status_url,
            json={
                "code": "ready_to_release",
                "processed": True,
                "can_release": True,
                "url": "http://sca.example/dev/click-apps/1/rev/1/",
                "revision": 1,
            },
        )
        self.assertEqual(
            ("http://sca.example/dev/click-apps/1/rev/1/", 1),
            self.client.checkStatus(status_url),
        )

    @responses.activate
    def test_checkStatus_404(self):
        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        responses.add("GET", status_url, status=404)
        self.assertRaisesWithContent(
            BadScanStatusResponse,
            "404 Client Error: Not Found",
            self.client.checkStatus,
            status_url,
        )

    @responses.activate
    def test_checkStatus_manual_review(self):
        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        responses.add(
            "GET",
            status_url,
            json={
                "errors": [
                    {
                        "code": None,
                        "link": None,
                        "message": (
                            "found potentially sensitive files in package"
                        ),
                    }
                ],
                "url": "http://sca.example/dev/click-apps/1/rev/1/",
                "code": "need_manual_review",
                "processed": True,
                "can_release": False,
                "revision": 1,
            },
        )
        self.assertEqual(
            ("http://sca.example/dev/click-apps/1/rev/1/", 1),
            self.client.checkStatus(status_url),
        )

    @responses.activate
    def test_checkStatus_review_queued(self):
        status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        responses.add(
            "GET",
            status_url,
            json={
                "errors": [
                    {
                        "code": "review-queued",
                        "message": (
                            "Waiting for previous upload(s) to complete their "
                            "review process."
                        ),
                    }
                ],
                "code": "processing_error",
                "processed": True,
                "can_release": False,
            },
        )
        self.assertEqual((None, None), self.client.checkStatus(status_url))
