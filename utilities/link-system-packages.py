#! /usr/bin/python2

# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Link system-installed Python modules into Launchpad's virtualenv."""

from __future__ import absolute_import, print_function, unicode_literals

from argparse import ArgumentParser
from distutils.sysconfig import get_python_lib
import importlib
import os.path
import re


def link_module(name, virtualenv_libdir, optional=False):
    try:
        module = importlib.import_module(name)
    except ImportError:
        if optional:
            print("Skipping missing optional module %s." % name)
            return
        else:
            raise
    path = module.__file__
    if os.path.basename(path).startswith("__init__."):
        path = os.path.dirname(path)
    system_libdir = get_python_lib(plat_specific=path.endswith(".so"))
    if os.path.commonprefix([path, system_libdir]) != system_libdir:
        raise RuntimeError(
            "%s imported from outside %s (%s)" % (name, system_libdir, path))
    target_path = os.path.join(
        virtualenv_libdir, os.path.relpath(path, system_libdir))
    if os.path.lexists(target_path) and os.path.islink(target_path):
        os.unlink(target_path)
    os.symlink(path, target_path)


def main():
    parser = ArgumentParser()
    parser.add_argument("virtualenv_libdir")
    parser.add_argument("module_file", type=open)
    args = parser.parse_args()

    for line in args.module_file:
        line = re.sub(r"#.*", "", line).strip()
        if not line:
            continue
        if line.endswith("?"):
            line = line[:-1]
            optional = True
        else:
            optional = False
        link_module(line, args.virtualenv_libdir, optional=optional)


if __name__ == "__main__":
    main()
