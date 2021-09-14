# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the script to generate a NaCl key pair."""

__metaclass__ = type

import base64

from fixtures import MockPatch
from nacl.public import (
    PrivateKey,
    PublicKey,
    )
from testtools.content import text_content
from testtools.matchers import (
    MatchesListwise,
    StartsWith,
    )

from lp.services.crypto.scripts.generatekeypair import main as gkp_main
from lp.testing import TestCase
from lp.testing.fixture import CapturedOutput


def decode_key(factory, data):
    return factory(base64.b64decode(data.encode('ASCII')))


class TestGenerateKeyPair(TestCase):

    def runScript(self, args, expect_exit=False):
        try:
            with MockPatch('sys.argv', ['version-info'] + args):
                with CapturedOutput() as captured:
                    gkp_main()
        except SystemExit:
            exited = True
        else:
            exited = False
        stdout = captured.stdout.getvalue()
        stderr = captured.stderr.getvalue()
        self.addDetail('stdout', text_content(stdout))
        self.addDetail('stderr', text_content(stderr))
        if expect_exit:
            if not exited:
                raise AssertionError('Script unexpectedly exited successfully')
        else:
            if exited:
                raise AssertionError(
                    'Script unexpectedly exited unsuccessfully')
            self.assertEqual('', stderr)
        return stdout

    def test_bad_arguments(self):
        self.runScript(['--nonsense'], expect_exit=True)

    def test_generates_key_pair(self):
        lines = self.runScript([]).splitlines()
        self.assertThat(lines, MatchesListwise([
            StartsWith('Private: '),
            StartsWith('Public:  '),
            ]))
        private_key = decode_key(PrivateKey, lines[0][len('Private: '):])
        public_key = decode_key(PublicKey, lines[1][len('Public:  '):])
        self.assertEqual(public_key, private_key.public_key)
