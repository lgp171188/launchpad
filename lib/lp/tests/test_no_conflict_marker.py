# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test that no files in the tree has spurious conflicts markers."""

__metaclass__ = type

import os
import subprocess
import unittest


class NoSpuriousConflictsMarkerTest(unittest.TestCase):
    """Check each file in the working tree for spurious conflicts markers."""

    # We do not check for ======= because it might match some
    # old heading style in some doctests.
    CONFLICT_MARKER_RE = r'^\(<<<<<<< TREE\|>>>>>>> MERGE-SOURCE\)$'

    # We could use bzrlib.workingtree for that test, but this cause
    # problems when the system bzr (so the developer's branch) isn't at
    # the same level than the bzrlib included in our tree. Anyway, it's
    # probably faster to use grep.
    def test_noSpuriousConflictsMarker(self):
        """Fail if any spurious conflicts markers are found."""
        root_dir = os.path.join(os.path.dirname(__file__), '../../..')

        # We need to reset PYTHONPATH here, otherwise the bzr in our tree
        # will be picked up.
        new_env = dict(os.environ)
        new_env['PYTHONPATH'] = ''
        list_files = subprocess.Popen(
            ['bzr', 'ls', '-R', '--versioned'],
            stdout=subprocess.PIPE, cwd=root_dir, env=new_env)
        grep = subprocess.Popen(
            ['xargs', 'grep', '-s', self.CONFLICT_MARKER_RE],
            stdin=list_files.stdout, stdout=subprocess.PIPE, cwd=root_dir)
        out = grep.communicate()[0]
        self.assertFalse(
            len(out), 'Found spurious conflicts marker:\n%s' % out)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(NoSpuriousConflictsMarkerTest))
    return suite


if __name__ == '__main__':
    unittest.main()
