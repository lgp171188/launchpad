# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test syncing branches from production to a staging environment."""

import os.path
import subprocess
from textwrap import dedent

from fixtures import MockPatch, TempDir
from testtools.matchers import DirExists, Equals, Matcher, MatchesListwise, Not

from lp.codehosting.scripts.sync_branches import SyncBranchesScript
from lp.codehosting.vfs import branch_id_to_path
from lp.services.config import config
from lp.services.log.logger import BufferLogger
from lp.services.scripts.base import LaunchpadScriptFailure
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class BranchDirectoryCreated(Matcher):
    def __str__(self):
        return "BranchDirectoryCreated()"

    def match(self, branch):
        return DirExists().match(
            os.path.join(
                config.codehosting.mirrored_branches_root,
                branch_id_to_path(branch.id),
            )
        )


class BranchSyncProcessMatches(MatchesListwise):
    def __init__(self, branch):
        branch_path = branch_id_to_path(branch.id)
        super().__init__(
            [
                Equals(
                    (
                        [
                            "rsync",
                            "-a",
                            "--delete-after",
                            "bazaar.lp.internal::mirrors/%s/" % branch_path,
                            "%s/"
                            % os.path.join(
                                config.codehosting.mirrored_branches_root,
                                branch_path,
                            ),
                        ],
                    )
                ),
                Equals({"universal_newlines": True}),
            ]
        )


class TestSyncBranches(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.tempdir = self.useFixture(TempDir()).path
        self.pushConfig("codehosting", mirrored_branches_root=self.tempdir)
        self.mock_check_output = self.useFixture(
            MockPatch("subprocess.check_output")
        ).mock
        self.logger = BufferLogger()

    def _runScript(self, branch_names):
        script = SyncBranchesScript(
            "sync-branches", test_args=branch_names, logger=self.logger
        )
        script.main()

    def test_unknown_branch(self):
        branch = self.factory.makeBranch()
        self._runScript(
            [branch.unique_name, branch.unique_name + "-nonexistent"]
        )
        self.assertIn(
            "WARNING Branch %s-nonexistent does not exist\n"
            % (branch.unique_name),
            self.logger.getLogBuffer(),
        )
        # Other branches are synced anyway.
        self.assertThat(branch, BranchDirectoryCreated())
        self.assertThat(
            self.mock_check_output.call_args_list,
            MatchesListwise(
                [
                    BranchSyncProcessMatches(branch),
                ]
            ),
        )

    def test_too_many_branches(self):
        branches = [self.factory.makeBranch() for _ in range(36)]
        self.assertRaisesWithContent(
            LaunchpadScriptFailure,
            "Refusing to rsync more than 35 branches",
            self._runScript,
            [branch.unique_name for branch in branches],
        )
        for branch in branches:
            self.assertThat(branch, Not(BranchDirectoryCreated()))
        self.assertEqual([], self.mock_check_output.call_args_list)

    def test_branch_storage_missing(self):
        branches = [self.factory.makeBranch() for _ in range(2)]
        branch_paths = [branch_id_to_path(branch.id) for branch in branches]

        def check_output_side_effect(args, **kwargs):
            if "%s/%s/" % (self.tempdir, branch_paths[0]) in args:
                raise subprocess.CalledProcessError(
                    23,
                    args,
                    output=(
                        'rsync: change_dir "/%s" (in mirrors) failed: '
                        "No such file or directory (2)" % branch_paths[0]
                    ),
                )
            else:
                return None

        self.mock_check_output.side_effect = check_output_side_effect
        self._runScript([branch.unique_name for branch in branches])
        branch_displays = [
            "%s (%s)" % (branch.identity, branch_path)
            for branch, branch_path in zip(branches, branch_paths)
        ]
        self.assertEqual(
            dedent(
                """\
                INFO There are 2 branches to rsync
                WARNING Branch {} not found, ignoring
                INFO Rsynced {}
                """
            ).format(*branch_displays),
            self.logger.getLogBuffer(),
        )
        self.assertThat(
            branches,
            MatchesListwise([BranchDirectoryCreated() for _ in branches]),
        )
        self.assertThat(
            self.mock_check_output.call_args_list,
            MatchesListwise(
                [BranchSyncProcessMatches(branch) for branch in branches]
            ),
        )

    def test_branch_other_rsync_error(self):
        branch = self.factory.makeBranch()
        self.mock_check_output.side_effect = subprocess.CalledProcessError(
            1, [], output="rsync exploded\n"
        )
        self.assertRaisesWithContent(
            LaunchpadScriptFailure,
            "There was an error running: "
            "rsync -a --delete-after "
            "bazaar.lp.internal::mirrors/{}/ {}/{}/\n"
            "Status: 1\n"
            "Output: rsync exploded".format(
                branch_id_to_path(branch.id),
                self.tempdir,
                branch_id_to_path(branch.id),
            ),
            self._runScript,
            [branch.unique_name],
        )
        self.assertThat(branch, BranchDirectoryCreated())
        self.assertThat(
            self.mock_check_output.call_args_list,
            MatchesListwise([BranchSyncProcessMatches(branch)]),
        )

    def test_success(self):
        branches = [self.factory.makeBranch() for _ in range(3)]
        branch_paths = [branch_id_to_path(branch.id) for branch in branches]
        self._runScript([branch.unique_name for branch in branches])
        branch_displays = [
            "%s (%s)" % (branch.identity, branch_path)
            for branch, branch_path in zip(branches, branch_paths)
        ]
        self.assertEqual(
            dedent(
                """\
                INFO There are 3 branches to rsync
                INFO Rsynced {}
                INFO Rsynced {}
                INFO Rsynced {}
                """
            ).format(*branch_displays),
            self.logger.getLogBuffer(),
        )
        self.assertThat(
            branches,
            MatchesListwise([BranchDirectoryCreated() for _ in branches]),
        )
        self.assertThat(
            self.mock_check_output.call_args_list,
            MatchesListwise(
                [BranchSyncProcessMatches(branch) for branch in branches]
            ),
        )
