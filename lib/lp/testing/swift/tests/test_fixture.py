# Copyright 2013-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Testing the mock Swift test fixture."""

from datetime import datetime
from hashlib import md5
from typing import List

from requests.exceptions import ConnectionError
from swiftclient import client as swiftclient
from testtools.matchers import GreaterThan, LessThan, MatchesStructure, Not

from lp.services.config import config
from lp.services.librarianserver import swift
from lp.testing import TestCase
from lp.testing.factory import ObjectFactory
from lp.testing.layers import BaseLayer
from lp.testing.swift import fakeswift
from lp.testing.swift.fixture import SwiftFixture

__all__: List[str] = []


class TestSwiftFixture(TestCase):
    layer = BaseLayer

    def setUp(self):
        super().setUp()
        self.swift_fixture = SwiftFixture()
        self.useFixture(self.swift_fixture)
        self.factory = ObjectFactory()

    def makeSampleObject(self, client, contents, content_type=None):
        """Create a new container and a new sample object within it."""
        cname = self.factory.getUniqueUnicode()
        oname = self.factory.getUniqueUnicode()
        client.put_container(cname)
        client.put_object(cname, oname, contents, content_type=content_type)
        return cname, oname

    def test_get(self):
        client = self.swift_fixture.connect()
        size = 30
        headers, body = client.get_object("size", str(size))
        self.assertEqual(b"0" * size, body)
        self.assertEqual(str(size), headers["content-length"])
        self.assertEqual("text/plain", headers["content-type"])

    def test_get_404(self):
        client = self.swift_fixture.connect()
        cname = self.factory.getUniqueUnicode()
        client.put_container(cname)
        exc = self.assertRaises(
            swiftclient.ClientException,
            client.get_object,
            cname,
            "nonexistent",
        )
        self.assertEqual(404, exc.http_status)

    def test_get_403(self):
        client = self.swift_fixture.connect(key="bad key")
        exc = self.assertRaises(
            swiftclient.ClientException, client.get_container, "size"
        )
        # swiftclient should possibly set exc.http_status here, but doesn't.
        self.assertEqual(
            "Authorization Failure. "
            "Authorization Failed: Forbidden (HTTP 403)",
            str(exc),
        )

    def test_put(self):
        client = self.swift_fixture.connect()
        message = b"Hello World!"
        cname, oname = self.makeSampleObject(client, message, "text/something")
        for x in range(1, 10):
            headers, body = client.get_object(cname, oname)
            self.assertEqual(message * x, body)
            self.assertEqual(str(len(message) * x), headers["content-length"])
            self.assertEqual("text/something", headers["content-type"])
            client.put_object(
                cname, oname, message * (x + 1), content_type="text/something"
            )

    def test_get_container(self):
        # Basic container listing.
        start = datetime.utcnow().replace(microsecond=0)
        client = self.swift_fixture.connect()
        message = b"42"
        cname, oname = self.makeSampleObject(client, message, "text/something")
        client.put_object(cname, oname + ".2", message)

        _, container = client.get_container(cname)
        self.assertEqual(2, len(container))
        obj = container[0]
        self.assertEqual(oname, obj["name"])
        self.assertEqual(len(message), obj["bytes"])
        self.assertEqual(md5(message).hexdigest(), obj["hash"])
        self.assertEqual("text/something", obj["content-type"])
        last_modified = datetime.strptime(
            obj["last_modified"], "%Y-%m-%dT%H:%M:%S.%f"
        )  # ISO format
        self.assertThat(last_modified, Not(LessThan(start)))
        self.assertThat(last_modified, Not(GreaterThan(datetime.utcnow())))

    def test_get_container_marker(self):
        # Container listing supports the marker parameter.
        client = self.swift_fixture.connect()
        message = b"Hello"
        cname, oname = self.makeSampleObject(client, message, "text/something")
        oname2 = oname + ".2"
        oname3 = oname + ".3"
        client.put_object(cname, oname2, message)
        client.put_object(cname, oname3, message)

        # List contents found after name == marker.
        _, container = client.get_container(cname, marker=oname)
        self.assertEqual(2, len(container))
        self.assertEqual(oname2, container[0]["name"])
        self.assertEqual(oname3, container[1]["name"])

    def test_get_container_end_marker(self):
        # Container listing supports the end_marker parameter.
        client = self.swift_fixture.connect()
        message = b"Hello"
        cname, oname = self.makeSampleObject(client, message, "text/something")
        oname2 = oname + ".2"
        oname3 = oname + ".3"
        client.put_object(cname, oname2, message)
        client.put_object(cname, oname3, message)

        # List contents found before name == end_marker.
        _, container = client.get_container(cname, end_marker=oname3)
        self.assertEqual(2, len(container))
        self.assertEqual(oname, container[0]["name"])
        self.assertEqual(oname2, container[1]["name"])

    def test_get_container_limit(self):
        # Container listing supports the limit parameter.
        client = self.swift_fixture.connect()
        message = b"Hello"
        cname, oname = self.makeSampleObject(client, message, "text/something")
        oname2 = oname + ".2"
        oname3 = oname + ".3"
        client.put_object(cname, oname2, message)
        client.put_object(cname, oname3, message)

        # Limit list to two objects.
        _, container = client.get_container(cname, limit=2)
        self.assertEqual(2, len(container))
        self.assertEqual(oname, container[0]["name"])
        self.assertEqual(oname2, container[1]["name"])

    def test_get_container_prefix(self):
        client = self.swift_fixture.connect()
        message = b"Hello"
        cname, oname = self.makeSampleObject(client, message, "text/something")
        oname2 = "different"
        oname3 = oname + ".3"
        client.put_object(cname, oname2, message)
        client.put_object(cname, oname3, message)

        # List contents whose object names start with prefix.
        _, container = client.get_container(cname, prefix=oname)
        self.assertEqual(2, len(container))
        self.assertEqual(oname, container[0]["name"])
        self.assertEqual(oname3, container[1]["name"])

    def test_get_container_full_listing(self):
        client = self.swift_fixture.connect()
        message = b"42"
        cname, oname = self.makeSampleObject(client, message, "text/something")

        _, container = client.get_container(cname, full_listing=True)
        self.assertEqual(1, len(container))

    def test_shutdown_and_startup(self):
        # This test demonstrates how the Swift client deals with a
        # flapping Swift server.
        size = 30

        # With no Swift server, a fresh connection fails with
        # a swiftclient.ClientException when it fails to
        # authenticate.
        client = self.swift_fixture.connect()
        self.swift_fixture.shutdown()
        self.assertRaises(
            swiftclient.ClientException, client.get_object, "size", str(size)
        )

        # Things work fine when the Swift server is up.
        self.swift_fixture.startup()
        headers, body = client.get_object("size", str(size))
        self.assertEqual(body, b"0" * size)

        # But if the Swift server goes away again, we end up with
        # different failures since the connection has already
        # authenticated.
        self.swift_fixture.shutdown()
        self.assertRaises(
            ConnectionError, client.get_object, "size", str(size)
        )

        # If we bring it back up, the client retries and succeeds.
        self.swift_fixture.startup()
        headers, body = client.get_object("size", str(size))
        self.assertEqual(body, b"0" * size)

    def test_env(self):
        self.assertThat(
            config.librarian_server,
            MatchesStructure.byEquality(
                os_auth_url="http://localhost:{}/keystone/v2.0/".format(
                    self.swift_fixture.daemon_port
                ),
                os_username=fakeswift.DEFAULT_USERNAME,
                os_password=fakeswift.DEFAULT_PASSWORD,
                os_tenant_name=fakeswift.DEFAULT_TENANT_NAME,
            ),
        )

    def test_old_instance_env(self):
        old_swift_fixture = self.useFixture(SwiftFixture(old_instance=True))
        self.assertThat(
            config.librarian_server,
            MatchesStructure.byEquality(
                os_auth_url="http://localhost:{}/keystone/v2.0/".format(
                    self.swift_fixture.daemon_port
                ),
                os_username=fakeswift.DEFAULT_USERNAME,
                os_password=fakeswift.DEFAULT_PASSWORD,
                os_tenant_name=fakeswift.DEFAULT_TENANT_NAME,
                old_os_auth_url="http://localhost:{}/keystone/v2.0/".format(
                    old_swift_fixture.daemon_port
                ),
                old_os_username=fakeswift.DEFAULT_USERNAME,
                old_os_password=fakeswift.DEFAULT_PASSWORD,
                old_os_tenant_name=fakeswift.DEFAULT_TENANT_NAME,
            ),
        )

    def test_reconfigures_librarian_server(self):
        # Fixtures providing old and new Swift instances don't interfere
        # with each other, and they reconfigure the librarian server
        # appropriately on setup.
        self.assertEqual(1, len(swift.connection_pools))
        message = b"Hello World!"
        with swift.connection() as client:
            cname, oname = self.makeSampleObject(
                client, message, "text/something"
            )
            headers, body = client.get_object(cname, oname)
            self.assertEqual(message, body)
        self.useFixture(SwiftFixture(old_instance=True))
        self.assertEqual(2, len(swift.connection_pools))
        with swift.connection() as client:
            headers, body = client.get_object(cname, oname)
            self.assertEqual(message, body)
        with swift.connection(swift.connection_pools[0]) as old_client:
            exc = self.assertRaises(
                swiftclient.ClientException,
                old_client.get_object,
                cname,
                oname,
            )
            self.assertEqual(404, exc.http_status)
            old_cname, old_oname = self.makeSampleObject(
                old_client, message, "text/something"
            )
            headers, body = old_client.get_object(old_cname, old_oname)
            self.assertEqual(message, body)
        with swift.connection(swift.connection_pools[1]) as client:
            exc = self.assertRaises(
                swiftclient.ClientException,
                client.get_object,
                old_cname,
                old_oname,
            )
            self.assertEqual(404, exc.http_status)
        # The last (i.e. newest) connection pool is the default.
        with swift.connection() as client:
            exc = self.assertRaises(
                swiftclient.ClientException,
                client.get_object,
                old_cname,
                old_oname,
            )
            self.assertEqual(404, exc.http_status)
