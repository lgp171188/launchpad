# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "find_lp_scripts",
]


import os

import lp

LP_TREE = os.path.dirname(os.path.dirname(os.path.dirname(lp.__file__)))


SCRIPT_LOCATIONS = [
    "cronscripts",
    "scripts",
]


def find_lp_scripts():
    """Find all scripts/ and cronscripts/ files in the current tree.

    Skips filename starting with '_' or not ending with '.py' or
    listed in the KNOWN_BROKEN blacklist.
    """
    scripts = []
    for script_location in SCRIPT_LOCATIONS:
        location = os.path.join(LP_TREE, script_location)
        for path, dirs, filenames in os.walk(location):
            for filename in filenames:
                script_path = os.path.join(path, filename)
                if filename.startswith("_") or not filename.endswith(".py"):
                    continue
                scripts.append(script_path)
    return sorted(scripts)
