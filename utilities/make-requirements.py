#! /usr/bin/python3

# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Build a pip constraints file from inputs."""

import logging
from argparse import ArgumentParser
from collections import defaultdict
from configparser import ConfigParser

from pkg_resources import parse_requirements


def read_buildout_versions(path):
    """Parse versions from a buildout configuration file into requirements.

    This isn't intended to parse everything buildout can do, but just enough
    to parse Zope Toolkit versions files.  Note that these are treated as
    constraints (`pip install -c`) rather than requirements (`pip install
    -r`), because we don't use the whole Zope Toolkit.
    """
    parser = ConfigParser()
    parser.optionxform = str
    parser.read(path)
    versions = defaultdict(dict)
    for section in parser.sections():
        if section == "versions":
            python_version = None
        elif section.startswith("versions:python"):
            python_suffix = section[len("versions:python") :]
            if len(python_suffix) == 1 and python_suffix.isdigit():
                python_version = "%s.*" % python_suffix
            elif len(python_suffix) == 2 and python_suffix.isdigit():
                python_version = "%s.%s.*" % tuple(python_suffix)
            else:
                raise ValueError("Unhandled section: %s" % section)
        else:
            raise ValueError("Unhandled section: %s" % section)
        for name in parser.options(section):
            versions[name][python_version] = parser.get(section, name)
    requirements = []
    for name in sorted(versions):
        python_versions = list(versions[name])
        if python_versions == [None]:
            requirements.append("%s==%s" % (name, versions[name][None]))
        else:
            for python_version in python_versions:
                if python_version is None:
                    continue
                requirements.append(
                    '%s==%s; python_version == "%s"'
                    % (name, versions[name][python_version], python_version)
                )
            if None in python_versions:
                marker = " and ".join(
                    'python_version != "%s"' % python_version
                    for python_version in python_versions
                    if python_version is not None
                )
                requirements.append(
                    "%s==%s; %s" % (name, versions[name][None], marker)
                )
    return list(parse_requirements(requirements))


def read_requirements(path):
    """Parse a PEP 508 requirements file."""
    with open(path) as f:
        return list(parse_requirements(f))


def write_requirements(include_requirements, exclude_requirements):
    """Write a combined requirements file to stdout."""
    combined = {}
    for requirements in include_requirements:
        by_key = defaultdict(list)
        for requirement in requirements:
            by_key[requirement.key].append(requirement)
        for key in by_key:
            if by_key[key] == combined.get(key):
                logging.warning("Duplicate requirement found: %s", by_key[key])
        combined.update(by_key)
    for requirements in exclude_requirements:
        for requirement in requirements:
            if requirement.key in combined:
                del combined[requirement.key]

    print("# THIS IS AN AUTOGENERATED FILE; DO NOT EDIT DIRECTLY.")
    for key in sorted(combined):
        for requirement in combined[key]:
            print(requirement)


def main():
    parser = ArgumentParser()
    parser.add_argument(
        "--buildout",
        action="append",
        metavar="VERSIONS",
        help="Include requirements from this buildout versions file",
    )
    parser.add_argument(
        "--include",
        action="append",
        metavar="REQUIREMENTS",
        help="Include requirements from this PEP 508 requirements file",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        metavar="REQUIREMENTS",
        help="Exclude requirements from this PEP 508 requirements file",
    )
    args = parser.parse_args()

    include_requirements = [
        read_buildout_versions(path) for path in args.buildout
    ] + [read_requirements(path) for path in args.include]
    exclude_requirements = [read_requirements(path) for path in args.exclude]

    write_requirements(include_requirements, exclude_requirements)


if __name__ == "__main__":
    main()
