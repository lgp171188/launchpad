# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A fixture that simulates parts of the Artifactory API."""

__all__ = [
    "FakeArtifactoryFixture",
    ]

from datetime import (
    datetime,
    timezone,
    )
import fnmatch
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import (
    parse_qs,
    unquote,
    urlparse,
    )

from fixtures import Fixture
import responses


class FakeArtifactoryFixture(Fixture):

    def __init__(self, base_url, repository_name):
        self.base_url = base_url
        self.repository_name = repository_name
        self.repo_url = "%s/%s" % (base_url, self.repository_name)
        self.api_url = "%s/api/storage/%s" % (
            self.base_url, self.repository_name)
        self.search_url = "%s/api/search/aql" % self.base_url
        self._fs = {}
        self.add_dir("/")

    def _setUp(self):
        self.requests_mock = responses.RequestsMock(
            assert_all_requests_are_fired=False)
        self.requests_mock.start()
        self.addCleanup(self.requests_mock.stop)
        repo_url_regex = re.compile(r"^%s/.*" % re.escape(self.repo_url))
        api_url_regex = re.compile(r"^%s/.*" % re.escape(self.api_url))
        self.requests_mock.add(responses.CallbackResponse(
            method="GET", url=repo_url_regex, callback=self._handle_download,
            stream=True))
        self.requests_mock.add_callback(
            "GET", api_url_regex, callback=self._handle_stat)
        self.requests_mock.add_callback(
            "PUT", repo_url_regex, callback=self._handle_upload)
        self.requests_mock.add_callback(
            "PUT", api_url_regex, callback=self._handle_set_properties)
        self.requests_mock.add_callback(
            "POST", self.search_url, callback=self._handle_aql)
        self.requests_mock.add_callback(
            "DELETE", repo_url_regex, callback=self._handle_delete)
        self.requests_mock.add_callback(
            "DELETE", api_url_regex, callback=self._handle_delete_properties)

    def add_dir(self, path):
        now = datetime.now(timezone.utc).isoformat()
        self._fs[path] = {"created": now, "lastModified": now}

    def add_file(self, path, contents, size, properties):
        now = datetime.now(timezone.utc).isoformat()
        body = contents.read(size)
        self._fs[path] = {
            "created": now,
            "lastModified": now,
            "size": str(size),
            "checksums": {"sha1": hashlib.sha1(body).hexdigest()},
            "body": body,
            "properties": properties,
            }

    def remove_file(self, path):
        del self._fs[path]

    def _handle_download(self, request):
        """Handle a request to download an existing file."""
        path = urlparse(request.url[len(self.repo_url):]).path
        if path in self._fs and "size" in self._fs[path]:
            return (
                200, {"Content-Type": "application/octet-stream"},
                self._fs[path]["body"])
        else:
            return 404, {}, "Unable to find item"

    def _handle_stat(self, request):
        """Handle a request to stat an existing file."""
        parsed_url = urlparse(request.url[len(self.api_url):])
        path = parsed_url.path
        if path in self._fs:
            stat = {"repo": self.repository_name, "path": path}
            stat.update(self._fs[path])
            stat.pop("body", None)
            if parsed_url.query != "properties":
                stat.pop("properties", None)
            return 200, {}, json.dumps(stat)
        else:
            return 404, {}, "Unable to find item"

    def _decode_properties(self, encoded):
        """Decode properties that were encoded as part of a request."""
        properties = {}
        for param in encoded.split(";"):
            key, value = param.split("=", 1)
            # XXX cjwatson 2022-04-19: Check whether this unquoting approach
            # actually matches the artifactory module and Artifactory
            # itself.
            properties[unquote(key)] = [unquote(v) for v in value.split(",")]
        return properties

    def _handle_upload(self, request):
        """Handle a request to upload a directory or file."""
        parsed_url = urlparse(request.url[len(self.repo_url):])
        path = parsed_url.path
        if path.endswith("/"):
            self.add_dir(path.rstrip("/"))
        elif path.rsplit("/", 1)[0] in self._fs:
            properties = self._decode_properties(parsed_url.params)
            self.add_file(
                path, request.body,
                int(request.headers["Content-Length"]), properties)
        return 201, {}, ""

    def _handle_set_properties(self, request):
        """Handle a request to set properties on an existing file."""
        parsed_url = urlparse(request.url[len(self.api_url):])
        path = parsed_url.path
        if path in self._fs:
            query = parse_qs(parsed_url.query)
            properties = self._decode_properties(query["properties"][0])
            self._fs[path]["properties"].update(properties)
            return 204, {}, ""
        else:
            return 404, {}, "Unable to find item"

    def _handle_delete_properties(self, request):
        """Handle a request to delete properties from an existing file."""
        parsed_url = urlparse(request.url[len(self.api_url):])
        path = parsed_url.path
        if path in self._fs:
            query = parse_qs(parsed_url.query)
            for key in query["properties"][0].split(","):
                del self._fs[path]["properties"][unquote(key)]
            return 204, {}, ""
        else:
            return 404, {}, "Unable to find item"

    def _make_aql_item(self, path):
        """Return an AQL response item based on an entry in `self._fs`."""
        path_obj = Path(path)
        return {
            "repo": self.repository_name,
            "path": path_obj.parent.as_posix()[1:],
            "name": path_obj.name,
            "properties": [
                {"key": key, "value": v}
                for key, value in sorted(
                    self._fs[path]["properties"].items())
                for v in value],
            }

    def _matches_aql(self, item, criteria):
        """Return True if an item matches some AQL criteria.

        This is definitely incomplete, but good enough for our testing
        needs.

        https://www.jfrog.com/confluence/display/JFROG/\
          Artifactory+Query+Language
        """
        for key, value in criteria.items():
            if key == "$and":
                if not all(self._matches_aql(item, v) for v in value):
                    return False
            elif key == "$or":
                if not any(self._matches_aql(item, v) for v in value):
                    return False
            elif key.startswith("$"):
                raise ValueError("Unhandled AQL operator: %s" % key)
            elif key in item:
                if isinstance(value, dict) and len(value) == 1:
                    [(comp_op, comp_value)] = value.items()
                    if comp_op == "$match":
                        if not fnmatch.fnmatch(item[key], comp_value):
                            return False
                    else:
                        raise ValueError(
                            "Unhandled AQL comparison operator: %s" % key)
                elif isinstance(value, str):
                    if item[key] != value:
                        return False
                else:
                    raise ValueError("Unhandled AQL criterion: %r" % value)
            else:
                raise ValueError("Unhandled AQL key: %s" % key)
        return True

    def _handle_aql(self, request):
        """Handle a request to perform an AQL search.

        No, of course we don't implement a full AQL parser.
        """
        match = re.match(
            r"^items\.find\((.*?)\)\.include\((.*?)\)$", request.body)
        if match is None:
            return 400, {}, ""
        # Treating this as JSON is cheating a bit, but it works.
        criteria = json.loads(match.group(1))
        items = [
            self._make_aql_item(path)
            for path in sorted(self._fs) if "size" in self._fs[path]]
        results = [item for item in items if self._matches_aql(item, criteria)]
        return 200, {}, json.dumps({"results": results})

    def _handle_delete(self, request):
        """Handle a request to delete an existing file."""
        path = urlparse(request.url[len(self.repo_url):]).path
        if not path.endswith("/") and path in self._fs:
            self.remove_file(path)
        return 200, {}, ""
