# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Client for talking to an OCI registry."""

__all__ = ["OCIRegistryClient"]

import base64
import hashlib
import json
import logging
import re
import tarfile
from functools import partial
from http.client import IncompleteRead
from io import BytesIO
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from requests.exceptions import ConnectionError, HTTPError
from requests.utils import parse_dict_header
from tenacity import (
    before_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)
from zope.interface import implementer

from lp.buildmaster.enums import BuildStatus
from lp.oci.interfaces.ociregistryclient import (
    BlobUploadFailed,
    IOCIRegistryClient,
    ManifestUploadFailed,
    MultipleOCIRegistryError,
)
from lp.services.config import config
from lp.services.features import getFeatureFlag
from lp.services.librarian.utils import EncodableLibraryFileAlias
from lp.services.propertycache import cachedproperty
from lp.services.timeout import urlfetch

log = logging.getLogger(__name__)

# Helper function to call urlfetch(use_proxy=True, *args, **kwargs)
proxy_urlfetch = partial(urlfetch, use_proxy=True)


OCI_AWS_BEARER_TOKEN_DOMAINS_FLAG = "oci.push.aws.bearer_token_domains"


def is_aws_bearer_token_domain(domain):
    """Returns True if the given registry domain should use bearer token
    instead of basic auth."""
    domains = getFeatureFlag(OCI_AWS_BEARER_TOKEN_DOMAINS_FLAG)
    if not domains:
        # We know that public ECR default domain is bearer token. If the
        # flag is not set, force it.
        domains = "public.ecr.aws"
    return any(domain.endswith(i) for i in domains.split())


@implementer(IOCIRegistryClient)
class OCIRegistryClient:
    @classmethod
    def _getJSONfile(cls, reference):
        """Read JSON out of a `LibraryFileAlias`."""
        try:
            reference.open()
            return json.loads(reference.read().decode("UTF-8"))
        finally:
            reference.close()

    @classmethod
    def _makeRegistryError(cls, error_class, summary, response):
        errors = None
        if response.content:
            try:
                response_data = response.json()
            except ValueError:
                pass
            else:
                errors = response_data.get("errors")
        return error_class(summary, errors)

    # Retry this on a ConnectionError, 5 times with 3 seconds wait.
    # Log each attempt so we can see they are happening.
    @classmethod
    @retry(
        wait=wait_fixed(3),
        before=before_log(log, logging.INFO),
        reraise=True,
        retry=(
            retry_if_exception_type(ConnectionError)
            | retry_if_exception_type(IncompleteRead)
        ),
        stop=stop_after_attempt(5),
    )
    def _upload(cls, digest, push_rule, fileobj, length, http_client):
        """Upload a blob to the registry, using a given digest.

        :param digest: The digest to store the file under.
        :param push_rule: `OCIPushRule` to use for the URL and credentials.
        :param fileobj: An object that looks like a buffer.
        :param length: The length of the blob in bytes.

        :raises BlobUploadFailed: if the registry does not accept the blob.
        """
        # Check if it already exists
        try:
            head_response = http_client.requestPath(
                f"/blobs/{digest}", method="HEAD"
            )
            if head_response.status_code == 200:
                log.info(f"{digest} already found")
                return
        except HTTPError as http_error:
            # A 404 is fine, we're about to upload the layer anyway
            if http_error.response.status_code != 404:
                raise http_error

        post_response = http_client.requestPath(
            "/blobs/uploads/", method="POST"
        )

        post_location = post_response.headers["Location"]
        query_parsed = {"digest": digest}

        try:
            put_response = http_client.request(
                post_location,
                params=query_parsed,
                data=fileobj,
                headers={"Content-Length": str(length)},
                method="PUT",
            )
        except HTTPError as http_error:
            put_response = http_error.response
        if put_response.status_code != 201:
            raise cls._makeRegistryError(
                BlobUploadFailed,
                "Upload of {} for {} failed".format(
                    digest, push_rule.image_name
                ),
                put_response,
            )

    @classmethod
    def _upload_layer(
        cls, digest, push_rule, lfa, http_client, upload_layers_uncompressed
    ):
        """Upload a layer blob to the registry.

        Uses _upload, but opens the LFA and extracts the necessary files
        from the .tar.gz first.

        :param digest: The digest to store the file under.
        :param push_rule: `OCIPushRule` to use for the URL and credentials.
        :param lfa: The `LibraryFileAlias` for the layer.
        """
        lfa.open()
        try:
            if upload_layers_uncompressed:
                with tarfile.open(fileobj=lfa, mode="r|gz") as un_zipped:
                    for tarinfo in un_zipped:
                        if tarinfo.name != "layer.tar":
                            continue
                        fileobj = un_zipped.extractfile(tarinfo)
                        # XXX Work around requests handling of objects that
                        # have fileno, but error on access in python3:
                        # https://github.com/psf/requests/pull/5239
                        fileobj.len = tarinfo.size
                        try:
                            cls._upload(
                                digest,
                                push_rule,
                                fileobj,
                                tarinfo.size,
                                http_client,
                            )
                        finally:
                            fileobj.close()
                        return tarinfo.size
            else:
                size = lfa.content.filesize
                wrapper = EncodableLibraryFileAlias(lfa)
                cls._upload(digest, push_rule, wrapper, size, http_client)
                return size
        finally:
            lfa.close()

    @classmethod
    def _build_registry_manifest(
        cls,
        digests,
        config,
        config_json,
        config_sha,
        preloaded_data,
        layer_sizes,
        upload_layers_uncompressed,
    ):
        """Create an image manifest for the uploading image.

        This involves nearly everything as digests and lengths are required.
        This method creates a minimal manifest, some fields are missing.

        :param digests: Dict of the various digests involved.
        :param config: The contents of the manifest config file as a dict.
        :param config_json: The config file as a JSON string.
        :param config_sha: The sha256sum of the config JSON string.
        :param layer_sizes: Dict of layer digests and their size in bytes.
        """
        # Create the initial manifest data with empty layer information
        manifest = {
            "schemaVersion": 2,
            "mediaType": (
                "application/vnd.docker.distribution.manifest.v2+json"
            ),
            "config": {
                "mediaType": "application/vnd.docker.container.image.v1+json",
                "size": len(config_json),
                "digest": f"sha256:{config_sha}",
            },
            "layers": [],
        }

        # Fill in the layer information
        # For uploading the compressed tar.gz for each layer we need
        # to obtain the digest for the tar.gz from the Config.json
        # and build the manifest with the zipped digest.
        for unzipped_sha in config["rootfs"]["diff_ids"]:
            if upload_layers_uncompressed:
                digest = unzipped_sha
            else:
                digest = "sha256:{}".format(digests[unzipped_sha]["digest"])
            log.info(
                "Adding digest: %s for layer %s to manifest file."
                % (digest, digests[unzipped_sha]["layer_id"])
            )
            manifest["layers"].append(
                {
                    "mediaType": (
                        "application/vnd.docker.image.rootfs.diff.tar.gzip"
                    ),
                    "size": layer_sizes[digest],
                    "digest": digest,
                }
            )
        log.info("LP constructed the following manifest: %s", manifest)
        return manifest

    @classmethod
    def _preloadFiles(cls, build, manifest, digests):
        """Preload the data from the librarian to avoid multiple fetches
        if there is more than one push rule for a build.

        :param build: The referencing `OCIRecipeBuild`.
        :param manifest: The manifest from the built image.
        :param digests: Dict of the various digests involved.
        """
        data = {}
        for section in manifest:
            # Load the matching config file for this section
            config = cls._getJSONfile(build.getFileByName(section["Config"]))
            files = {"config_file": config}
            for diff_id in config["rootfs"]["diff_ids"]:
                # We may have already seen this diff ID.
                if files.get(diff_id):
                    continue
                # Retrieve the layer files.
                # This doesn't read the content, so there is potential
                # for multiple fetches, but the files can be arbitrary size
                # Potentially gigabytes.
                files[diff_id] = {}
                source_digest = digests[diff_id]["digest"]
                _, lfa, _ = build.getLayerFileByDigest(source_digest)
                files[diff_id] = lfa
            data[section["Config"]] = files
        return data

    @classmethod
    def _calculateTags(cls, recipe):
        """Work out the base tag for the image should be.

        :param push_rule: `OCIPushRule` that we are using.
        """
        tags = []
        if recipe.is_valid_branch_format:
            ref_name = recipe.git_ref.path
            # lp:1921865, account for tags in the correct format
            if ref_name.startswith("refs/tags/"):
                ref_name = ref_name[len("refs/tags/") :]
            elif ref_name.startswith("refs/heads/"):
                ref_name = ref_name[len("refs/heads/") :]
            tags.append("{}_{}".format(ref_name, "edge"))
        else:
            tags.append("edge")
        return tags

    @classmethod
    def _getCurrentRegistryManifest(cls, http_client, tag):
        """Get the current manifest for the given push rule. If manifest
        doesn't exist, raises HTTPError.
        """
        url = f"/manifests/{tag}"
        accept = "application/vnd.docker.distribution.manifest.list.v2+json"
        response = http_client.requestPath(
            url, method="GET", headers={"Accept": accept}
        )
        return response.json()

    @classmethod
    def _uploadRegistryManifest(
        cls, http_client, registry_manifest, push_rule, tag, build=None
    ):
        """Uploads the build manifest, returning its content information.

        The returned information can be used to create a Manifest list
        including the uploaded manifest, for example, in order to create
        multi-architecture images.

        :return: A dict with {"digest": "sha256:xxx", "size": total_bytes}
        """
        # This is
        # https://docs.docker.com/registry/spec/manifest-v2-2/#manifest-list
        # Specifically the Schema 2 manifest.
        digest = None
        data = json.dumps(registry_manifest).encode("UTF-8")
        if tag is None:
            tag = f"sha256:{hashlib.sha256(data).hexdigest()}"
        size = len(data)
        content_type = registry_manifest.get(
            "mediaType", "application/vnd.docker.distribution.manifest.v2+json"
        )
        try:
            manifest_response = http_client.requestPath(
                f"/manifests/{tag}",
                data=data,
                headers={"Content-Type": content_type},
                method="PUT",
            )
            digest = manifest_response.headers.get("Docker-Content-Digest")
        except HTTPError as http_error:
            manifest_response = http_error.response
        if manifest_response.status_code != 201:
            if build:
                msg = "Failed to upload manifest for {} ({}) in {}".format(
                    build.recipe.name, push_rule.registry_url, build.id
                )
            else:
                msg = (
                    "Failed to upload manifest of manifests for" " {} ({})"
                ).format(push_rule.recipe.name, push_rule.registry_url)
            raise cls._makeRegistryError(
                ManifestUploadFailed, msg, manifest_response
            )
        return {"digest": digest, "size": size}

    @classmethod
    def should_upload_layers_uncompressed(cls, lfa):
        # We maintain 2 types of upload in LP:

        # The first (old approach) consists of us extracting the `layer.tar`
        # from the tar.gz uploaded by the buildd to the librarian
        # and uploading `layer.tar` directly, not the contents of it.
        # The structure we maintained for this is:
        # directory.tar.gz/layer.tar/layer_contents

        # The second (new approach) consists of uploading the contents
        # compressed as a tar.gz as we find them in Librarian. The new
        # structure we maintain here is: layer.tar.gz/layer_contents.
        # This final gz format has the name of the directory
        # (directory.tar.gz/contents).

        # Buildd has been modified to upload to Librarian using the second
        # approach (compressed tar.gz layers) but from LP to Registries
        # we need to distinguish here between the 2 approaches and upload
        # accordingly as we might have old builds in Librarian that have
        # not been requested to be uploaded to registries yet.
        try:
            lfa.open()
            with tarfile.open(fileobj=lfa, mode="r|gz") as un_zipped:
                for tarinfo in un_zipped:
                    if tarinfo.name == "layer.tar":
                        return True
            return False
        finally:
            lfa.close()

    @classmethod
    def _upload_to_push_rule(
        cls, push_rule, build, manifest, digests, preloaded_data, tag=None
    ):
        http_client = RegistryHTTPClient.getInstance(push_rule)

        for section in manifest:
            # Work out names
            file_data = preloaded_data[section["Config"]]
            config = file_data["config_file"]
            #  Upload the layers involved
            layer_sizes = {}

            # determine layer upload type: compressed or uncompressed
            first_id = config["rootfs"]["diff_ids"][0]
            lfa = file_data[first_id]
            upload_layers_uncompressed = cls.should_upload_layers_uncompressed(
                lfa
            )

            for diff_id in config["rootfs"]["diff_ids"]:
                if upload_layers_uncompressed:
                    digest = diff_id
                else:
                    digest = "sha256:{}".format(
                        file_data[diff_id].content.sha256
                    )
                layer_size = cls._upload_layer(
                    digest,
                    push_rule,
                    file_data[diff_id],
                    http_client,
                    upload_layers_uncompressed,
                )
                layer_sizes[digest] = layer_size
            # The config file is required in different forms, so we can
            # calculate the sha, work these out and upload
            config_json = json.dumps(config).encode("UTF-8")
            config_sha = hashlib.sha256(config_json).hexdigest()
            cls._upload(
                f"sha256:{config_sha}",
                push_rule,
                BytesIO(config_json),
                len(config_json),
                http_client,
            )

            # Build the registry manifest from the image manifest
            # and associated configs
            registry_manifest = cls._build_registry_manifest(
                digests,
                config,
                config_json,
                config_sha,
                preloaded_data[section["Config"]],
                layer_sizes,
                upload_layers_uncompressed,
            )

            # Upload the registry manifest
            manifest = cls._uploadRegistryManifest(
                http_client, registry_manifest, push_rule, tag, build
            )

            # Save the uploaded manifest location, so we can use it in case
            # this is a multi-arch image upload.
            if build.build_request:
                build.build_request.addUploadedManifest(build.id, manifest)

    @classmethod
    def upload(cls, build):
        """Upload the artifacts from an OCIRecipeBuild to a registry.

        :param build: `OCIRecipeBuild` representing this build.
        :raises ManifestUploadFailed: If the final registry manifest fails to
                                      upload due to network or validity.
        """
        cls.updateSupersededBuilds(build)
        if build.status == BuildStatus.SUPERSEDED:
            return
        # Get the required metadata files
        manifest = cls._getJSONfile(build.manifest)
        digests_list = cls._getJSONfile(build.digests)
        digests = {}
        for digest_dict in digests_list:
            digests.update(digest_dict)

        # Preload the requested files
        preloaded_data = cls._preloadFiles(build, manifest, digests)

        exceptions = []
        try:
            for push_rule in build.recipe.push_rules:
                try:
                    cls._upload_to_push_rule(
                        push_rule,
                        build,
                        manifest,
                        digests,
                        preloaded_data,
                        tag=None,
                    )
                except Exception as e:
                    exceptions.append(e)
            if len(exceptions) == 1:
                raise exceptions[0]
            elif len(exceptions) > 1:
                raise MultipleOCIRegistryError(exceptions)
        finally:
            # Avoid traceback reference cycles.
            del exceptions

    _arch_to_platform = {
        "amd64": {"os": "linux", "architecture": "amd64"},
        "arm64": {"os": "linux", "architecture": "arm64", "variant": "v8"},
        "armhf": {"os": "linux", "architecture": "arm", "variant": "v7"},
        "i386": {"os": "linux", "architecture": "386"},
        "ppc64el": {"os": "linux", "architecture": "ppc64le"},
        "riscv64": {"os": "linux", "architecture": "riscv64"},
        "s390x": {"os": "linux", "architecture": "s390x"},
    }

    @classmethod
    def _makePlatformSpecifiers(cls, arch):
        """Make OCI platform specifiers for an architecture tag.

        OCI platform specifiers are based on Go architecture names, which
        aren't identical to dpkg architecture tags in all cases.  Do the
        necessary mapping.

        The first specifier in the list returned by this method is the
        preferred one; subsequent specifiers may have been set by old code
        and should still be searched for when finding existing manifests.
        """
        platforms = []
        oci_platform = cls._arch_to_platform.get(arch)
        if oci_platform is not None:
            platforms.append(oci_platform)
        else:
            log.warning("No OCI platform specifier known for %s", arch)
        legacy_platform = {"os": "linux", "architecture": arch}
        if legacy_platform != oci_platform:
            platforms.append(legacy_platform)
        return platforms

    @classmethod
    def makeMultiArchManifest(
        cls, http_client, push_rule, build_request, uploaded_builds, tag
    ):
        """Returns the multi-arch manifest content including all uploaded
        builds of the given build_request.
        """
        try:
            current_manifest = cls._getCurrentRegistryManifest(
                http_client, tag
            )
            # Check if the current manifest is not an incompatible version.
            version = current_manifest.get("schemaVersion", 1)
            if version < 2 or "manifests" not in current_manifest:
                current_manifest = None
        except HTTPError as e:
            if e.response.status_code == 404:
                # If there is no manifest file (or it doesn't follow the
                # multi-arch spec), we should proceed adding our own
                # manifest file.
                current_manifest = None
                msg_tpl = (
                    "No multi-arch manifest on registry %s (image name: %s). "
                    "Uploading a new one."
                )
                log.info(
                    msg_tpl % (push_rule.registry_url, push_rule.image_name)
                )
            else:
                raise
        if current_manifest is None:
            current_manifest = {
                "schemaVersion": 2,
                "mediaType": (
                    "application/"
                    "vnd.docker.distribution.manifest.list.v2+json"
                ),
                "manifests": [],
            }
        manifests = current_manifest["manifests"]
        for build in uploaded_builds:
            build_manifest = build_request.uploaded_manifests.get(build.id)
            if not build_manifest:
                log.info(f"No build manifest found for build {build.id}")
                continue
            log.info(f"Build manifest found for build {build.id}")
            digest = build_manifest["digest"]
            size = build_manifest["size"]
            arch = build.distro_arch_series.architecturetag
            platforms = cls._makePlatformSpecifiers(arch)

            manifest = next(
                (m for m in manifests if m["platform"] in platforms), None
            )
            if manifest is None:
                log.info(
                    "Appending multi-arch manifest for build {} "
                    "with arch {}".format(build.id, arch)
                )
                manifest = {
                    "mediaType": (
                        "application/"
                        "vnd.docker.distribution.manifest.v2+json"
                    ),
                    "size": size,
                    "digest": digest,
                    "platform": platforms[0],
                }
                manifests.append(manifest)
            else:
                log.info(
                    "Updating multi-arch manifest for build {} "
                    "with arch {}".format(build.id, arch)
                )
                manifest["digest"] = digest
                manifest["size"] = size
                manifest["platform"] = platforms[0]

        return current_manifest

    @classmethod
    def updateSupersededBuilds(cls, build):
        """Checks if the given build was superseded by another build,
        updating its status in case it should have been superseded.

        :return: True if the build was superseded.
        """
        if build.status == BuildStatus.SUPERSEDED:
            return
        if build.hasMoreRecentBuild():
            force_transition = build.status == BuildStatus.FULLYBUILT
            build.updateStatus(
                BuildStatus.SUPERSEDED,
                force_invalid_transition=force_transition,
            )

    @classmethod
    def uploadManifestList(cls, build_request, uploaded_builds):
        """Uploads to all build_request.recipe.push_rules the manifest list
        for the builds in the given build_request.
        """
        # First, double check that the builds that will be updated in the
        # manifest files were not superseded by newer builds.
        for build in uploaded_builds:
            cls.updateSupersededBuilds(build)
        uploaded_builds = [
            build
            for build in uploaded_builds
            if build.status != BuildStatus.SUPERSEDED
        ]
        if not uploaded_builds:
            return
        for push_rule in build_request.recipe.push_rules:
            for tag in cls._calculateTags(build_request.recipe):
                try:
                    http_client = RegistryHTTPClient.getInstance(push_rule)
                    multi_manifest_content = cls.makeMultiArchManifest(
                        http_client,
                        push_rule,
                        build_request,
                        uploaded_builds,
                        tag,
                    )
                    cls._uploadRegistryManifest(
                        http_client,
                        multi_manifest_content,
                        push_rule,
                        tag,
                        build=None,
                    )
                except Exception:
                    log.exception(
                        "Exception in uploading manifest for OCI build "
                        "request {} with tag {}".format(build_request.id, tag)
                    )
                    raise


class OCIRegistryAuthenticationError(Exception):
    def __init__(self, msg, http_error=None):
        super().__init__(msg)
        self.http_error = http_error


class RegistryHTTPClient:
    def __init__(self, push_rule):
        self.push_rule = push_rule

    @property
    def credentials(self):
        """Returns a tuple of (username, password)."""
        auth = self.push_rule.registry_credentials.getCredentials()
        if auth.get("username"):
            return auth["username"], auth.get("password")
        return None, None

    @property
    def api_url(self):
        """Returns the base API URL for this registry."""
        push_rule = self.push_rule
        return f"{push_rule.registry_url}/v2/{push_rule.image_name}"

    def request(self, url, *args, **request_kwargs):
        username, password = self.credentials
        if username is not None:
            request_kwargs.setdefault("auth", (username, password))
        return proxy_urlfetch(url, **request_kwargs)

    def requestPath(self, path, *args, **request_kwargs):
        """Shortcut to do a request to {self.api_url}/{path}."""
        url = f"{self.api_url}{path}"
        return self.request(url, *args, **request_kwargs)

    @classmethod
    def getInstance(cls, push_rule):
        """Returns an instance of RegistryHTTPClient adapted to the
        given push rule and registry's authentication flow."""
        domain = urlparse(push_rule.registry_url).netloc
        if is_aws_bearer_token_domain(domain):
            return AWSRegistryBearerTokenClient(push_rule)
        if domain.endswith(".amazonaws.com"):
            return AWSRegistryHTTPClient(push_rule)
        try:
            proxy_urlfetch(f"{push_rule.registry_url}/v2/")
            # No authorization error? Just return the basic RegistryHTTPClient.
            return RegistryHTTPClient(push_rule)
        except HTTPError as e:
            # If we got back an "UNAUTHORIZED" error with "Www-Authenticate"
            # header, we should check what type of authorization we should use.
            header_key = "Www-Authenticate"
            if (
                e.response.status_code == 401
                and header_key in e.response.headers
            ):
                auth_type = e.response.headers[header_key].split(" ", 1)[0]
                if auth_type == "Bearer":
                    # Note that, although we have the realm where to
                    # authenticate, we do not retrieve the authentication
                    # token here. Different operations might need different
                    # permission scope (defined at "Bearer ...scope=yyy").
                    # So, we defer the token fetching to a moment where we
                    # are actually doing the operations and we will get info
                    # about what scope we will need.
                    return BearerTokenRegistryClient(push_rule)
                elif auth_type == "Basic":
                    return RegistryHTTPClient(push_rule)
            raise OCIRegistryAuthenticationError(
                "Unknown authentication type for %s registry"
                % push_rule.registry_url,
                e,
            )


class BearerTokenRegistryClient(RegistryHTTPClient):
    """Special case of RegistryHTTPClient for registries with auth
    based on bearer token, like DockerHub.

    This client type is prepared to deal with DockerHub's authorization
    cycle, which involves fetching the appropriate authorization token
    instead of using HTTP's basic auth.
    """

    def __init__(self, push_rule):
        super().__init__(push_rule)
        self.auth_token = None

    def parseAuthInstructions(self, request):
        """Parse the Www-Authenticate response header.

        This method parses the appropriate header from the request and returns
        the token type and the key-value pairs that should be used as query
        parameters of the token GET request."""
        instructions = request.headers["Www-Authenticate"]
        token_type, values = instructions.split(" ", 1)
        dict_values = parse_dict_header(values)
        return token_type, dict_values

    def authenticate(self, last_failed_request):
        """Tries to authenticate, considering the last HTTP 401 failed
        request."""
        token_type, values = self.parseAuthInstructions(last_failed_request)
        try:
            url = values.pop("realm")
        except KeyError:
            raise OCIRegistryAuthenticationError(
                "Auth instructions didn't include realm to get the token: %s"
                % values
            )
        # We should use the basic auth version for this request.
        response = super().request(
            url, params=values, method="GET", auth=self.credentials
        )
        response.raise_for_status()
        response_data = response.json()
        try:
            self.auth_token = response_data["token"]
        except KeyError:
            raise OCIRegistryAuthenticationError(
                "Could not get token from response data: %s" % response_data
            )

    def request(self, url, auth_retry=True, *args, **request_kwargs):
        """Does a request, handling authentication cycle in case of 401
        response.

        :param auth_retry: Should we authenticate and retry the request if
                           it fails with HTTP 401 code?"""
        headers = request_kwargs.pop("headers", {})
        try:
            if self.auth_token is not None:
                headers["Authorization"] = "Bearer %s" % self.auth_token
            return proxy_urlfetch(url, headers=headers, **request_kwargs)
        except HTTPError as e:
            if auth_retry and e.response.status_code == 401:
                self.authenticate(e.response)
                return self.request(
                    url,
                    auth_retry=False,
                    headers=headers,
                    *args,
                    **request_kwargs,
                )
            raise


class AWSAuthenticatorMixin:
    """Basic class to override the way we get credentials, exchanging
    registered aws_access_key_id and aws_secret_access_key with the
    temporary token got from AWS API.
    """

    def _getClientParameters(self):
        if config.launchpad.http_proxy:
            boto_config = Config(
                proxies={
                    "http": config.launchpad.http_proxy,
                    "https": config.launchpad.http_proxy,
                }
            )
        else:
            boto_config = Config()
        auth = self.push_rule.registry_credentials.getCredentials()
        username, password = auth["username"], auth.get("password")
        region = self._getRegion()
        log.info("Trying to authenticate with AWS in region %s" % region)
        return dict(
            aws_access_key_id=username,
            aws_secret_access_key=password,
            region_name=region,
            config=boto_config,
        )

    def _getBotoClient(self):
        params = self._getClientParameters()
        client_type = "ecr-public" if self.is_public_ecr else "ecr"
        return boto3.client(client_type, **params)

    @property
    def is_public_ecr(self):
        """Returns True if the given registry domain is a public ECR. False
        otherwise.
        """
        domain = urlparse(self.push_rule.registry_url).netloc
        return is_aws_bearer_token_domain(domain)

    def _getRegion(self):
        """Returns the region from the push URL domain."""
        push_rule = self.push_rule
        region = push_rule.registry_credentials.region
        if region is not None:
            return region
        # Try to guess from the domain. The format should be something like
        # 'xxx.dkr.ecr.sa-east-1.amazonaws.com'. 'sa-east-1' is the region.
        domain = urlparse(self.push_rule.registry_url).netloc
        if re.match(r".+\.dkr\.ecr\..+\.amazonaws\.com", domain):
            return domain.split(".")[-3]
        raise OCIRegistryAuthenticationError("Unknown AWS region.")

    @cachedproperty
    def credentials(self):
        """Exchange aws_access_key_id and aws_secret_access_key with the
        authentication token that should be used when talking to ECR."""
        try:
            client = self._getBotoClient()
            token = client.get_authorization_token()
            auth_data = token["authorizationData"]
            # Some AWS services returns a list with one element inside,
            # while others return only a dict directly. We should support
            # both situations.
            if isinstance(auth_data, list):
                auth_data = auth_data[0]
            authorization_token = auth_data["authorizationToken"]
            username, password = (
                base64.b64decode(authorization_token).decode().split(":")
            )
            return username, password
        except Exception as e:
            log.error(
                "Error trying to get authorization token for ECR "
                "registry: %s(%s)" % (e.__class__, e)
            )
            raise OCIRegistryAuthenticationError(
                "It was not possible to get AWS credentials for %s: %s"
                % (self.push_rule.registry_url, e)
            )


class AWSRegistryHTTPClient(AWSAuthenticatorMixin, RegistryHTTPClient):
    """AWS registry client with authentication flow based on basic auth."""

    pass


class AWSRegistryBearerTokenClient(
    AWSAuthenticatorMixin, BearerTokenRegistryClient
):
    """AWS registry client with authentication flow based on bearer tokens."""

    pass
