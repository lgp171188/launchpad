# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Client for talking to an OCI registry."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRegistryClient'
]


from functools import partial
import hashlib
from io import BytesIO
import json


try:
    from json.decoder import JSONDecodeError
except ImportError:
    JSONDecodeError = ValueError
import logging
import tarfile

from requests.exceptions import (
    ConnectionError,
    HTTPError,
    )
from six.moves.urllib.request import (
    parse_http_list,
    parse_keqv_list,
    )
from tenacity import (
    before_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
    )
from zope.interface import implementer

from lp.oci.interfaces.ociregistryclient import (
    BlobUploadFailed,
    IOCIRegistryClient,
    MultipleOCIRegistryError,
    ManifestUploadFailed,
    )
from lp.services.timeout import urlfetch


log = logging.getLogger(__name__)

# Helper function to call urlfetch(use_proxy=True, *args, **kwargs)
proxy_urlfetch = partial(urlfetch, use_proxy=True)


@implementer(IOCIRegistryClient)
class OCIRegistryClient:

    @classmethod
    def _getJSONfile(cls, reference):
        """Read JSON out of a `LibraryFileAlias`."""
        try:
            reference.open()
            return json.loads(reference.read())
        finally:
            reference.close()

    @classmethod
    def _makeRegistryError(cls, error_class, summary, response):
        errors = None
        if response.content:
            try:
                response_data = response.json()
            except JSONDecodeError:
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
        retry=retry_if_exception_type(ConnectionError),
        stop=stop_after_attempt(5))
    def _upload(cls, digest, push_rule, fileobj, http_client):
        """Upload a blob to the registry, using a given digest.

        :param digest: The digest to store the file under.
        :param push_rule: `OCIPushRule` to use for the URL and credentials.
        :param fileobj: An object that looks like a buffer.

        :raises BlobUploadFailed: if the registry does not accept the blob.
        """
        # Check if it already exists
        try:
            head_response = http_client.requestPath(
                "/blobs/{}".format(digest),
                method="HEAD")
            if head_response.status_code == 200:
                log.info("{} already found".format(digest))
                return
        except HTTPError as http_error:
            # A 404 is fine, we're about to upload the layer anyway
            if http_error.response.status_code != 404:
                raise http_error

        post_response = http_client.requestPath(
            "/blobs/uploads/", method="POST")

        post_location = post_response.headers["Location"]
        query_parsed = {"digest": digest}

        try:
            put_response = http_client.request(
                post_location,
                params=query_parsed,
                data=fileobj,
                method="PUT")
        except HTTPError as http_error:
            put_response = http_error.response
        if put_response.status_code != 201:
            raise cls._makeRegistryError(
                BlobUploadFailed,
                "Upload of {} for {} failed".format(
                    digest, push_rule.image_name),
                put_response)

    @classmethod
    def _upload_layer(cls, digest, push_rule, lfa, http_client):
        """Upload a layer blob to the registry.

        Uses _upload, but opens the LFA and extracts the necessary files
        from the .tar.gz first.

        :param digest: The digest to store the file under.
        :param push_rule: `OCIPushRule` to use for the URL and credentials.
        :param lfa: The `LibraryFileAlias` for the layer.
        """
        lfa.open()
        try:
            un_zipped = tarfile.open(fileobj=lfa, mode='r|gz')
            for tarinfo in un_zipped:
                if tarinfo.name != 'layer.tar':
                    continue
                fileobj = un_zipped.extractfile(tarinfo)
                cls._upload(digest, push_rule, fileobj, http_client)
        finally:
            lfa.close()

    @classmethod
    def _build_registry_manifest(cls, digests, config, config_json,
                                 config_sha, preloaded_data):
        """Create an image manifest for the uploading image.

        This involves nearly everything as digests and lengths are required.
        This method creates a minimal manifest, some fields are missing.

        :param digests: Dict of the various digests involved.
        :param config: The contents of the manifest config file as a dict.
        :param config_json: The config file as a JSON string.
        :param config_sha: The sha256sum of the config JSON string.
        """
        # Create the initial manifest data with empty layer information
        manifest = {
            "schemaVersion": 2,
            "mediaType":
                "application/vnd.docker.distribution.manifest.v2+json",
            "config": {
                "mediaType": "application/vnd.docker.container.image.v1+json",
                "size": len(config_json),
                "digest": "sha256:{}".format(config_sha),
            },
            "layers": []}

        # Fill in the layer information
        for layer in config["rootfs"]["diff_ids"]:
            manifest["layers"].append({
                "mediaType":
                    "application/vnd.docker.image.rootfs.diff.tar.gzip",
                "size": preloaded_data[layer].content.filesize,
                "digest": layer})
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
            config = cls._getJSONfile(
                build.getFileByName(section['Config']))
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
    def _calculateTag(cls, build, push_rule):
        """Work out the base tag for the image should be.

        :param build: `OCIRecipeBuild` representing this build.
        :param push_rule: `OCIPushRule` that we are using.
        """
        # XXX twom 2020-04-17 This needs to include OCIProjectSeries and
        # base image name
        if build:
            return "{}-{}".format(build.processor.name, "edge")
        else:
            return "edge"

    @classmethod
    def _uploadRegistryManifest(cls, http_client, registry_manifest,
                                push_rule, build=None):
        """Uploads the build manifest, returning its content digest."""
        tag = cls._calculateTag(build, push_rule)
        digest = None
        data = json.dumps(registry_manifest)
        size = len(data)
        content_type = registry_manifest.get(
            "mediaType",
            "application/vnd.docker.distribution.manifest.v2+json")

        try:
            manifest_response = http_client.requestPath(
                "/manifests/{}".format(tag),
                data=data,
                headers={"Content-Type": content_type},
                method="PUT")
            digest = manifest_response.headers.get("Docker-Content-Digest")
        except HTTPError as http_error:
            manifest_response = http_error.response
        if manifest_response.status_code != 201:
            if build:
                msg = "Failed to upload manifest for {} ({}) in {}".format(
                    build.recipe.name, push_rule.registry_url, build.id)
            else:
                msg = ("Failed to upload manifest of manifests for"
                       " {} ({})").format(
                    push_rule.recipe.name, push_rule.registry_url)
            raise cls._makeRegistryError(
                ManifestUploadFailed, msg, manifest_response)
        return {"digest": digest, "size": size}

    @classmethod
    def _upload_to_push_rule(
            cls, push_rule, build, manifest, digests, preloaded_data):
        http_client = RegistryHTTPClient.getInstance(push_rule)

        for section in manifest:
            # Work out names
            file_data = preloaded_data[section["Config"]]
            config = file_data["config_file"]
            #  Upload the layers involved
            for diff_id in config["rootfs"]["diff_ids"]:
                cls._upload_layer(
                    diff_id,
                    push_rule,
                    file_data[diff_id],
                    http_client)
            # The config file is required in different forms, so we can
            # calculate the sha, work these out and upload
            config_json = json.dumps(config).encode("UTF-8")
            config_sha = hashlib.sha256(config_json).hexdigest()
            cls._upload(
                "sha256:{}".format(config_sha),
                push_rule,
                BytesIO(config_json),
                http_client)

            # Build the registry manifest from the image manifest
            # and associated configs
            registry_manifest = cls._build_registry_manifest(
                digests, config, config_json, config_sha,
                preloaded_data[section["Config"]])

            # Upload the registry manifest
            maanifest = cls._uploadRegistryManifest(
                http_client, registry_manifest, push_rule, build)

            # Save the uploaded manifest location, so we can use it in case
            # this is a multi-arch image upload.
            if build.build_request:
                build.build_request.addUploadedManifest(build.id, maanifest)

    @classmethod
    def upload(cls, build):
        """Upload the artifacts from an OCIRecipeBuild to a registry.

        :param build: `OCIRecipeBuild` representing this build.
        :raises ManifestUploadFailed: If the final registry manifest fails to
                                      upload due to network or validity.
        """
        # Get the required metadata files
        manifest = cls._getJSONfile(build.manifest)
        digests_list = cls._getJSONfile(build.digests)
        digests = {}
        for digest_dict in digests_list:
            digests.update(digest_dict)

        # Preload the requested files
        preloaded_data = cls._preloadFiles(build, manifest, digests)

        exceptions = []
        for push_rule in build.recipe.push_rules:
            try:
                cls._upload_to_push_rule(
                    push_rule, build, manifest, digests, preloaded_data)
            except Exception as e:
                exceptions.append(e)
        if len(exceptions) == 1:
            raise exceptions[0]
        elif len(exceptions) > 1:
            raise MultipleOCIRegistryError(exceptions)

    @classmethod
    def makeMultiArchManifest(cls, build_request):
        """Returns the multi-arch manifest content."""
        manifests = []
        for build in build_request.builds:
            build_manifest = build_request.uploaded_manifests.get(build.id)
            if not build_manifest:
                continue
            digest = build_manifest["digest"]
            size = build_manifest["size"]
            arch = build.processor.name
            manifests.append({
                "mediaType": ("application/"
                              "vnd.docker.distribution.manifest.v2+json"),
                "size": size,
                "digest": digest,
                "platform": {"architecture": arch, "os": "linux"}
            })
        return {
          "schemaVersion": 2,
          "mediaType": ("application/"
                        "vnd.docker.distribution.manifest.list.v2+json"),
          "manifests": manifests}

    @classmethod
    def uploadManifestList(cls, build_request):
        multi_manifest_content = cls.makeMultiArchManifest(build_request)
        for push_rule in build_request.recipe.push_rules:
            http_client = RegistryHTTPClient.getInstance(push_rule)
            cls._uploadRegistryManifest(
                http_client, multi_manifest_content, push_rule, build=None)


class OCIRegistryAuthenticationError(Exception):
    def __init__(self, msg, http_error=None):
        super(OCIRegistryAuthenticationError, self).__init__(msg)
        self.http_error = http_error


class RegistryHTTPClient:
    def __init__(self, push_rule):
        self.push_rule = push_rule

    @property
    def credentials(self):
        """Returns a tuple of (username, password)."""
        auth = self.push_rule.registry_credentials.getCredentials()
        if auth.get('username'):
            return auth['username'], auth.get('password')
        return None, None

    @property
    def api_url(self):
        """Returns the base API URL for this registry."""
        push_rule = self.push_rule
        return "{}/v2/{}".format(push_rule.registry_url, push_rule.image_name)

    def request(self, url, *args, **request_kwargs):
        username, password = self.credentials
        if username is not None:
            request_kwargs.setdefault("auth", (username, password))
        return proxy_urlfetch(url, **request_kwargs)

    def requestPath(self, path, *args, **request_kwargs):
        """Shortcut to do a request to {self.api_url}/{path}."""
        url = "{}{}".format(self.api_url, path)
        return self.request(url, *args, **request_kwargs)

    @classmethod
    def getInstance(cls, push_rule):
        """Returns an instance of RegistryHTTPClient adapted to the
        given push rule and registry's authentication flow."""
        try:
            proxy_urlfetch("{}/v2/".format(push_rule.registry_url))
            # No authorization error? Just return the basic RegistryHTTPClient.
            return RegistryHTTPClient(push_rule)
        except HTTPError as e:
            # If we got back an "UNAUTHORIZED" error with "Www-Authenticate"
            # header, we should check what type of authorization we should use.
            header_key = "Www-Authenticate"
            if (e.response.status_code == 401
                    and header_key in e.response.headers):
                auth_type = e.response.headers[header_key].split(' ', 1)[0]
                if auth_type == 'Bearer':
                    # Note that, although we have the realm where to
                    # authenticate, we do not retrieve the authentication
                    # token here. Different operations might need different
                    # permission scope (defined at "Bearer ...scope=yyy").
                    # So, we defer the token fetching to a moment where we
                    # are actually doing the operations and we will get info
                    # about what scope we will need.
                    return BearerTokenRegistryClient(push_rule)
                elif auth_type == 'Basic':
                    return RegistryHTTPClient(push_rule)
            raise OCIRegistryAuthenticationError(
                "Unknown authentication type for %s registry" %
                push_rule.registry_url, e)


class BearerTokenRegistryClient(RegistryHTTPClient):
    """Special case of RegistryHTTPClient for registries with auth
    based on bearer token, like DockerHub.

    This client type is prepared to deal with DockerHub's authorization
    cycle, which involves fetching the appropriate authorization token
    instead of using HTTP's basic auth.
    """

    def __init__(self, push_rule):
        super(BearerTokenRegistryClient, self).__init__(push_rule)
        self.auth_token = None

    def parseAuthInstructions(self, request):
        """Parse the Www-Authenticate response header.

        This method parses the appropriate header from the request and returns
        the token type and the key-value pairs that should be used as query
        parameters of the token GET request."""
        instructions = request.headers['Www-Authenticate']
        token_type, values = instructions.split(' ', 1)
        dict_values = parse_keqv_list(parse_http_list(values))
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
                % values)
        # We should use the basic auth version for this request.
        response = super(BearerTokenRegistryClient, self).request(
            url, params=values, method="GET", auth=self.credentials)
        response.raise_for_status()
        response_data = response.json()
        try:
            self.auth_token = response_data["token"]
        except KeyError:
            raise OCIRegistryAuthenticationError(
                "Could not get token from response data: %s" % response_data)

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
                    url, auth_retry=False, headers=headers,
                    *args, **request_kwargs)
            raise
