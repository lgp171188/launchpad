# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the script to show version information."""

from textwrap import dedent

from fixtures import MockPatch
from testtools.content import text_content

from lp.app import versioninfo
from lp.scripts.utilities.versioninfo import main as versioninfo_main
from lp.testing import TestCase
from lp.testing.fixture import CapturedOutput


class TestVersionInfo(TestCase):

    def runScript(self, args, expect_exit=False):
        try:
            with MockPatch('sys.argv', ['version-info'] + args):
                with CapturedOutput() as captured:
                    versioninfo_main()
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

    def test_attribute_revision(self):
        for option in '-a', '--attribute':
            self.assertEqual(
                versioninfo.revision + '\n',
                self.runScript([option, 'revision']))

    def test_attribute_display_revision(self):
        for option in '-a', '--attribute':
            self.assertEqual(
                versioninfo.display_revision + '\n',
                self.runScript([option, 'display_revision']))

    def test_attribute_date(self):
        for option in '-a', '--attribute':
            self.assertEqual(
                versioninfo.date + '\n',
                self.runScript([option, 'date']))

    def test_attribute_branch_nick(self):
        for option in '-a', '--attribute':
            self.assertEqual(
                versioninfo.branch_nick + '\n',
                self.runScript([option, 'branch_nick']))

    def test_attribute_nonsense(self):
        for option in '-a', '--attribute':
            self.runScript([option, 'nonsense'], expect_exit=True)

    def test_all_attributes(self):
        expected_output = dedent('''\
            Revision: {revision}
            Display revision: {display_revision}
            Date: {date}
            Branch nick: {branch_nick}
            ''').format(
                revision=versioninfo.revision,
                display_revision=versioninfo.display_revision,
                date=versioninfo.date,
                branch_nick=versioninfo.branch_nick)
        self.assertEqual(expected_output, self.runScript([]))
