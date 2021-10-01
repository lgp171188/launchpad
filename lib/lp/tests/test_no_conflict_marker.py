# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test that no files in the tree has spurious conflicts markers."""

import os
import subprocess
import unittest


class NoSpuriousConflictsMarkerTest(unittest.TestCase):
    """Check each file in the working tree for spurious conflicts markers."""

    # We do not check for ======= because it might match some
    # old heading style in some doctests.
    CONFLICT_MARKER_RE = r'^\(<<<<<<< \|>>>>>>> \)'

    # XXX cjwatson 2019-09-25: It may be simpler to use something based on
    # "git diff --check", but we'd need to work out what to do about its
    # whitespace checks.
    def test_noSpuriousConflictsMarker(self):
        """Fail if any spurious conflicts markers are found."""
        root_dir = os.path.join(os.path.dirname(__file__), '../../..')

        list_files = subprocess.Popen(
            ['git', 'ls-files'], stdout=subprocess.PIPE, cwd=root_dir)
        unique_files = subprocess.Popen(
            ['sort', '-u'],
            stdin=list_files.stdout, stdout=subprocess.PIPE)
        grep = subprocess.Popen(
            ['xargs', 'grep', '-s', self.CONFLICT_MARKER_RE],
            stdin=unique_files.stdout, stdout=subprocess.PIPE, cwd=root_dir)
        out = grep.communicate()[0]
        self.assertFalse(
            len(out), 'Found spurious conflicts marker:\n%s' % out)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(NoSpuriousConflictsMarkerTest))
    return suite


if __name__ == '__main__':
    unittest.main()
