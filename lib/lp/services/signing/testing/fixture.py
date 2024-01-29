# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Fake signing service fixture."""

__all__ = [
    "SigningServiceFixture",
]

import os.path
import socket
from textwrap import dedent

from nacl.encoding import Base64Encoder
from nacl.public import PrivateKey
from testtools import content, content_type
from txfixtures.tachandler import TacTestFixture

from lp.services.config import config
from lp.services.config.fixture import ConfigFixture, ConfigUseFixture
from lp.testing.factory import ObjectFactory


class SigningServiceFixture(TacTestFixture):
    tacfile = os.path.join(os.path.dirname(__file__), "fakesigning.tac")
    pidfile = None
    logfile = None
    client_private_key = None
    daemon_port = None

    def setUp(self, spew=False, umask=None):
        # Pick a random free port.
        if self.daemon_port is None:
            sock = socket.socket()
            sock.bind(("", 0))
            self.daemon_port = sock.getsockname()[1]
            sock.close()
            self.logfile = os.path.join(
                config.root, "logs", "fakesigning-%s.log" % self.daemon_port
            )
            self.pidfile = os.path.join(
                config.root, "logs", "fakesigning-%s.pid" % self.daemon_port
            )
        assert self.daemon_port is not None

        super().setUp(
            spew=spew,
            umask=umask,
            python_path=os.path.join(config.root, "bin", "py"),
            twistd_script=os.path.join(config.root, "bin", "twistd"),
        )

        logfile = self.logfile
        self.addCleanup(lambda: os.path.exists(logfile) and os.unlink(logfile))

        content.attach_file(
            self,
            logfile,
            "signing-log",
            content_type.UTF8_TEXT,
            buffer_now=False,
        )

        factory = ObjectFactory()
        config_name = factory.getUniqueString()
        config_fixture = self.useFixture(
            ConfigFixture(config_name, os.environ["LPCONFIG"])
        )
        config_fixture.add_section(
            dedent(
                """
            [signing]
            signing_endpoint: http://localhost:{daemon_port}/
            client_private_key: {client_private_key}
            client_public_key: {client_public_key}
            """
            ).format(
                daemon_port=self.daemon_port,
                client_private_key=self.client_private_key.encode(
                    encoder=Base64Encoder
                ).decode("ASCII"),
                client_public_key=self.client_private_key.public_key.encode(
                    encoder=Base64Encoder
                ).decode("ASCII"),
            )
        )
        self.useFixture(ConfigUseFixture(config_name))

    def setUpRoot(self):
        # We don't need a root directory, but this is a convenient place to
        # generate a client key and set environment variables.
        self.client_private_key = PrivateKey.generate()

        os.environ["FAKE_SIGNING_PORT"] = str(self.daemon_port)
        os.environ["FAKE_SIGNING_CLIENT_PUBLIC_KEY"] = (
            self.client_private_key.public_key.encode(
                encoder=Base64Encoder
            ).decode("ASCII")
        )
