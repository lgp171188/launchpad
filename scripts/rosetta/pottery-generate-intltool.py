#!/usr/bin/python3 -S
#
# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Print a list of directories that contain a valid intltool structure."""

import _pythonpath  # noqa: F401

import os.path

from lpbuildd.pottery.intltool import generate_pots
from lpbuildd.tests.fakebuilder import (
    UncontainedBackend as _UncontainedBackend,
)

from lp.services.scripts.base import LaunchpadScript


class UncontainedBackend(_UncontainedBackend):
    """Like UncontainedBackend, except avoid executing "test".

    Otherwise we can end up with confusion between the Unix "test" utility
    and Launchpad's bin/test.
    """

    def path_exists(self, path):
        """See `Backend`."""
        return os.path.exists(path)

    def isdir(self, path):
        """See `Backend`."""
        return os.path.isdir(path)

    def islink(self, path):
        """See `Backend`."""
        return os.path.islink(path)


class PotteryGenerateIntltool(LaunchpadScript):
    """Print a list of directories that contain a valid intltool structure."""

    def add_my_options(self):
        """See `LaunchpadScript`."""
        self.parser.usage = "%prog [options] [PATH]"

    def main(self):
        """See `LaunchpadScript`."""
        path = self.args[0] if self.args else "."
        backend = UncontainedBackend("dummy")
        print("\n".join(generate_pots(backend, path)))


if __name__ == "__main__":
    script = PotteryGenerateIntltool(name="pottery-generate-intltool")
    script.run()
