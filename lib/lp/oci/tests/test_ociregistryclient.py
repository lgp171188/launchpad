# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the OCI Registry client."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from functools import partial
import json
import os
import tarfile
import uuid

from fixtures import MockPatch
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    )
import responses
from six import StringIO
from tenacity import RetryError
from testtools.matchers import (
    AfterPreprocessing,
    Equals,
    MatchesDict,
    MatchesException,
    MatchesListwise,
    Raises,
    )
import transaction
from zope.security.proxy import removeSecurityProxy

from lp.oci.interfaces.ociregistryclient import (
    BlobUploadFailed,
    ManifestUploadFailed,
    )
from lp.oci.model.ociregistryclient import (
    BearerTokenRegistryClient,
    OCIRegistryAuthenticationError,
    OCIRegistryClient,
    proxy_urlfetch,
    RegistryHTTPClient,
    )
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.services.compat import mock
from lp.testing import TestCaseWithFactory
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )


class SpyProxyCallsMixin:
    def setupProxySpy(self):
        self.proxy_call_count = 0

        def count_proxy_call_count(*args, **kwargs):
            self.proxy_call_count += 1
            return proxy_urlfetch(*args, **kwargs)

        self.useFixture(MockPatch(
            'lp.oci.model.ociregistryclient.proxy_urlfetch',
            side_effect=count_proxy_call_count))


class TestOCIRegistryClient(OCIConfigHelperMixin, SpyProxyCallsMixin,
                            TestCaseWithFactory):

    layer = LaunchpadZopelessLayer
    retry_count = 0

    def setUp(self):
        super(TestOCIRegistryClient, self).setUp()
        self.setConfig()
        self.setupProxySpy()
        self.manifest = [{
            "Config": "config_file_1.json",
            "Layers": ["layer_1/layer.tar", "layer_2/layer.tar"]}]
        self.digests = [{
            "diff_id_1": {
                "digest": "digest_1",
                "source": "test/base_1",
                "layer_id": "layer_1"
            },
            "diff_id_2": {
                "digest": "digest_2",
                "source": "",
                "layer_id": "layer_2"
            }
        }]
        self.config = {"rootfs": {"diff_ids": ["diff_id_1", "diff_id_2"]}}
        self.build = self.factory.makeOCIRecipeBuild()
        self.push_rule = self.factory.makeOCIPushRule(recipe=self.build.recipe)
        self.client = OCIRegistryClient()

    def _makeFiles(self):
        self.factory.makeOCIFile(
            build=self.build,
            content=json.dumps(self.manifest),
            filename='manifest.json',
        )
        self.factory.makeOCIFile(
            build=self.build,
            content=json.dumps(self.digests),
            filename='digests.json',
        )
        self.factory.makeOCIFile(
            build=self.build,
            content=json.dumps(self.config),
            filename='config_file_1.json'
        )

        tmpdir = self.makeTemporaryDirectory()
        self.layer_files = []
        for i in range(1, 3):
            digest = 'digest_%i' % i
            file_name = 'digest_%s_filename' % i
            file_path = os.path.join(tmpdir, file_name)

            with open(file_path, 'w') as fd:
                fd.write(digest)

            fileout = StringIO()
            tar = tarfile.open(mode="w:gz", fileobj=fileout)
            tar.add(file_path, 'layer.tar')
            tar.close()

            fileout.seek(0)
            # make layer files
            self.layer_files.append(self.factory.makeOCIFile(
                build=self.build,
                content=fileout.read(),
                filename=file_name,
                layer_file_digest=digest
            ))

        transaction.commit()

    @responses.activate
    def test_upload(self):
        self._makeFiles()
        self.useFixture(MockPatch(
            "lp.oci.model.ociregistryclient.OCIRegistryClient._upload"))
        self.useFixture(MockPatch(
            "lp.oci.model.ociregistryclient.OCIRegistryClient._upload_layer"))

        push_rule = self.build.recipe.push_rules[0]
        responses.add("GET", "%s/v2/" % push_rule.registry_url, status=200)

        manifests_url = "{}/v2/{}/manifests/edge".format(
            push_rule.registry_credentials.url,
            push_rule.image_name
        )
        responses.add("PUT", manifests_url, status=201)

        self.client.upload(self.build)

        request = json.loads(responses.calls[1].request.body)

        self.assertThat(request, MatchesDict({
            "layers": MatchesListwise([
                MatchesDict({
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"),
                    "digest": Equals("diff_id_1"),
                    "size": Equals(
                        self.layer_files[0].library_file.content.filesize)}),
                MatchesDict({
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"),
                    "digest": Equals("diff_id_2"),
                    "size": Equals(
                        self.layer_files[1].library_file.content.filesize)})
            ]),
            "schemaVersion": Equals(2),
            "config": MatchesDict({
                "mediaType": Equals(
                    "application/vnd.docker.container.image.v1+json"),
                "digest": Equals(
                    "sha256:33b69b4b6e106f9fc7a8b93409"
                    "36c85cf7f84b2d017e7b55bee6ab214761f6ab"),
                "size": Equals(52)
            }),
            "mediaType": Equals(
                "application/vnd.docker.distribution.manifest.v2+json")
        }))

    @responses.activate
    def test_upload_formats_credentials(self):
        self._makeFiles()
        _upload_fixture = self.useFixture(MockPatch(
            "lp.oci.model.ociregistryclient.OCIRegistryClient._upload"))
        self.useFixture(MockPatch(
            "lp.oci.model.ociregistryclient.OCIRegistryClient._upload_layer"))

        self.push_rule.registry_credentials.setCredentials({
            "username": "test-username",
            "password": "test-password"
        })

        push_rule = self.build.recipe.push_rules[0]
        responses.add("GET", "%s/v2/" % push_rule.registry_url, status=200)

        manifests_url = "{}/v2/{}/manifests/edge".format(
            push_rule.registry_credentials.url, push_rule.image_name)
        responses.add("PUT", manifests_url, status=201)

        self.client.upload(self.build)

        http_client = _upload_fixture.mock.call_args_list[0][0][-1]
        self.assertEqual(
            http_client.credentials, ('test-username', 'test-password'))

    def test_preloadFiles(self):
        self._makeFiles()
        files = self.client._preloadFiles(
            self.build, self.manifest, self.digests[0])

        self.assertThat(files, MatchesDict({
            'config_file_1.json': MatchesDict({
                'config_file': Equals(self.config),
                'diff_id_1': Equals(self.layer_files[0].library_file),
                'diff_id_2': Equals(self.layer_files[1].library_file)})}))

    def test_calculateTag(self):
        result = self.client._calculateTag(
            self.build, self.build.recipe.push_rules[0])
        self.assertEqual("edge", result)

    def test_build_registry_manifest(self):
        self._makeFiles()
        preloaded_data = self.client._preloadFiles(
            self.build, self.manifest, self.digests[0])
        manifest = self.client._build_registry_manifest(
            self.digests[0],
            self.config,
            json.dumps(self.config),
            "config-sha",
            preloaded_data["config_file_1.json"])
        self.assertThat(manifest, MatchesDict({
            "layers": MatchesListwise([
                MatchesDict({
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"),
                    "digest": Equals("diff_id_1"),
                    "size": Equals(
                        self.layer_files[0].library_file.content.filesize)}),
                MatchesDict({
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"),
                    "digest": Equals("diff_id_2"),
                    "size": Equals(
                        self.layer_files[1].library_file.content.filesize)})
            ]),
            "schemaVersion": Equals(2),
            "config": MatchesDict({
                "mediaType": Equals(
                    "application/vnd.docker.container.image.v1+json"),
                "digest": Equals("sha256:config-sha"),
                "size": Equals(52)
            }),
            "mediaType": Equals(
                "application/vnd.docker.distribution.manifest.v2+json")
        }))

    @responses.activate
    def test_upload_handles_existing(self):
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = "{}/blobs/{}".format(
            http_client.api_url, "test-digest")
        responses.add("HEAD", blobs_url, status=200)
        push_rule = self.build.recipe.push_rules[0]
        push_rule.registry_credentials.setCredentials({})
        self.client._upload(
            "test-digest", push_rule, None, http_client)

        self.assertEqual(len(responses.calls), self.proxy_call_count)
        # There should be no auth headers for these calls
        for call in responses.calls:
            self.assertNotIn('Authorization', call.request.headers.keys())

    @responses.activate
    def test_upload_check_existing_raises_non_404(self):
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = "{}/blobs/{}".format(
            http_client.api_url, "test-digest")
        responses.add("HEAD", blobs_url, status=500)
        push_rule = self.build.recipe.push_rules[0]
        self.assertEqual(len(responses.calls), self.proxy_call_count)
        self.assertRaises(
            HTTPError,
            self.client._upload,
            "test-digest",
            push_rule,
            None,
            http_client)

    @responses.activate
    def test_upload_passes_basic_auth(self):
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = "{}/blobs/{}".format(
            http_client.api_url, "test-digest")
        responses.add("HEAD", blobs_url, status=200)
        push_rule.registry_credentials.setCredentials({
            "username": "user", "password": "password"})
        self.client._upload(
            "test-digest", push_rule, None,
            http_client)

        self.assertEqual(len(responses.calls), self.proxy_call_count)
        for call in responses.calls:
            self.assertEqual(
                'Basic dXNlcjpwYXNzd29yZA==',
                call.request.headers['Authorization'])

    def test_upload_retries_exception(self):
        # Use a separate counting mechanism so we're not entirely relying
        # on tenacity to tell us that it has retried.
        def count_retries(*args, **kwargs):
            self.retry_count += 1
            raise ConnectionError

        self.useFixture(MockPatch(
            'lp.oci.model.ociregistryclient.proxy_urlfetch',
            side_effect=count_retries
        ))
        # Patch sleep so we don't need to change our arguments and the
        # test is instant
        self.client._upload.retry.sleep = lambda x: None

        try:
            push_rule = self.build.recipe.push_rules[0]
            self.client._upload(
                "test-digest", push_rule,
                None, RegistryHTTPClient(push_rule))
        except RetryError:
            pass
        # Check that tenacity and our counting agree
        self.assertEqual(
            5, self.client._upload.retry.statistics["attempt_number"])
        self.assertEqual(5, self.retry_count)

    @responses.activate
    def test_upload_put_blob_raises_error(self):
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = "{}/blobs/{}".format(
            http_client.api_url, "test-digest")
        uploads_url = "{}/blobs/uploads/".format(http_client.api_url)
        upload_url = "{}/blobs/uploads/{}".format(
            http_client.api_url, uuid.uuid4())
        put_errors = [
            {
                "code": "BLOB_UPLOAD_INVALID",
                "message": "blob upload invalid",
                "detail": [],
                },
            ]
        responses.add("HEAD", blobs_url, status=404)
        responses.add("POST", uploads_url, headers={"Location": upload_url})
        responses.add(
            "PUT", upload_url, status=400, json={"errors": put_errors})
        self.assertThat(
            partial(
                self.client._upload,
                "test-digest", push_rule, None, http_client),
            Raises(MatchesException(
                BlobUploadFailed,
                AfterPreprocessing(
                    str,
                    Equals(
                        "Upload of {} for {} failed".format(
                            "test-digest", push_rule.image_name))))))

    @responses.activate
    def test_upload_put_manifest_raises_error(self):
        self._makeFiles()
        self.useFixture(MockPatch(
            "lp.oci.model.ociregistryclient.OCIRegistryClient._upload"))
        self.useFixture(MockPatch(
            "lp.oci.model.ociregistryclient.OCIRegistryClient._upload_layer"))

        push_rule = self.build.recipe.push_rules[0]
        responses.add(
            "GET", "{}/v2/".format(push_rule.registry_url), status=200)

        manifests_url = "{}/v2/{}/manifests/edge".format(
            push_rule.registry_credentials.url,
            push_rule.image_name
        )
        put_errors = [
            {
                "code": "MANIFEST_INVALID",
                "message": "manifest invalid",
                "detail": [],
                },
            ]
        responses.add(
            "PUT", manifests_url, status=400, json={"errors": put_errors})

        self.assertThat(
            partial(self.client.upload, self.build),
            Raises(MatchesException(
                ManifestUploadFailed,
                AfterPreprocessing(
                    str,
                    Equals(
                        "Failed to upload manifest for {} in {}".format(
                            self.build.recipe.name, self.build.id))))))


class TestRegistryHTTPClient(OCIConfigHelperMixin, SpyProxyCallsMixin,
                             TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestRegistryHTTPClient, self).setUp()
        self.setConfig()
        self.setupProxySpy()

    @responses.activate
    def test_get_default_client_instance(self):
        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://the-registry.test",
            credentials={'username': 'the-user', 'password': "the-passwd"})
        push_rule = removeSecurityProxy(self.factory.makeOCIPushRule(
            registry_credentials=credentials,
            image_name="the-user/test-image"))

        responses.add("GET", "%s/v2/" % push_rule.registry_url, status=200)

        instance = RegistryHTTPClient.getInstance(push_rule)
        self.assertEqual(RegistryHTTPClient, type(instance))

        self.assertEqual(1, len(responses.calls))
        self.assertEqual(1, self.proxy_call_count)
        call = responses.calls[0]
        self.assertEqual("%s/v2/" % push_rule.registry_url, call.request.url)

    @responses.activate
    def test_get_bearer_token_client_instance(self):
        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://the-registry.test",
            credentials={'username': 'the-user', 'password': "the-passwd"})
        push_rule = removeSecurityProxy(self.factory.makeOCIPushRule(
            registry_credentials=credentials,
            image_name="the-user/test-image"))

        responses.add(
            "GET", "%s/v2/" % push_rule.registry_url, status=401, headers={
                "Www-Authenticate": 'Bearer realm="something.com"'})

        instance = RegistryHTTPClient.getInstance(push_rule)
        self.assertEqual(BearerTokenRegistryClient, type(instance))

        self.assertEqual(1, len(responses.calls))
        self.assertEqual(1, self.proxy_call_count)
        call = responses.calls[0]
        self.assertEqual("%s/v2/" % push_rule.registry_url, call.request.url)

    @responses.activate
    def test_get_basic_auth_client_instance(self):
        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://the-registry.test",
            credentials={'username': 'the-user', 'password': "the-passwd"})
        push_rule = removeSecurityProxy(self.factory.makeOCIPushRule(
            registry_credentials=credentials,
            image_name="the-user/test-image"))

        responses.add(
            "GET", "%s/v2/" % push_rule.registry_url, status=401, headers={
                "Www-Authenticate": 'Basic realm="something.com"'})

        instance = RegistryHTTPClient.getInstance(push_rule)
        self.assertEqual(RegistryHTTPClient, type(instance))

        self.assertEqual(1, len(responses.calls))
        self.assertEqual(1, self.proxy_call_count)
        call = responses.calls[0]
        self.assertEqual("%s/v2/" % push_rule.registry_url, call.request.url)


class TestBearerTokenRegistryClient(OCIConfigHelperMixin,
                                    SpyProxyCallsMixin, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBearerTokenRegistryClient, self).setUp()
        self.setConfig()
        self.setupProxySpy()

    def makeOCIPushRule(self):
        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://registry.hub.docker.com",
            credentials={'username': 'the-user', 'password': "the-passwd"})
        return self.factory.makeOCIPushRule(
            registry_credentials=credentials,
            image_name="the-user/test-image")

    def test_api_url(self):
        push_rule = self.makeOCIPushRule()
        client = BearerTokenRegistryClient(push_rule)
        self.assertEqual(
            "https://registry.hub.docker.com/v2/the-user/test-image",
            client.api_url)

    def test_parse_instructions(self):
        auth_header_content = (
            'Bearer realm="https://auth.docker.io/token",'
            'service="registry.docker.io",'
            'scope="repository:the-user/test-image:pull,push"')

        request = mock.Mock()
        request.headers = {'Www-Authenticate': auth_header_content}

        push_rule = self.makeOCIPushRule()
        client = BearerTokenRegistryClient(push_rule)

        self.assertEqual(
            client.parseAuthInstructions(request), ("Bearer", {
            "realm": "https://auth.docker.io/token",
            "service": "registry.docker.io",
            "scope": "repository:the-user/test-image:pull,push"
        }))

    @responses.activate
    def test_unauthorized_request_retries_fetching_token(self):
        token_url = "https://auth.docker.io/token"
        auth_header_content = (
            'Bearer realm="%s",'
            'service="registry.docker.io",'
            'scope="repository:the-user/test-image:pull,push"') % token_url

        url = "http://fake.launchpad.test/foo"
        responses.add("GET", url, status=401, headers={
            'Www-Authenticate': auth_header_content})
        responses.add("GET", token_url, status=200, json={"token": "123abc"})
        responses.add("GET", url, status=201, json={"success": True})

        push_rule = removeSecurityProxy(self.makeOCIPushRule())
        client = BearerTokenRegistryClient(push_rule)
        response = client.request(url)
        self.assertEqual(201, response.status_code)
        self.assertEqual(response.json(), {"success": True})

        # Check that the 3 requests were made in order.
        self.assertEqual(3, len(responses.calls))
        self.assertEqual(3, self.proxy_call_count)
        failed_call, auth_call, success_call = responses.calls

        self.assertEqual(url, failed_call.request.url)
        self.assertEqual(401, failed_call.response.status_code)

        self.assertStartsWith(auth_call.request.url, token_url)
        self.assertEqual(200, auth_call.response.status_code)

        self.assertEqual(url, success_call.request.url)
        self.assertEqual(201, success_call.response.status_code)

    @responses.activate
    def test_unauthorized_request_retries_only_once(self):
        token_url = "https://auth.docker.io/token"
        auth_header_content = (
            'Bearer realm="%s",'
            'service="registry.docker.io",'
            'scope="repository:the-user/test-image:pull,push"') % token_url

        url = "http://fake.launchpad.test/foo"
        responses.add("GET", url, status=401, headers={
            'Www-Authenticate': auth_header_content})
        responses.add("GET", token_url, status=200, json={"token": "123abc"})

        push_rule = removeSecurityProxy(self.makeOCIPushRule())
        client = BearerTokenRegistryClient(push_rule)
        self.assertRaises(HTTPError, client.request, url)

        # Check that the 3 requests were made in order.
        self.assertEqual(3, len(responses.calls))
        self.assertEqual(3, self.proxy_call_count)
        failed_call, auth_call, second_failed_call = responses.calls

        self.assertEqual(url, failed_call.request.url)
        self.assertEqual(401, failed_call.response.status_code)

        self.assertStartsWith(auth_call.request.url, token_url)
        self.assertEqual(200, auth_call.response.status_code)

        self.assertEqual(url, second_failed_call.request.url)
        self.assertEqual(401, second_failed_call.response.status_code)

    @responses.activate
    def test_unauthorized_request_fails_to_get_token(self):
        token_url = "https://auth.docker.io/token"
        auth_header_content = (
            'Bearer realm="%s",'
            'service="registry.docker.io",'
            'scope="repository:the-user/test-image:pull,push"') % token_url

        url = "http://fake.launchpad.test/foo"
        responses.add("GET", url, status=401, headers={
            'Www-Authenticate': auth_header_content})
        responses.add("GET", token_url, status=400)

        push_rule = removeSecurityProxy(self.makeOCIPushRule())
        client = BearerTokenRegistryClient(push_rule)
        self.assertRaises(HTTPError, client.request, url)

        self.assertEqual(2, len(responses.calls))
        self.assertEqual(2, self.proxy_call_count)
        failed_call, auth_call = responses.calls

        self.assertEqual(url, failed_call.request.url)
        self.assertEqual(401, failed_call.response.status_code)

        self.assertStartsWith(auth_call.request.url, token_url)
        self.assertEqual(400, auth_call.response.status_code)

    @responses.activate
    def test_authenticate_malformed_www_authenticate_header(self):
        auth_header_content = (
            'Bearer service="registry.docker.io",'
            'scope="repository:the-user/test-image:pull,push"')

        previous_request = mock.Mock()
        previous_request.headers = {'Www-Authenticate': auth_header_content}

        push_rule = removeSecurityProxy(self.makeOCIPushRule())
        client = BearerTokenRegistryClient(push_rule)
        self.assertRaises(OCIRegistryAuthenticationError,
                          client.authenticate, previous_request)

    @responses.activate
    def test_authenticate_malformed_token_response(self):
        token_url = "https://auth.docker.io/token"
        auth_header_content = (
          'Bearer realm="%s",'
          'service="registry.docker.io",'
          'scope="repository:the-user/test-image:pull,push"') % token_url

        url = "http://fake.launchpad.test/foo"
        responses.add("GET", url, status=401, headers={
            'Www-Authenticate': auth_header_content})

        # no "token" key on the response.
        responses.add("GET", token_url, status=200, json={
            "shrug": "123"})

        previous_request = mock.Mock()
        previous_request.headers = {'Www-Authenticate': auth_header_content}

        push_rule = removeSecurityProxy(self.makeOCIPushRule())
        client = BearerTokenRegistryClient(push_rule)

        self.assertRaises(OCIRegistryAuthenticationError,
                          client.authenticate, previous_request)
