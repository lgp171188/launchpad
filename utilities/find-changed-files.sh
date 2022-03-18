#!/bin/bash
#
# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
#
# Determine the changed files in the working tree, or if the working tree is
# clean then the changed files relative to the parent branch.

set -e
set -o pipefail

if [ ! -e .git ]; then
    echo "Not in a Git working tree" >&2
    exit 1
fi

git_diff_files() {
    git diff --name-only -z "$@" | perl -l -0 -ne '
        # Only show paths that exist and are not symlinks.
        print if -e and not -l'
}

files=$(git_diff_files HEAD)
if [ -z "$files" ]; then
    # git doesn't give us a way to track the parent branch, so just use
    # master by default and let the user override that using a
    # positional argument.
    files=$(git_diff_files "${1:-master}")
fi

echo "$files"
