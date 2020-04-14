# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Client for talking to an OCI registry."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRegistryClient'
]


from io import BytesIO
import hashlib
import json
import logging
import tarfile

from requests.exceptions import HTTPError
from zope.interface import implementer

from lp.oci.interfaces.ociregistryclient import (
    BlobUploadFailed,
    IOCIRegistryClient,
    ManifestUploadFailed,
    )
from lp.services.timeout import urlfetch

log = logging.getLogger("ociregistryclient")


@implementer(IOCIRegistryClient)
class OCIRegistryClient:

    @classmethod
    def _getJSONfile(cls, reference):
        """Read JSON out of a `LibraryFileAlias`."""
        _, lfa, lfc = reference
        try:
            lfa.open()
            return json.loads(lfa.read())
        finally:
            lfa.close()

    @classmethod
    def _upload(cls, digest, push_rule, name, fileobj):
        """Upload a blob to the registry, using a given digest.

        :param digest: The digest to store the file under.
        :param push_rule: `OCIPushRule` to use for the URL and credentials.
        :param name: Name of the image the blob is part of.
        :param fileobj: An object that looks like a buffer.

        :raises BlobUploadFailed: if the registry does not accept the blob.
        """
        # Check if it already exists
        try:
            head_response = urlfetch(
                "{}/v2/{}/blobs/{}".format(
                    push_rule.registry_credentials.url, name, digest),
                method="HEAD")
            if head_response.status_code == 200:
                log.info("{} already found".format(digest))
                return
        except HTTPError as http_error:
            # A 404 is fine, we're about to upload the layer anyway
            if http_error.response.status_code != 404:
                raise http_error

        post_response = urlfetch(
            "{}/v2/{}/blobs/uploads/".format(
                push_rule.registry_credentials.url, name),
            method="POST")

        post_location = post_response.headers["Location"]
        query_parsed = {"digest": digest}

        put_response = urlfetch(
            post_location,
            params=query_parsed,
            data=fileobj,
            method="PUT"
        )

        if put_response.status_code != 201:
            raise BlobUploadFailed(
                "Upload of {} for {} failed".format(digest, name))

    @classmethod
    def _upload_layer(cls, digest, push_rule, name, lfa):
        """Upload a layer blob to the registry.

        Uses _upload, but opens the LFA and extracts the necessary files
        from the .tar.gz first.

        :param digest: The digest to store the file under.
        :param push_rule: `OCIPushRule` to use for the URL and credentials.
        :param name: Name of the image the blob is part of.
        :param lfa: The `LibraryFileAlias` for the layer.
        """
        lfa.open()
        try:
            un_zipped = tarfile.open(fileobj=lfa, mode='r|gz')
            for tarinfo in un_zipped:
                if tarinfo.name != 'layer.tar':
                    continue
                fileobj = un_zipped.extractfile(tarinfo)
                cls._upload(digest, push_rule, name, fileobj)
        finally:
            lfa.close()

    @classmethod
    def _build_registry_manifest(cls, name, digests,
                              config, config_json, config_sha):
        """Create an image manifest for the uploading image.

        This involves nearly everything as digests and lengths are required.
        This method creates a minimal manifest, some fields are missing.

        :param name: The name of the image to upload.
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
            "layers": [],
        }

        # Fill in the layer information
        for layer in config["rootfs"]["diff_ids"]:
            manifest["layers"].append(
                {
                    "mediaType":
                        "application/vnd.docker.image.rootfs.diff.tar.gzip",
                    "size": 0,  # XXX twom 2020-04-14 We can get this from LFA
                    "digest": layer,
                }
            )
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
                build.getByFileName(section['Config']))
            files = {"config_file": config}
            for diff_id in config["rootfs"]["diff_ids"]:
                # We may have already seen this diff ID.
                if files.get(diff_id):
                    continue
                # Retrieve the layer files.
                # This doesn't read the content, so there is potential
                # for multiple fetches, but the files can be arbitary size
                # Potentially gigabytes.
                files[diff_id] = {}
                source_digest = digests[diff_id]["digest"]
                _, lfa, _ = build.getLayerFileByDigest(source_digest)
                files[diff_id] = lfa
            data[section["Config"]] = files
        return data

    @classmethod
    def _calculateName(cls, build, push_rule):
        """Work out what the name for the image should be.

        :param build: `OCIRecipeBuild` representing this build.
        :param push_rule: `OCIPushRule` that we are using.
        """
        return "{}/{}".format(
            build.recipe.oci_project.pillar.name,
            push_rule.image_name)

    @classmethod
    def _calculateTag(cls, build, push_rule):
        """Work out the base tag for the image should be.

        :param build: `OCIRecipeBuild` representing this build.
        :param push_rule: `OCIPushRule` that we are using.
        """
        # XXX twom 2020-04-17 This needs to include OCIProjectSeries and
        # base image name

        return "{}".format("edge")

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
            for k, v in digest_dict.items():
                digests[k] = v

        # Preload the requested files
        preloaded_data = cls._preloadFiles(build, manifest, digests)

        for push_rule in build.recipe.push_rules:
            for section in manifest:
                # Work out names and tags
                image_name = cls._calculateName(build, push_rule)
                tag = cls._calculateTag(build, push_rule)
                file_data = preloaded_data[section["Config"]]
                config = file_data["config_file"]
                #  Upload the layers involved
                for diff_id in config["rootfs"]["diff_ids"]:
                    cls._upload_layer(
                        diff_id,
                        push_rule,
                        image_name,
                        file_data[diff_id])
                # The config file is required in different forms, so we can
                # calculate the sha, work these out and upload
                config_json = json.dumps(config).encode()
                config_sha = hashlib.sha256(config_json).hexdigest()
                cls._upload(
                    "sha256:{}".format(config_sha),
                    push_rule,
                    image_name,
                    BytesIO(config_json)
                )

                # Build the registry manifest from the image manifest
                # and associated configs
                registry_manifest = cls._build_registry_manifest(
                    image_name, digests,
                    config, config_json, config_sha)

                # Upload the registry manifest
                manifest_response = urlfetch(
                    "{}/v2/{}/manifests/{}".format(
                        push_rule.registry_credentials.url,
                        image_name,
                        tag),
                    json=registry_manifest,
                    headers={
                        "Content-Type":
                            "application/"
                            "vnd.docker.distribution.manifest.v2+json"
                        },
                    method="PUT"
                )
                if manifest_response.status_code != 201:
                    raise ManifestUploadFailed(
                        "Failed to upload manifest for {} in {}".format(
                            build.recipe.name, build.id))
