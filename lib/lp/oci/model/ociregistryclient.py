import hashlib
import json
from StringIO import StringIO
import tarfile

import requests


class LayerNotFound(Exception):
    pass


class LayerMountFailed(Exception):
    pass


class LayerUploadFailed(Exception):
    pass


class ManifestUploadFailed(Exception):
    pass


class OCIRegistryClient():

    def _getJSONfile(self, reference):
        _, lfa, lfc = reference
        try:
            lfa.open()
            return json.loads(lfa.read())
        finally:
            lfa.close()

    def _upload(self, digest, push_rule, name, fileobj):

        # Check if it already exists
        head_response = requests.head(
            "{}/v2/{}/blobs/{}".format(
                push_rule.registry_credentials.url, name, digest))
        if head_response.status_code == 200:
            print("{} already found".format(digest))
            return

        post_request = requests.post(
            "{}/v2/{}/blobs/uploads/".format(
                push_rule.registry_credentials.url, name))

        post_location = post_request.headers["Location"]
        query_parsed = {"digest": digest}

        put_response = requests.put(
            post_location, params=query_parsed,
            data=fileobj)

        if put_response.status_code != 201:
            raise LayerUploadFailed(
                "Upload of {} for {} failed".format(digest, name))

    def _upload_layer(self, digest, push_rule, name, lfa):

        lfa.open()
        try:
            un_zipped = tarfile.open(fileobj=lfa, mode='r|gz')
            for tarinfo in un_zipped:
                if tarinfo.name != 'layer.tar':
                    continue
                fileobj = un_zipped.extractfile(tarinfo)
                self._upload(digest, push_rule, name, fileobj)
        finally:
            lfa.close()

    def _build_image_manifest(self, name, tag, digests,
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

    def _preloadFiles(self, build, manifest, digests):
        # preload the data from the librarian to avoid potential multiple
        # pulls if there is more than one push rule
        data = {}
        for section in manifest:
            config = self._getJSONfile(
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

    def upload(self, build):
        # get manifest
        manifest = self._getJSONfile(build.manifest)
        digests_list = self._getJSONfile(build.digests)
        digests = {}
        for digest_dict in digests_list:
            for k, v in digest_dict.items():
                digests[k] = v

        # XXX twom 2020-04-06 This should be calculated
        build_tag = "temp-build-tag"

        preloaded_data = self._preloadFiles(build, manifest, digests)

        for push_rule in build.recipe.push_rules:
            for section in manifest:
                file_data = preloaded_data[section["Config"]]
                config = file_data["config_file"]
                for diff_id in config["rootfs"]["diff_ids"]:
                    self._upload_layer(
                        diff_id,
                        push_rule,
                        push_rule.image_name,
                        file_data[diff_id].get('lfa'))
                config_json = json.dumps(config).encode()
                config_sha = hashlib.sha256(config_json).hexdigest()
                self._upload(
                    "sha256:{}".format(config_sha),
                    push_rule,
                    push_rule.image_name,
                    StringIO(config_json)
                )
                image_manifest = self._build_image_manifest(
                    push_rule.image_name, build_tag, digests,
                    config, config_json, config_sha)

                manifest_response = requests.put(
                    "{}/v2/{}/manifests/latest".format(
                        push_rule.registry_credentials.url,
                        push_rule.image_name),
                    json=image_manifest,
                    headers={
                        "Content-Type":
                            "application/"
                            "vnd.docker.distribution.manifest.v2+json"
                        },
                )
                if manifest_response.status_code != 201:
                    raise ManifestUploadFailed(
                        "Failed to upload manifest for {} in {}".format(
                            build.recipe.name, build.id))
