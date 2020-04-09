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
    IOCIRegistryClient,
    LayerUploadFailed,
    ManifestUploadFailed,
    )
from lp.services.timeout import urlfetch

log = logging.getLogger("ociregistryclient")


@implementer(IOCIRegistryClient)
class OCIRegistryClient:

    @classmethod
    def _getJSONfile(cls, reference):
        _, lfa, lfc = reference
        try:
            lfa.open()
            return json.loads(lfa.read())
        finally:
            lfa.close()

    @classmethod
    def _upload(cls, digest, push_rule, name, fileobj):

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
            raise LayerUploadFailed(
                "Upload of {} for {} failed".format(digest, name))

    @classmethod
    def _upload_layer(cls, digest, push_rule, name, lfa):

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
    def _build_image_manifest(cls, name, tag, digests,
                              config, config_json, config_sha):
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

        for layer in config["rootfs"]["diff_ids"]:
            manifest["layers"].append(
                {
                    "mediaType":
                        "application/vnd.docker.image.rootfs.diff.tar.gzip",
                    "size": 0,  # This doesn't appear to matter?
                    "digest": layer,
                }
            )
        return manifest

    @classmethod
    def _preloadFiles(cls, build, manifest, digests):
        # preload the data from the librarian to avoid potential multiple
        # pulls if there is more than one push rule
        data = {}
        for section in manifest:
            config = cls._getJSONfile(
                build.getByFileName(section['Config']))
            files = {"config_file": config}
            for diff_id in config["rootfs"]["diff_ids"]:
                files[diff_id] = {}
                source = digests[diff_id]["source"]
                source_digest = digests[diff_id]["digest"]
                files[diff_id]["source"] = source_digest
                _, lfa, _ = build.getLayerFileByDigest(source_digest)
                files[diff_id]["lfa"] = lfa
                files['attempt_mount'] = bool(source)
            data[section["Config"]] = files
        return data

    @classmethod
    def upload(cls, build):
        # get manifest
        manifest = cls._getJSONfile(build.manifest)
        digests_list = cls._getJSONfile(build.digests)
        digests = {}
        for digest_dict in digests_list:
            for k, v in digest_dict.items():
                digests[k] = v

        # XXX twom 2020-04-06 This should be calculated
        build_tag = "temp-build-tag"

        preloaded_data = cls._preloadFiles(build, manifest, digests)

        for push_rule in build.recipe.push_rules:
            for section in manifest:
                file_data = preloaded_data[section["Config"]]
                config = file_data["config_file"]
                for diff_id in config["rootfs"]["diff_ids"]:
                    cls._upload_layer(
                        diff_id,
                        push_rule,
                        push_rule.image_name,
                        file_data[diff_id].get('lfa'))
                config_json = json.dumps(config).encode()
                config_sha = hashlib.sha256(config_json).hexdigest()
                cls._upload(
                    "sha256:{}".format(config_sha),
                    push_rule,
                    push_rule.image_name,
                    BytesIO(config_json)
                )
                image_manifest = cls._build_image_manifest(
                    push_rule.image_name, build_tag, digests,
                    config, config_json, config_sha)

                manifest_response = urlfetch(
                    "{}/v2/{}/manifests/latest".format(
                        push_rule.registry_credentials.url,
                        push_rule.image_name),
                    json=image_manifest,
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
