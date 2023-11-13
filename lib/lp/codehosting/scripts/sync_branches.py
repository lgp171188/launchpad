# Copyright 2007-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Sync branches from production to a staging environment."""

__all__ = ["SyncBranchesScript"]

import os.path
import subprocess
from shlex import quote as shell_quote

from zope.component import getUtility

from lp.code.interfaces.branch import IBranchSet
from lp.codehosting.vfs import branch_id_to_path
from lp.services.config import config
from lp.services.scripts.base import LaunchpadScript, LaunchpadScriptFailure

# We don't want to spend too long syncing branches.
BRANCH_LIMIT = 35


class SyncBranchesScript(LaunchpadScript):
    """Sync branches from production to a staging environment."""

    usage = "%prog [options] BRANCH_NAME [...]"
    description = (
        __doc__
        + "\n"
        + (
            "Branch names may be given in any of the forms accepted for lp: "
            'URLs, but without the leading "lp:".'
        )
    )

    def _syncBranch(self, branch):
        branch_path = branch_id_to_path(branch.id)
        branch_dir = os.path.join(
            config.codehosting.mirrored_branches_root, branch_path
        )
        if not os.path.exists(branch_dir):
            os.makedirs(branch_dir)
        args = [
            "rsync",
            "-a",
            "--delete-after",
            "%s/%s/" % (config.codehosting.sync_branches_source, branch_path),
            "%s/" % branch_dir,
        ]
        try:
            subprocess.check_output(args, universal_newlines=True)
        except subprocess.CalledProcessError as e:
            if "No such file or directory" in e.output:
                self.logger.warning(
                    "Branch %s (%s) not found, ignoring",
                    branch.identity,
                    branch_path,
                )
            else:
                raise LaunchpadScriptFailure(
                    "There was an error running: %s\n"
                    "Status: %s\n"
                    "Output: %s"
                    % (
                        " ".join(shell_quote(arg) for arg in args),
                        e.returncode,
                        e.output.rstrip("\n"),
                    )
                )
        else:
            self.logger.info("Rsynced %s (%s)", branch.identity, branch_path)

    def main(self):
        branches = []
        for branch_name in self.args:
            branch = getUtility(IBranchSet).getByPath(branch_name)
            if branch is not None:
                branches.append(branch)
            else:
                self.logger.warning("Branch %s does not exist", branch_name)

        self.logger.info("There are %d branches to rsync", len(branches))

        if len(branches) > BRANCH_LIMIT:
            raise LaunchpadScriptFailure(
                "Refusing to rsync more than %d branches" % BRANCH_LIMIT
            )

        for branch in branches:
            self._syncBranch(branch)
