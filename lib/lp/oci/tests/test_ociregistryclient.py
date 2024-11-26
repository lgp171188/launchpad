# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the OCI Registry client."""

import base64
import io
import json
import os
import re
import tarfile
import uuid
from datetime import timedelta
from functools import partial
from http.client import IncompleteRead
from unittest import mock

import responses
from tenacity import wait_fixed
import transaction
from fixtures import MockPatch
from requests.exceptions import ConnectionError, HTTPError
from testtools.matchers import (
    AfterPreprocessing,
    ContainsDict,
    Equals,
    Is,
    MatchesAll,
    MatchesDict,
    MatchesException,
    MatchesListwise,
    MatchesStructure,
    Raises,
)
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.oci.interfaces.ocirecipe import OCI_RECIPE_ALLOW_CREATE
from lp.oci.interfaces.ocirecipebuild import OCIRecipeBuildRegistryUploadStatus
from lp.oci.interfaces.ocirecipejob import IOCIRecipeRequestBuildsJobSource
from lp.oci.interfaces.ociregistryclient import (
    BlobUploadFailed,
    ManifestUploadFailed,
    MultipleOCIRegistryError,
)
from lp.oci.model.ocirecipe import OCIRecipeBuildRequest
from lp.oci.model.ociregistryclient import (
    OCI_AWS_BEARER_TOKEN_DOMAINS_FLAG,
    AWSAuthenticatorMixin,
    AWSRegistryBearerTokenClient,
    AWSRegistryHTTPClient,
    BearerTokenRegistryClient,
    OCIRegistryAuthenticationError,
    OCIRegistryClient,
    RegistryHTTPClient,
    proxy_urlfetch,
)
from lp.oci.tests.helpers import OCIConfigHelperMixin
from lp.registry.interfaces.series import SeriesStatus
from lp.services.features.testing import FeatureFixture
from lp.services.tarfile_helpers import LaunchpadWriteTarFile
from lp.testing import TestCaseWithFactory, admin_logged_in, person_logged_in
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadZopelessLayer


class SpyProxyCallsMixin:
    def setupProxySpy(self):
        self.proxy_call_count = 0

        def count_proxy_call_count(*args, **kwargs):
            self.proxy_call_count += 1
            return proxy_urlfetch(*args, **kwargs)

        proxy_mock = self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.proxy_urlfetch",
                side_effect=count_proxy_call_count,
            )
        ).mock
        # Avoid reference cycles with file objects passed to urlfetch.
        self.addCleanup(proxy_mock.reset_mock)


class TestOCIRegistryClient(
    OCIConfigHelperMixin, SpyProxyCallsMixin, TestCaseWithFactory
):
    layer = LaunchpadZopelessLayer
    retry_count = 0

    def setUp(self):
        super().setUp()
        self.setConfig()
        self.setupProxySpy()
        self.manifest = [
            {
                "Config": "config_file_1.json",
                "Layers": ["layer_1/layer.tar", "layer_2/layer.tar"],
            }
        ]
        self.digests = [
            {
                "diff_id_1": {
                    "digest": "digest_1",
                    "source": "test/base_1",
                    "layer_id": "layer_1",
                },
                "diff_id_2": {
                    "digest": "digest_2",
                    "source": "",
                    "layer_id": "layer_2",
                },
            }
        ]
        self.config = {"rootfs": {"diff_ids": ["diff_id_1", "diff_id_2"]}}
        # This produces a git ref that does not match the 'valid' OCI branch
        # format, so will not get multiple tags. Multiple tags are tested
        # explicitly.
        [self.git_ref] = self.factory.makeGitRefs(
            paths=["refs/heads/v1.0-20.04"]
        )
        recipe = self.factory.makeOCIRecipe(git_ref=self.git_ref)
        self.build = self.factory.makeOCIRecipeBuild(recipe=recipe)
        self.push_rule = self.factory.makeOCIPushRule(recipe=self.build.recipe)
        self.client = OCIRegistryClient()

    def _makeFiles(self):
        self.factory.makeOCIFile(
            build=self.build,
            content=json.dumps(self.manifest).encode("UTF-8"),
            filename="manifest.json",
        )
        self.factory.makeOCIFile(
            build=self.build,
            content=json.dumps(self.digests).encode("UTF-8"),
            filename="digests.json",
        )
        self.factory.makeOCIFile(
            build=self.build,
            content=json.dumps(self.config).encode("UTF-8"),
            filename="config_file_1.json",
        )

        tmpdir = self.makeTemporaryDirectory()
        self.layer_files = []
        for i in range(1, 3):
            digest = "digest_%i" % i
            file_name = "digest_%s_filename" % i
            file_path = os.path.join(tmpdir, file_name)

            with open(file_path, "w") as fd:
                fd.write(digest)

            fileout = io.BytesIO()
            tar = tarfile.open(mode="w:gz", fileobj=fileout)
            tar.add(file_path, "layer.tar")
            tar.close()

            fileout.seek(0)
            # make layer files
            self.layer_files.append(
                self.factory.makeOCIFile(
                    build=self.build,
                    content=fileout.read(),
                    filename=file_name,
                    layer_file_digest=digest,
                )
            )

        transaction.commit()

    def addManifestResponses(self, push_rule, status_code=201, json=None):
        """Add responses for manifest upload URLs."""
        # PUT to "anonymous" architecture-specific manifest.
        manifests_url = "{}/v2/{}/manifests/sha256:.*".format(
            push_rule.registry_credentials.url, push_rule.image_name
        )
        responses.add(
            "PUT", re.compile(manifests_url), status=status_code, json=json
        )

        # PUT to tagged multi-arch manifest.
        manifests_url = "{}/v2/{}/manifests/edge".format(
            push_rule.registry_credentials.url, push_rule.image_name
        )
        responses.add("PUT", manifests_url, status=status_code, json=json)

        # recipes that the git branch name matches the correct format
        manifests_url = "{}/v2/{}/manifests/{}_edge".format(
            push_rule.registry_credentials.url,
            push_rule.image_name,
            push_rule.recipe.git_ref.name,
        )
        responses.add("PUT", manifests_url, status=status_code, json=json)

    @responses.activate
    def test_upload(self):
        self._makeFiles()
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient._upload"
            )
        )
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient."
                "_upload_layer",
                return_value=999,
            )
        )

        push_rule = self.build.recipe.push_rules[0]
        responses.add("GET", "%s/v2/" % push_rule.registry_url, status=200)

        self.addManifestResponses(push_rule)

        self.client.upload(self.build)

        # We should have uploaded to the digest, not the tag
        self.assertIn("sha256:", responses.calls[1].request.url)
        self.assertNotIn("edge", responses.calls[1].request.url)
        request = json.loads(responses.calls[1].request.body)

        layer_matchers = [
            MatchesDict(
                {
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"
                    ),
                    "digest": Equals("diff_id_1"),
                    "size": Equals(999),
                }
            ),
            MatchesDict(
                {
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"
                    ),
                    "digest": Equals("diff_id_2"),
                    "size": Equals(999),
                }
            ),
        ]
        config_matcher = MatchesDict(
            {
                "mediaType": Equals(
                    "application/vnd.docker.container.image.v1+json"
                ),
                "digest": Equals(
                    "sha256:33b69b4b6e106f9fc7a8b93409"
                    "36c85cf7f84b2d017e7b55bee6ab214761f6ab"
                ),
                "size": Equals(52),
            }
        )
        self.assertThat(
            request,
            MatchesDict(
                {
                    "layers": MatchesListwise(layer_matchers),
                    "schemaVersion": Equals(2),
                    "config": config_matcher,
                    "mediaType": Equals(
                        "application/vnd.docker.distribution.manifest.v2+json"
                    ),
                }
            ),
        )

    @responses.activate
    def test_upload_ignores_superseded_builds(self):
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        recipe = self.build.recipe
        processor = self.build.processor
        distribution = recipe.oci_project.distribution
        distroseries = self.factory.makeDistroSeries(
            distribution=distribution, status=SeriesStatus.CURRENT
        )
        distro_arch_series = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag=processor.name,
            processor=processor,
        )

        # Creates another build, more recent.
        self.factory.makeOCIRecipeBuild(
            recipe=recipe,
            distro_arch_series=distro_arch_series,
            status=BuildStatus.FULLYBUILT,
            date_created=self.build.date_created + timedelta(seconds=1),
        )

        self.client.upload(self.build)
        self.assertEqual(BuildStatus.SUPERSEDED, self.build.status)
        self.assertEqual(
            OCIRecipeBuildRegistryUploadStatus.SUPERSEDED,
            self.build.registry_upload_status,
        )
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_upload_with_distribution_credentials(self):
        self._makeFiles()
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient._upload"
            )
        )
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient."
                "_upload_layer",
                return_value=999,
            )
        )
        credentials = self.factory.makeOCIRegistryCredentials()
        image_name = self.factory.getUniqueUnicode()
        self.build.recipe.image_name = image_name
        distro = self.build.recipe.oci_project.distribution
        with person_logged_in(distro.owner):
            distro.oci_registry_credentials = credentials
        # we have distribution credentials, we should have a 'push rule'
        push_rule = self.build.recipe.push_rules[0]
        responses.add("GET", "%s/v2/" % push_rule.registry_url, status=200)
        self.addManifestResponses(push_rule)

        self.client.upload(self.build)

        request = json.loads(responses.calls[1].request.body)

        layer_matchers = [
            MatchesDict(
                {
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"
                    ),
                    "digest": Equals("diff_id_1"),
                    "size": Equals(999),
                }
            ),
            MatchesDict(
                {
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"
                    ),
                    "digest": Equals("diff_id_2"),
                    "size": Equals(999),
                }
            ),
        ]
        config_matcher = MatchesDict(
            {
                "mediaType": Equals(
                    "application/vnd.docker.container.image.v1+json"
                ),
                "digest": Equals(
                    "sha256:33b69b4b6e106f9fc7a8b93409"
                    "36c85cf7f84b2d017e7b55bee6ab214761f6ab"
                ),
                "size": Equals(52),
            }
        )
        self.assertThat(
            request,
            MatchesDict(
                {
                    "layers": MatchesListwise(layer_matchers),
                    "schemaVersion": Equals(2),
                    "config": config_matcher,
                    "mediaType": Equals(
                        "application/vnd.docker.distribution.manifest.v2+json"
                    ),
                }
            ),
        )

    @responses.activate
    def test_upload_formats_credentials(self):
        self._makeFiles()
        _upload_fixture = self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient._upload"
            )
        )
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient."
                "_upload_layer",
                return_value=999,
            )
        )

        self.push_rule.registry_credentials.setCredentials(
            {"username": "test-username", "password": "test-password"}
        )

        push_rule = self.build.recipe.push_rules[0]
        responses.add("GET", "%s/v2/" % push_rule.registry_url, status=200)

        self.addManifestResponses(push_rule)

        self.client.upload(self.build)

        http_client = _upload_fixture.mock.call_args_list[0][0][-1]
        self.assertEqual(
            http_client.credentials, ("test-username", "test-password")
        )

    @responses.activate
    def test_upload_skip_failed_push_rule(self):
        self._makeFiles()
        upload_fixture = self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient._upload"
            )
        )
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient."
                "_upload_layer",
                return_value=999,
            )
        )

        push_rules = [
            self.push_rule,
            self.factory.makeOCIPushRule(recipe=self.build.recipe),
            self.factory.makeOCIPushRule(recipe=self.build.recipe),
        ]
        # Set the first 2 rules to fail with 400 at the PUT operation.
        for i, push_rule in enumerate(push_rules):
            push_rule.registry_credentials.setCredentials(
                {
                    "username": "test-username-%s" % i,
                    "password": "test-password-%s" % i,
                }
            )
            responses.add("GET", "%s/v2/" % push_rule.registry_url, status=200)

            status = 400 if i < 2 else 201
            self.addManifestResponses(push_rule, status_code=status)

        error = self.assertRaises(
            MultipleOCIRegistryError, self.client.upload, self.build
        )

        # Check that it tried to call the upload for each one of the push rules
        self.assertEqual(3, upload_fixture.mock.call_count)
        used_credentials = {
            args[0][-1].credentials
            for args in upload_fixture.mock.call_args_list
        }
        self.assertSetEqual(
            {
                ("test-username-0", "test-password-0"),
                ("test-username-1", "test-password-1"),
                ("test-username-2", "test-password-2"),
            },
            used_credentials,
        )

        # Check that we received back an exception of the correct type.
        self.assertIsInstance(error, MultipleOCIRegistryError)
        self.assertEqual(2, len(error.errors))
        self.assertEqual(2, len(error.exceptions))

        expected_error_msg = (
            "Failed to upload manifest for {recipe} ({url1}) in {build} / "
            "Failed to upload manifest for {recipe} ({url2}) in {build}"
        ).format(
            recipe=self.build.recipe.name,
            build=self.build.id,
            url1=push_rules[0].registry_url,
            url2=push_rules[1].registry_url,
        )
        self.assertEqual(expected_error_msg, str(error))

    def test_preloadFiles(self):
        self._makeFiles()
        files = self.client._preloadFiles(
            self.build, self.manifest, self.digests[0]
        )

        self.assertThat(
            files,
            MatchesDict(
                {
                    "config_file_1.json": MatchesDict(
                        {
                            "config_file": Equals(self.config),
                            "diff_id_1": Equals(
                                self.layer_files[0].library_file
                            ),
                            "diff_id_2": Equals(
                                self.layer_files[1].library_file
                            ),
                        }
                    )
                }
            ),
        )

    def test_calculateTags_invalid_format(self):
        [git_ref] = self.factory.makeGitRefs(paths=["refs/heads/invalid"])
        self.build.recipe.git_ref = git_ref
        result = self.client._calculateTags(self.build.recipe)
        self.assertThat(result, MatchesListwise([Equals("edge")]))

    def test_calculateTags_valid_format(self):
        [git_ref] = self.factory.makeGitRefs(paths=["refs/heads/v1.0-20.04"])
        self.build.recipe.git_ref = git_ref
        result = self.client._calculateTags(self.build.recipe)
        self.assertThat(result, MatchesListwise([Equals("v1.0-20.04_edge")]))

    def test_calculateTags_valid_tag(self):
        [git_ref] = self.factory.makeGitRefs(paths=["refs/tags/v1.0-20.04"])
        self.build.recipe.git_ref = git_ref
        result = self.client._calculateTags(self.build.recipe)
        self.assertThat(result, MatchesListwise([Equals("v1.0-20.04_edge")]))

    def test_build_registry_manifest(self):
        self._makeFiles()
        preloaded_data = self.client._preloadFiles(
            self.build, self.manifest, self.digests[0]
        )
        manifest = self.client._build_registry_manifest(
            self.digests[0],
            self.config,
            json.dumps(self.config),
            "config-sha",
            preloaded_data["config_file_1.json"],
            {"diff_id_1": 999, "diff_id_2": 9001},
            True,
        )
        layer_matchers = [
            MatchesDict(
                {
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"
                    ),
                    "digest": Equals("diff_id_1"),
                    "size": Equals(999),
                }
            ),
            MatchesDict(
                {
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"
                    ),
                    "digest": Equals("diff_id_2"),
                    "size": Equals(9001),
                }
            ),
        ]
        config_matcher = MatchesDict(
            {
                "mediaType": Equals(
                    "application/vnd.docker.container.image.v1+json"
                ),
                "digest": Equals("sha256:config-sha"),
                "size": Equals(52),
            }
        )
        self.assertThat(
            manifest,
            MatchesDict(
                {
                    "layers": MatchesListwise(layer_matchers),
                    "schemaVersion": Equals(2),
                    "config": config_matcher,
                    "mediaType": Equals(
                        "application/vnd.docker.distribution.manifest.v2+json"
                    ),
                }
            ),
        )

    def test_build_registry_manifest_compressed_layers(self):
        self._makeFiles()
        preloaded_data = self.client._preloadFiles(
            self.build, self.manifest, self.digests[0]
        )
        manifest = self.client._build_registry_manifest(
            self.digests[0],
            self.config,
            json.dumps(self.config),
            "config-sha",
            preloaded_data["config_file_1.json"],
            {"sha256:digest_1": 999, "sha256:digest_2": 9001},
            False,
        )
        layer_matchers = [
            MatchesDict(
                {
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"
                    ),
                    "digest": Equals("sha256:digest_1"),
                    "size": Equals(999),
                }
            ),
            MatchesDict(
                {
                    "mediaType": Equals(
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"
                    ),
                    "digest": Equals("sha256:digest_2"),
                    "size": Equals(9001),
                }
            ),
        ]
        config_matcher = MatchesDict(
            {
                "mediaType": Equals(
                    "application/vnd.docker.container.image.v1+json"
                ),
                "digest": Equals("sha256:config-sha"),
                "size": Equals(52),
            }
        )
        self.assertThat(
            manifest,
            MatchesDict(
                {
                    "layers": MatchesListwise(layer_matchers),
                    "schemaVersion": Equals(2),
                    "config": config_matcher,
                    "mediaType": Equals(
                        "application/vnd.docker.distribution.manifest.v2+json"
                    ),
                }
            ),
        )

    @responses.activate
    def test_upload_handles_existing(self):
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = f"{http_client.api_url}/blobs/test-digest"
        responses.add("HEAD", blobs_url, status=200)
        push_rule = self.build.recipe.push_rules[0]
        push_rule.registry_credentials.setCredentials({})
        self.client._upload("test-digest", push_rule, None, 0, http_client)

        self.assertEqual(len(responses.calls), self.proxy_call_count)
        # There should be no auth headers for these calls
        for call in responses.calls:
            self.assertNotIn("Authorization", call.request.headers.keys())

    @responses.activate
    def test_upload_check_existing_raises_non_404(self):
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = f"{http_client.api_url}/blobs/test-digest"
        responses.add("HEAD", blobs_url, status=500)
        push_rule = self.build.recipe.push_rules[0]
        self.assertEqual(len(responses.calls), self.proxy_call_count)
        self.assertRaises(
            HTTPError,
            self.client._upload,
            "test-digest",
            push_rule,
            None,
            0,
            http_client,
        )

    @responses.activate
    def test_upload_passes_basic_auth(self):
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = f"{http_client.api_url}/blobs/test-digest"
        responses.add("HEAD", blobs_url, status=200)
        push_rule.registry_credentials.setCredentials(
            {"username": "user", "password": "password"}
        )
        self.client._upload("test-digest", push_rule, None, 0, http_client)

        self.assertEqual(len(responses.calls), self.proxy_call_count)
        for call in responses.calls:
            self.assertEqual(
                "Basic dXNlcjpwYXNzd29yZA==",
                call.request.headers["Authorization"],
            )

    def _check_retry_type(self, counting_method, retry_type):
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.proxy_urlfetch",
                side_effect=counting_method,
            )
        )
        # Set wait_fixed in tenacity to 0 so we don't wait in order to speed up the test
        with mock.patch.object(target=self.client._upload.retry, attribute="wait", new=wait_fixed(0)):
            try:
                push_rule = self.build.recipe.push_rules[0]
                self.client._upload(
                    "test-digest",
                    push_rule,
                    None,
                    0,
                    RegistryHTTPClient(push_rule),
                )
            except retry_type:
                # Check that tenacity and our counting agree
                self.assertEqual(
                    5, self.client._upload.statistics["attempt_number"]
                )
                self.assertEqual(5, self.retry_count)
            except Exception:
                # We should see the original exception, not a RetryError
                raise

    def test_upload_retries_exception(self):
        # Use a separate counting mechanism so we're not entirely relying
        # on tenacity to tell us that it has retried.
        def count_retries(*args, **kwargs):
            self.retry_count += 1
            raise ConnectionError

        self._check_retry_type(count_retries, ConnectionError)

    def test_upload_retries_incomplete_read(self):
        # Use a separate counting mechanism so we're not entirely relying
        # on tenacity to tell us that it has retried.
        def count_retries(*args, **kwargs):
            self.retry_count += 1
            raise IncompleteRead(b"", 20)

        self._check_retry_type(count_retries, IncompleteRead)

    @responses.activate
    def test_upload_put_blob_raises_error(self):
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = f"{http_client.api_url}/blobs/test-digest"
        uploads_url = f"{http_client.api_url}/blobs/uploads/"
        upload_url = f"{http_client.api_url}/blobs/uploads/{uuid.uuid4()}"
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
            "PUT", upload_url, status=400, json={"errors": put_errors}
        )
        self.assertThat(
            partial(
                self.client._upload,
                "test-digest",
                push_rule,
                None,
                0,
                http_client,
            ),
            Raises(
                MatchesException(
                    BlobUploadFailed,
                    MatchesAll(
                        AfterPreprocessing(
                            str,
                            Equals(
                                "Upload of {} for {} failed".format(
                                    "test-digest", push_rule.image_name
                                )
                            ),
                        ),
                        MatchesStructure.byEquality(errors=put_errors),
                    ),
                )
            ),
        )

    @responses.activate
    def test_upload_put_blob_raises_non_201_success(self):
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = f"{http_client.api_url}/blobs/test-digest"
        uploads_url = f"{http_client.api_url}/blobs/uploads/"
        upload_url = f"{http_client.api_url}/blobs/uploads/{uuid.uuid4()}"
        responses.add("HEAD", blobs_url, status=404)
        responses.add("POST", uploads_url, headers={"Location": upload_url})
        responses.add("PUT", upload_url, status=200)
        self.assertThat(
            partial(
                self.client._upload,
                "test-digest",
                push_rule,
                None,
                0,
                http_client,
            ),
            Raises(
                MatchesException(
                    BlobUploadFailed,
                    MatchesAll(
                        AfterPreprocessing(
                            str,
                            Equals(
                                "Upload of {} for {} failed".format(
                                    "test-digest", push_rule.image_name
                                )
                            ),
                        ),
                        MatchesStructure(errors=Is(None)),
                    ),
                )
            ),
        )

    @responses.activate
    def test_upload_put_manifest_raises_error(self):
        self._makeFiles()
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient._upload"
            )
        )
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient."
                "_upload_layer",
                return_value=999,
            )
        )

        push_rule = self.build.recipe.push_rules[0]
        responses.add("GET", f"{push_rule.registry_url}/v2/", status=200)

        put_errors = [
            {
                "code": "MANIFEST_INVALID",
                "message": "manifest invalid",
                "detail": [],
            },
        ]
        self.addManifestResponses(
            push_rule, status_code=400, json={"errors": put_errors}
        )

        expected_msg = "Failed to upload manifest for {} ({}) in {}".format(
            self.build.recipe.name, self.push_rule.registry_url, self.build.id
        )
        self.assertThat(
            partial(self.client.upload, self.build),
            Raises(
                MatchesException(
                    ManifestUploadFailed,
                    MatchesAll(
                        AfterPreprocessing(str, Equals(expected_msg)),
                        MatchesStructure.byEquality(errors=put_errors),
                    ),
                )
            ),
        )

    @responses.activate
    def test_upload_put_manifest_raises_non_201_success(self):
        self._makeFiles()
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient._upload"
            )
        )
        self.useFixture(
            MockPatch(
                "lp.oci.model.ociregistryclient.OCIRegistryClient."
                "_upload_layer",
                return_value=999,
            )
        )

        push_rule = self.build.recipe.push_rules[0]
        responses.add("GET", f"{push_rule.registry_url}/v2/", status=200)

        self.addManifestResponses(push_rule, status_code=200)

        expected_msg = "Failed to upload manifest for {} ({}) in {}".format(
            self.build.recipe.name, self.push_rule.registry_url, self.build.id
        )
        self.assertThat(
            partial(self.client.upload, self.build),
            Raises(
                MatchesException(
                    ManifestUploadFailed,
                    MatchesAll(
                        AfterPreprocessing(str, Equals(expected_msg)),
                        MatchesStructure(errors=Is(None)),
                    ),
                )
            ),
        )

    @responses.activate
    def test_upload_layer_put_blob_sends_content_length(self):
        lfa = self.factory.makeLibraryFileAlias(
            content=LaunchpadWriteTarFile.files_to_bytes(
                {"layer.tar": b"test layer"}
            )
        )
        transaction.commit()
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = f"{http_client.api_url}/blobs/test-digest"
        uploads_url = f"{http_client.api_url}/blobs/uploads/"
        upload_url = f"{http_client.api_url}/blobs/uploads/{uuid.uuid4()}"
        responses.add("HEAD", blobs_url, status=404)
        responses.add("POST", uploads_url, headers={"Location": upload_url})
        responses.add("PUT", upload_url, status=201)
        self.assertTrue(self.client.should_upload_layers_uncompressed(lfa))
        self.client._upload_layer(
            "test-digest", push_rule, lfa, http_client, True
        )
        self.assertThat(
            responses.calls[2].request,
            MatchesStructure(
                method=Equals("PUT"),
                headers=ContainsDict(
                    {
                        "Content-Length": Equals(str(len(b"test layer"))),
                    }
                ),
            ),
        )

    def test_platform_specifiers(self):
        expected_platforms = {
            "amd64": [{"os": "linux", "architecture": "amd64"}],
            "arm64": [
                {"os": "linux", "architecture": "arm64", "variant": "v8"},
                {"os": "linux", "architecture": "arm64"},
            ],
            "armhf": [
                {"os": "linux", "architecture": "arm", "variant": "v7"},
                {"os": "linux", "architecture": "armhf"},
            ],
            "i386": [
                {"os": "linux", "architecture": "386"},
                {"os": "linux", "architecture": "i386"},
            ],
            "ppc64el": [
                {"os": "linux", "architecture": "ppc64le"},
                {"os": "linux", "architecture": "ppc64el"},
            ],
            "riscv64": [{"os": "linux", "architecture": "riscv64"}],
            "s390x": [{"os": "linux", "architecture": "s390x"}],
            "unknown": [{"os": "linux", "architecture": "unknown"}],
        }
        for arch, platforms in expected_platforms.items():
            self.assertEqual(
                platforms, self.client._makePlatformSpecifiers(arch)
            )

    @responses.activate
    def test_multi_arch_manifest_upload_skips_superseded_builds(self):
        recipe = self.build.recipe
        processor = self.build.processor
        distribution = recipe.oci_project.distribution
        distroseries = self.factory.makeDistroSeries(
            distribution=distribution, status=SeriesStatus.CURRENT
        )
        distro_arch_series = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag=processor.name,
            processor=processor,
        )

        # Creates another build for the same arch and recipe, more recent.
        self.factory.makeOCIRecipeBuild(
            recipe=recipe,
            distro_arch_series=distro_arch_series,
            status=BuildStatus.FULLYBUILT,
            date_created=self.build.date_created + timedelta(seconds=1),
        )

        build_request = OCIRecipeBuildRequest(recipe, -1)
        self.client.uploadManifestList(build_request, [self.build])

        self.assertEqual(BuildStatus.SUPERSEDED, self.build.status)
        self.assertEqual(
            OCIRecipeBuildRegistryUploadStatus.SUPERSEDED,
            self.build.registry_upload_status,
        )
        self.assertEqual(0, len(responses.calls))

    @responses.activate
    def test_multi_arch_manifest_upload_new_manifest(self):
        """Ensure that multi-arch manifest upload works and tags correctly
        the uploaded image."""
        # Creates a build request with 2 builds.
        recipe = self.factory.makeOCIRecipe(git_ref=self.git_ref)
        distroseries = self.factory.makeDistroSeries(
            distribution=recipe.distribution, status=SeriesStatus.CURRENT
        )
        for architecturetag, processor_name in (
            ("i386", "386"),
            ("amd64", "amd64"),
            ("hppa", "hppa"),
        ):
            self.factory.makeDistroArchSeries(
                distroseries=distroseries,
                architecturetag=architecturetag,
                processor=getUtility(IProcessorSet).getByName(processor_name),
            )
        build1 = self.factory.makeOCIRecipeBuild(
            recipe=recipe, distro_arch_series=distroseries["i386"]
        )
        build2 = self.factory.makeOCIRecipeBuild(
            recipe=recipe, distro_arch_series=distroseries["amd64"]
        )
        build3 = self.factory.makeOCIRecipeBuild(
            recipe=recipe, distro_arch_series=distroseries["hppa"]
        )

        # Creates a mock IOCIRecipeRequestBuildsJobSource, as it was created
        # by the celery job and triggered the 3 registry uploads already.
        job = mock.Mock()
        job.builds = [build1, build2, build3]
        job.uploaded_manifests = {
            build1.id: {"digest": "build1digest", "size": 123},
            build2.id: {"digest": "build2digest", "size": 321},
            build3.id: {"digest": "build2digest", "size": 333},
        }
        job_source = mock.Mock()
        job_source.getByOCIRecipeAndID.return_value = job
        self.useFixture(
            ZopeUtilityFixture(job_source, IOCIRecipeRequestBuildsJobSource)
        )
        build_request = OCIRecipeBuildRequest(recipe, -1)

        push_rule = self.factory.makeOCIPushRule(recipe=recipe)
        responses.add(
            "GET",
            "{}/v2/{}/manifests/v1.0-20.04_edge".format(
                push_rule.registry_url, push_rule.image_name
            ),
            status=404,
        )
        self.addManifestResponses(push_rule, status_code=201)

        responses.add("GET", f"{push_rule.registry_url}/v2/", status=200)
        self.addManifestResponses(push_rule, status_code=201)

        # Let's try to generate the manifest for just 2 of the 3 builds:
        self.client.uploadManifestList(build_request, [build1, build2])
        self.assertEqual(3, len(responses.calls))
        auth_call, get_manifest_call, send_manifest_call = responses.calls
        self.assertEndsWith(
            send_manifest_call.request.url,
            "/v2/%s/manifests/v1.0-20.04_edge" % push_rule.image_name,
        )
        self.assertEqual(
            {
                "schemaVersion": 2,
                "mediaType": "application/"
                "vnd.docker.distribution.manifest.list.v2+json",
                "manifests": [
                    {
                        "platform": {"os": "linux", "architecture": "386"},
                        "mediaType": "application/"
                        "vnd.docker.distribution.manifest.v2+json",
                        "digest": "build1digest",
                        "size": 123,
                    },
                    {
                        "platform": {"os": "linux", "architecture": "amd64"},
                        "mediaType": "application/"
                        "vnd.docker.distribution.manifest.v2+json",
                        "digest": "build2digest",
                        "size": 321,
                    },
                ],
            },
            json.loads(send_manifest_call.request.body),
        )

    @responses.activate
    def test_multi_arch_manifest_upload_update_manifest(self):
        """Makes sure we update only new architectures if there is already
        a manifest file in registry.
        """
        current_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/"
            "vnd.docker.distribution.manifest.list.v2+json",
            "manifests": [
                {
                    "platform": {"os": "linux", "architecture": "386"},
                    "mediaType": "application/"
                    "vnd.docker.distribution.manifest.v2+json",
                    "digest": "initial-386-digest",
                    "size": 110,
                },
                {
                    "platform": {"os": "linux", "architecture": "amd64"},
                    "mediaType": "application/"
                    "vnd.docker.distribution.manifest.v2+json",
                    "digest": "initial-amd64-digest",
                    "size": 220,
                },
            ],
        }

        # Creates a build request with 2 builds: amd64 (which is already in
        # the manifest) and hppa (that should be added)
        recipe = self.factory.makeOCIRecipe(git_ref=self.git_ref)
        distroseries = self.factory.makeDistroSeries(
            distribution=recipe.distribution, status=SeriesStatus.CURRENT
        )
        for architecturetag, processor_name in (
            ("amd64", "amd64"),
            ("hppa", "hppa"),
        ):
            self.factory.makeDistroArchSeries(
                distroseries=distroseries,
                architecturetag=architecturetag,
                processor=getUtility(IProcessorSet).getByName(processor_name),
            )
        build1 = self.factory.makeOCIRecipeBuild(
            recipe=recipe, distro_arch_series=distroseries["amd64"]
        )
        build2 = self.factory.makeOCIRecipeBuild(
            recipe=recipe, distro_arch_series=distroseries["hppa"]
        )

        # Creates a mock IOCIRecipeRequestBuildsJobSource, as it was created
        # by the celery job and triggered the 3 registry uploads already.
        job = mock.Mock()
        job.builds = [build1, build2]
        job.uploaded_manifests = {
            build1.id: {"digest": "new-build1-digest", "size": 1111},
            build2.id: {"digest": "new-build2-digest", "size": 2222},
        }
        job_source = mock.Mock()
        job_source.getByOCIRecipeAndID.return_value = job
        self.useFixture(
            ZopeUtilityFixture(job_source, IOCIRecipeRequestBuildsJobSource)
        )
        build_request = OCIRecipeBuildRequest(recipe, -1)

        push_rule = self.factory.makeOCIPushRule(recipe=recipe)
        responses.add(
            "GET",
            "{}/v2/{}/manifests/v1.0-20.04_edge".format(
                push_rule.registry_url, push_rule.image_name
            ),
            json=current_manifest,
            status=200,
        )
        self.addManifestResponses(push_rule, status_code=201)

        responses.add("GET", f"{push_rule.registry_url}/v2/", status=200)
        self.addManifestResponses(push_rule, status_code=201)

        self.client.uploadManifestList(build_request, [build1, build2])
        self.assertEqual(3, len(responses.calls))
        auth_call, get_manifest_call, send_manifest_call = responses.calls
        self.assertEndsWith(
            send_manifest_call.request.url,
            "/v2/%s/manifests/v1.0-20.04_edge" % push_rule.image_name,
        )
        self.assertEqual(
            {
                "schemaVersion": 2,
                "mediaType": "application/"
                "vnd.docker.distribution.manifest.list.v2+json",
                "manifests": [
                    {
                        "platform": {"os": "linux", "architecture": "386"},
                        "mediaType": "application/"
                        "vnd.docker.distribution.manifest.v2+json",
                        "digest": "initial-386-digest",
                        "size": 110,
                    },
                    {
                        "platform": {"os": "linux", "architecture": "amd64"},
                        "mediaType": "application/"
                        "vnd.docker.distribution.manifest.v2+json",
                        "digest": "new-build1-digest",
                        "size": 1111,
                    },
                    {
                        "platform": {"os": "linux", "architecture": "hppa"},
                        "mediaType": "application/"
                        "vnd.docker.distribution.manifest.v2+json",
                        "digest": "new-build2-digest",
                        "size": 2222,
                    },
                ],
            },
            json.loads(send_manifest_call.request.body),
        )

    @responses.activate
    def test_multi_arch_manifest_upload_invalid_current_manifest(self):
        """Makes sure we create a new multi-arch manifest if existing manifest
        file is using another unknown format.
        """
        current_manifest = {"schemaVersion": 1, "layers": []}

        # Creates a build request with 1 build for amd64.
        recipe = self.factory.makeOCIRecipe(git_ref=self.git_ref)
        distroseries = self.factory.makeDistroSeries(
            distribution=recipe.distribution, status=SeriesStatus.CURRENT
        )
        das = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag="amd64",
            processor=getUtility(IProcessorSet).getByName("amd64"),
        )
        build1 = self.factory.makeOCIRecipeBuild(
            recipe=recipe, distro_arch_series=das
        )

        job = mock.Mock()
        job.builds = [build1]
        job.uploaded_manifests = {
            build1.id: {"digest": "new-build1-digest", "size": 1111},
        }
        job_source = mock.Mock()
        job_source.getByOCIRecipeAndID.return_value = job
        self.useFixture(
            ZopeUtilityFixture(job_source, IOCIRecipeRequestBuildsJobSource)
        )
        build_request = OCIRecipeBuildRequest(recipe, -1)

        push_rule = self.factory.makeOCIPushRule(recipe=recipe)
        responses.add(
            "GET",
            "{}/v2/{}/manifests/v1.0-20.04_edge".format(
                push_rule.registry_url, push_rule.image_name
            ),
            json=current_manifest,
            status=200,
        )
        self.addManifestResponses(push_rule, status_code=201)

        responses.add("GET", f"{push_rule.registry_url}/v2/", status=200)
        self.addManifestResponses(push_rule, status_code=201)

        self.client.uploadManifestList(build_request, [build1])
        self.assertEqual(3, len(responses.calls))
        auth_call, get_manifest_call, send_manifest_call = responses.calls
        self.assertEndsWith(
            send_manifest_call.request.url,
            "/v2/%s/manifests/v1.0-20.04_edge" % push_rule.image_name,
        )
        self.assertEqual(
            {
                "schemaVersion": 2,
                "mediaType": "application/"
                "vnd.docker.distribution.manifest.list.v2+json",
                "manifests": [
                    {
                        "platform": {"os": "linux", "architecture": "amd64"},
                        "mediaType": "application/"
                        "vnd.docker.distribution.manifest.v2+json",
                        "digest": "new-build1-digest",
                        "size": 1111,
                    }
                ],
            },
            json.loads(send_manifest_call.request.body),
        )

    @responses.activate
    def test_multi_arch_manifest_upload_registry_error_fetching_current(self):
        """Makes sure we abort the image upload if we get an error that is
        not 404 when fetching the current manifest file.
        """
        job = mock.Mock()
        job.builds = [self.build]
        job.uploaded_manifests = {
            self.build.id: {"digest": "new-build1-digest", "size": 1111},
        }
        job_source = mock.Mock()
        job_source.getByOCIRecipeAndID.return_value = job
        self.useFixture(
            ZopeUtilityFixture(job_source, IOCIRecipeRequestBuildsJobSource)
        )
        build_request = OCIRecipeBuildRequest(self.build.recipe, -1)

        push_rule = self.build.recipe.push_rules[0]
        responses.add(
            "GET",
            "{}/v2/{}/manifests/v1.0-20.04_edge".format(
                push_rule.registry_url, push_rule.image_name
            ),
            json={"error": "Unknown"},
            status=503,
        )

        responses.add("GET", f"{push_rule.registry_url}/v2/", status=200)
        self.addManifestResponses(push_rule, status_code=201)

        self.assertRaises(
            HTTPError,
            self.client.uploadManifestList,
            build_request,
            [self.build],
        )

    @responses.activate
    def test_upload_layer_gzipped_blob(self):
        lfa = self.factory.makeLibraryFileAlias(
            content=LaunchpadWriteTarFile.files_to_bytes(
                {"6d56becb66b184f.tar.gz": b"test gzipped layer"}
            )
        )
        transaction.commit()
        push_rule = self.build.recipe.push_rules[0]
        http_client = RegistryHTTPClient(push_rule)
        blobs_url = f"{http_client.api_url}/blobs/test-digest"
        uploads_url = f"{http_client.api_url}/blobs/uploads/"
        upload_url = f"{http_client.api_url}/blobs/uploads/{uuid.uuid4()}"
        responses.add("HEAD", blobs_url, status=404)
        responses.add("POST", uploads_url, headers={"Location": upload_url})
        responses.add("PUT", upload_url, status=201)

        self.assertFalse(self.client.should_upload_layers_uncompressed(lfa))

        self.client._upload_layer(
            "test-digest", push_rule, lfa, http_client, False
        )
        self.assertThat(
            responses.calls[2].request,
            MatchesStructure(
                method=Equals("PUT"),
                headers=ContainsDict(
                    {
                        "Content-Length": Equals(str(lfa.content.filesize)),
                    }
                ),
            ),
        )

    @responses.activate
    def test_multi_arch_manifest_with_existing_architectures(self):
        """Ensure that an existing arch release does not vanish
        while waiting for a new upload."""
        current_manifest = {
            "schemaVersion": 2,
            "mediaType": "application/"
            "vnd.docker.distribution.manifest.list.v2+json",
            "manifests": [
                {
                    "platform": {"os": "linux", "architecture": "386"},
                    "mediaType": "application/"
                    "vnd.docker.distribution.manifest.v2+json",
                    "digest": "initial-386-digest",
                    "size": 110,
                },
                {
                    "platform": {"os": "linux", "architecture": "amd64"},
                    "mediaType": "application/"
                    "vnd.docker.distribution.manifest.v2+json",
                    "digest": "initial-amd64-digest",
                    "size": 220,
                },
            ],
        }

        recipe = self.factory.makeOCIRecipe(git_ref=self.git_ref)
        distroseries = self.factory.makeDistroSeries(
            distribution=recipe.distribution, status=SeriesStatus.CURRENT
        )
        for architecturetag, processor_name in (
            ("amd64", "amd64"),
            ("i386", "386"),
        ):
            self.factory.makeDistroArchSeries(
                distroseries=distroseries,
                architecturetag=architecturetag,
                processor=getUtility(IProcessorSet).getByName(processor_name),
            )
        build1 = self.factory.makeOCIRecipeBuild(
            recipe=recipe, distro_arch_series=distroseries["amd64"]
        )
        build2 = self.factory.makeOCIRecipeBuild(
            recipe=recipe, distro_arch_series=distroseries["i386"]
        )

        job = mock.Mock()
        job.builds = [build1, build2]
        job.uploaded_manifests = {
            build1.id: {"digest": "new-build1-digest", "size": 1111},
            build2.id: {"digest": "new-build2-digest", "size": 2222},
        }
        job_source = mock.Mock()
        job_source.getByOCIRecipeAndID.return_value = job
        self.useFixture(
            ZopeUtilityFixture(job_source, IOCIRecipeRequestBuildsJobSource)
        )
        build_request = OCIRecipeBuildRequest(recipe, -1)

        push_rule = self.factory.makeOCIPushRule(recipe=recipe)
        responses.add(
            "GET",
            "{}/v2/{}/manifests/v1.0-20.04_edge".format(
                push_rule.registry_url, push_rule.image_name
            ),
            json=current_manifest,
            status=200,
        )
        self.addManifestResponses(push_rule, status_code=201)

        responses.add("GET", f"{push_rule.registry_url}/v2/", status=200)
        self.addManifestResponses(push_rule, status_code=201)

        self.client.uploadManifestList(build_request, [build1])
        self.assertEqual(3, len(responses.calls))

        # Check that we have the old manifest for 386,
        # but the new one for amd64
        self.assertEqual(
            {
                "schemaVersion": 2,
                "mediaType": "application/"
                "vnd.docker.distribution.manifest.list.v2+json",
                "manifests": [
                    {
                        "platform": {"os": "linux", "architecture": "386"},
                        "mediaType": "application"
                        "/vnd.docker.distribution.manifest.v2+json",
                        "digest": "initial-386-digest",
                        "size": 110,
                    },
                    {
                        "platform": {"os": "linux", "architecture": "amd64"},
                        "mediaType": "application"
                        "/vnd.docker.distribution.manifest.v2+json",
                        "digest": "new-build1-digest",
                        "size": 1111,
                    },
                ],
            },
            json.loads(responses.calls[2].request.body),
        )


class TestRegistryHTTPClient(
    OCIConfigHelperMixin, SpyProxyCallsMixin, TestCaseWithFactory
):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.setConfig()
        self.setupProxySpy()

    @responses.activate
    def test_get_default_client_instance(self):
        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://the-registry.test",
            credentials={"username": "the-user", "password": "the-passwd"},
        )
        push_rule = removeSecurityProxy(
            self.factory.makeOCIPushRule(
                registry_credentials=credentials,
                image_name="the-user/test-image",
            )
        )

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
            credentials={"username": "the-user", "password": "the-passwd"},
        )
        push_rule = removeSecurityProxy(
            self.factory.makeOCIPushRule(
                registry_credentials=credentials,
                image_name="the-user/test-image",
            )
        )

        responses.add(
            "GET",
            "%s/v2/" % push_rule.registry_url,
            status=401,
            headers={"Www-Authenticate": 'Bearer realm="something.com"'},
        )

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
            credentials={"username": "the-user", "password": "the-passwd"},
        )
        push_rule = removeSecurityProxy(
            self.factory.makeOCIPushRule(
                registry_credentials=credentials,
                image_name="the-user/test-image",
            )
        )

        responses.add(
            "GET",
            "%s/v2/" % push_rule.registry_url,
            status=401,
            headers={"Www-Authenticate": 'Basic realm="something.com"'},
        )

        instance = RegistryHTTPClient.getInstance(push_rule)
        self.assertEqual(RegistryHTTPClient, type(instance))

        self.assertEqual(1, len(responses.calls))
        self.assertEqual(1, self.proxy_call_count)
        call = responses.calls[0]
        self.assertEqual("%s/v2/" % push_rule.registry_url, call.request.url)

    @responses.activate
    def test_get_aws_basic_auth_client_instance(self):
        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://123456789.dkr.ecr.sa-east-1.amazonaws.com",
            credentials={
                "username": "aws_access_key_id",
                "password": "aws_secret_access_key",
            },
        )
        push_rule = removeSecurityProxy(
            self.factory.makeOCIPushRule(
                registry_credentials=credentials, image_name="ecr-test"
            )
        )

        instance = RegistryHTTPClient.getInstance(push_rule)
        self.assertEqual(AWSRegistryHTTPClient, type(instance))
        self.assertFalse(instance.is_public_ecr)
        self.assertIsInstance(instance, RegistryHTTPClient)

    @responses.activate
    def test_get_aws_bearer_token_auth_client_instance(self):
        self.useFixture(
            FeatureFixture(
                {
                    OCI_RECIPE_ALLOW_CREATE: "on",
                    OCI_AWS_BEARER_TOKEN_DOMAINS_FLAG: (
                        "foo.example.com fake.example.com"
                    ),
                }
            )
        )
        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://fake.example.com",
            credentials={
                "username": "aws_access_key_id",
                "password": "aws_secret_access_key",
            },
        )
        push_rule = removeSecurityProxy(
            self.factory.makeOCIPushRule(
                registry_credentials=credentials, image_name="ecr-test"
            )
        )

        instance = RegistryHTTPClient.getInstance(push_rule)
        self.assertEqual(AWSRegistryBearerTokenClient, type(instance))
        self.assertTrue(instance.is_public_ecr)
        self.assertIsInstance(instance, RegistryHTTPClient)

    @responses.activate
    def test_aws_credentials(self):
        self.pushConfig("launchpad", http_proxy="http://proxy.example.com:123")
        boto_patch = self.useFixture(
            MockPatch("lp.oci.model.ociregistryclient.boto3")
        )
        boto = boto_patch.mock
        get_authorization_token = (
            boto.client.return_value.get_authorization_token
        )
        get_authorization_token.return_value = {
            "authorizationData": [
                {
                    "authorizationToken": base64.b64encode(
                        b"the-username:the-token"
                    )
                }
            ]
        }

        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://123456789.dkr.ecr.sa-east-1.amazonaws.com",
            credentials={
                "username": "my_aws_access_key_id",
                "password": "my_aws_secret_access_key",
            },
        )
        push_rule = removeSecurityProxy(
            self.factory.makeOCIPushRule(
                registry_credentials=credentials, image_name="ecr-test"
            )
        )

        instance = RegistryHTTPClient.getInstance(push_rule)
        # Check the credentials twice, to make sure they are cached.
        for _ in range(2):
            http_user, http_passwd = instance.credentials
            self.assertEqual("the-username", http_user)
            self.assertEqual("the-token", http_passwd)
            self.assertEqual(1, boto.client.call_count)
            self.assertEqual(
                mock.call(
                    "ecr",
                    aws_access_key_id="my_aws_access_key_id",
                    aws_secret_access_key="my_aws_secret_access_key",
                    region_name="sa-east-1",
                    config=mock.ANY,
                ),
                boto.client.call_args,
            )
            config = boto.client.call_args[-1]["config"]
            self.assertEqual(
                {
                    "http": "http://proxy.example.com:123",
                    "https": "http://proxy.example.com:123",
                },
                config.proxies,
            )

    @responses.activate
    def test_aws_malformed_url_region(self):
        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://.amazonaws.com",
            credentials={"username": "aa", "password": "bb"},
        )
        push_rule = removeSecurityProxy(
            self.factory.makeOCIPushRule(
                registry_credentials=credentials, image_name="ecr-test"
            )
        )

        instance = RegistryHTTPClient.getInstance(push_rule)
        self.assertRaises(
            OCIRegistryAuthenticationError, getattr, instance, "credentials"
        )


class TestBearerTokenRegistryClient(
    OCIConfigHelperMixin, SpyProxyCallsMixin, TestCaseWithFactory
):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.setConfig()
        self.setupProxySpy()

    def makeOCIPushRule(self):
        credentials = self.factory.makeOCIRegistryCredentials(
            url="https://registry.hub.docker.com",
            credentials={"username": "the-user", "password": "the-passwd"},
        )
        return self.factory.makeOCIPushRule(
            registry_credentials=credentials, image_name="the-user/test-image"
        )

    def test_api_url(self):
        push_rule = self.makeOCIPushRule()
        client = BearerTokenRegistryClient(push_rule)
        self.assertEqual(
            "https://registry.hub.docker.com/v2/the-user/test-image",
            client.api_url,
        )

    def test_parse_instructions(self):
        auth_header_content = (
            'Bearer realm="https://auth.docker.io/token",'
            'service="registry.docker.io",'
            'scope="repository:the-user/test-image:pull,push"'
        )

        request = mock.Mock()
        request.headers = {"Www-Authenticate": auth_header_content}

        push_rule = self.makeOCIPushRule()
        client = BearerTokenRegistryClient(push_rule)

        self.assertEqual(
            client.parseAuthInstructions(request),
            (
                "Bearer",
                {
                    "realm": "https://auth.docker.io/token",
                    "service": "registry.docker.io",
                    "scope": "repository:the-user/test-image:pull,push",
                },
            ),
        )

    @responses.activate
    def test_unauthorized_request_retries_fetching_token(self):
        token_url = "https://auth.docker.io/token"
        auth_header_content = (
            'Bearer realm="%s",'
            'service="registry.docker.io",'
            'scope="repository:the-user/test-image:pull,push"'
        ) % token_url

        url = "http://fake.launchpad.test/foo"
        responses.add(
            "GET",
            url,
            status=401,
            headers={"Www-Authenticate": auth_header_content},
        )
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
            'scope="repository:the-user/test-image:pull,push"'
        ) % token_url

        url = "http://fake.launchpad.test/foo"
        responses.add(
            "GET",
            url,
            status=401,
            headers={"Www-Authenticate": auth_header_content},
        )
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
            'scope="repository:the-user/test-image:pull,push"'
        ) % token_url

        url = "http://fake.launchpad.test/foo"
        responses.add(
            "GET",
            url,
            status=401,
            headers={"Www-Authenticate": auth_header_content},
        )
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
            'scope="repository:the-user/test-image:pull,push"'
        )

        previous_request = mock.Mock()
        previous_request.headers = {"Www-Authenticate": auth_header_content}

        push_rule = removeSecurityProxy(self.makeOCIPushRule())
        client = BearerTokenRegistryClient(push_rule)
        self.assertRaises(
            OCIRegistryAuthenticationError,
            client.authenticate,
            previous_request,
        )

    @responses.activate
    def test_authenticate_malformed_token_response(self):
        token_url = "https://auth.docker.io/token"
        auth_header_content = (
            'Bearer realm="%s",'
            'service="registry.docker.io",'
            'scope="repository:the-user/test-image:pull,push"'
        ) % token_url

        url = "http://fake.launchpad.test/foo"
        responses.add(
            "GET",
            url,
            status=401,
            headers={"Www-Authenticate": auth_header_content},
        )

        # no "token" key on the response.
        responses.add("GET", token_url, status=200, json={"shrug": "123"})

        previous_request = mock.Mock()
        previous_request.headers = {"Www-Authenticate": auth_header_content}

        push_rule = removeSecurityProxy(self.makeOCIPushRule())
        client = BearerTokenRegistryClient(push_rule)

        self.assertRaises(
            OCIRegistryAuthenticationError,
            client.authenticate,
            previous_request,
        )


class TestAWSAuthenticator(OCIConfigHelperMixin, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.setConfig()

    def test_get_region_from_credential(self):
        cred = self.factory.makeOCIRegistryCredentials(
            url="https://example.com", credentials={"region": "sa-east-1"}
        )
        push_rule = self.factory.makeOCIPushRule(registry_credentials=cred)

        with admin_logged_in():
            auth = AWSAuthenticatorMixin()
            auth.push_rule = push_rule
            self.assertEqual("sa-east-1", auth._getRegion())

    def test_get_region_from_url(self):
        cred = self.factory.makeOCIRegistryCredentials(
            url="https://123456789.dkr.ecr.sa-west-1.amazonaws.com"
        )
        push_rule = self.factory.makeOCIPushRule(registry_credentials=cred)

        with admin_logged_in():
            auth = AWSAuthenticatorMixin()
            auth.push_rule = push_rule
            self.assertEqual("sa-west-1", auth._getRegion())

    def test_get_region_invalid_url(self):
        cred = self.factory.makeOCIRegistryCredentials(
            url="https://something.example.com"
        )
        push_rule = self.factory.makeOCIPushRule(registry_credentials=cred)

        with admin_logged_in():
            auth = AWSAuthenticatorMixin()
            auth.push_rule = push_rule
            self.assertRaises(OCIRegistryAuthenticationError, auth._getRegion)

    def test_should_use_public_ecr_boto_model(self):
        self.setConfig(
            {OCI_AWS_BEARER_TOKEN_DOMAINS_FLAG: "bearertoken.example.com"}
        )
        boto_client_mock = self.useFixture(
            MockPatch("lp.oci.model.ociregistryclient.boto3.client")
        ).mock
        cred = self.factory.makeOCIRegistryCredentials(
            url="https://myregistry.bearertoken.example.com",
            credentials=dict(
                region="us-east-1", username="user1", password="passwd1"
            ),
        )
        push_rule = self.factory.makeOCIPushRule(registry_credentials=cred)

        with admin_logged_in():
            auth = AWSAuthenticatorMixin()
            auth.push_rule = push_rule
            self.assertTrue(auth.is_public_ecr)

            client = auth._getBotoClient()
            self.assertEqual(boto_client_mock.return_value, client)
            self.assertEqual(1, boto_client_mock.call_count)
            call = boto_client_mock.call_args
            self.assertEqual(
                mock.call(
                    "ecr-public",
                    config=mock.ANY,
                    region_name="us-east-1",
                    aws_secret_access_key="passwd1",
                    aws_access_key_id="user1",
                ),
                call,
            )
            self.assertThat(
                call[1]["config"], MatchesStructure.byEquality(proxies=None)
            )

    def test_should_not_use_public_ecr_boto_model(self):
        self.setConfig(
            {OCI_AWS_BEARER_TOKEN_DOMAINS_FLAG: "bearertoken.example.com"}
        )
        boto_client_mock = self.useFixture(
            MockPatch("lp.oci.model.ociregistryclient.boto3.client")
        ).mock
        cred = self.factory.makeOCIRegistryCredentials(
            url="https://123456789.dkr.ecr.sa-west-1.amazonaws.com",
            credentials=dict(
                region="us-east-1", username="user1", password="passwd1"
            ),
        )
        push_rule = self.factory.makeOCIPushRule(registry_credentials=cred)

        with admin_logged_in():
            auth = AWSAuthenticatorMixin()
            auth.push_rule = push_rule
            self.assertFalse(auth.is_public_ecr)

            client = auth._getBotoClient()
            self.assertEqual(boto_client_mock.return_value, client)
            self.assertEqual(1, boto_client_mock.call_count)
            call = boto_client_mock.call_args
            self.assertEqual(
                mock.call(
                    "ecr",
                    config=mock.ANY,
                    region_name="us-east-1",
                    aws_secret_access_key="passwd1",
                    aws_access_key_id="user1",
                ),
                call,
            )
            self.assertThat(
                call[1]["config"], MatchesStructure.byEquality(proxies=None)
            )
