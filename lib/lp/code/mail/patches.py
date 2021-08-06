# This file was partially cloned from breezy 3.0.0 (breezy.patches) and
# customised for LP.
#
# Copyright (C) 2005-2010 Aaron Bentley, Canonical Ltd
# <aaron.bentley@utoronto.ca>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import re

from breezy.patches import (
    binary_files_re,
    hunk_from_header,
    parse_patch,
    )


def iter_file_patch(iter_lines, allow_dirty=False, keep_dirty=False):
    '''
    :arg iter_lines: iterable of lines to parse for patches
    :kwarg allow_dirty: If True, allow comments and other non-patch text
        before the first patch.  Note that the algorithm here can only find
        such text before any patches have been found.  Comments after the
        first patch are stripped away in iter_hunks() if it is also passed
        allow_dirty=True.  Default False.
    '''
    # FIXME: Docstring is not quite true.  We allow certain comments no
    # matter what, If they startwith '===', '***', or '#' Someone should
    # reexamine this logic and decide if we should include those in
    # allow_dirty or restrict those to only being before the patch is found
    # (as allow_dirty does).
    regex = re.compile(binary_files_re)
    saved_lines = []
    dirty_head = []
    orig_range = 0
    beginning = True
    in_git_patch = False

    dirty_headers = (b'=== ', b'diff ', b'index ')
    for line in iter_lines:
        # preserve bzr modified/added headers and blank lines
        if line.startswith(dirty_headers) or not line.strip(b'\n'):
            if len(saved_lines) > 0:
                if keep_dirty and len(dirty_head) > 0:
                    yield {'saved_lines': saved_lines,
                           'dirty_head': dirty_head}
                    dirty_head = []
                else:
                    yield saved_lines
                in_git_patch = False
                saved_lines = []
            if line.startswith(b'diff --git'):
                in_git_patch = True
            dirty_head.append(line)
            continue
        if in_git_patch and line and line[:1].islower():
            # Extended header line in a git diff.  All extended header lines
            # currently start with a lower-case character, and nothing else
            # in the patch before the next "diff" header line can do so.
            dirty_head.append(line)
            continue
        if line.startswith(b'*** '):
            continue
        if line.startswith(b'#'):
            continue
        elif orig_range > 0:
            if line.startswith(b'-') or line.startswith(b' '):
                orig_range -= 1
        elif line.startswith(b'--- ') or regex.match(line):
            if allow_dirty and beginning:
                # Patches can have "junk" at the beginning
                # Stripping junk from the end of patches is handled when we
                # parse the patch
                beginning = False
            elif len(saved_lines) > 0:
                if keep_dirty and len(dirty_head) > 0:
                    yield {'saved_lines': saved_lines,
                           'dirty_head': dirty_head}
                    dirty_head = []
                else:
                    yield saved_lines
                in_git_patch = False
            saved_lines = []
        elif line.startswith(b'@@'):
            hunk = hunk_from_header(line)
            orig_range = hunk.orig_range
        saved_lines.append(line)
    if len(saved_lines) > 0:
        if keep_dirty and len(dirty_head) > 0:
            yield {'saved_lines': saved_lines,
                   'dirty_head': dirty_head}
        else:
            yield saved_lines


def parse_patches(iter_lines, allow_dirty=False, keep_dirty=False):
    '''
    :arg iter_lines: iterable of lines to parse for patches
    :kwarg allow_dirty: If True, allow text that's not part of the patch at
        selected places.  This includes comments before and after a patch
        for instance.  Default False.
    :kwarg keep_dirty: If True, returns a dict of patches with dirty headers.
        Default False.
    '''
    for patch_lines in iter_file_patch(iter_lines, allow_dirty, keep_dirty):
        if 'dirty_head' in patch_lines:
            yield {
                'patch': parse_patch(patch_lines['saved_lines'], allow_dirty),
                'dirty_head': patch_lines['dirty_head'],
                }
        else:
            yield parse_patch(patch_lines, allow_dirty)
