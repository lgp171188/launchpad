#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

"""
A copy of `cve_lib` module from `ubuntu-cve-tracker`
(only the code for parsing CVE files).
"""
import codecs
import glob
import math
import os
import re
import sys
from collections import OrderedDict

import yaml

GLOBAL_TAGS_KEY = "*"


def set_cve_dir(path):
    """Return a path with CVEs in it. Specifically:
    - if 'path' has CVEs in it, return path
    - if 'path' is a relative directory with no CVEs, see if UCT is defined
      and if so, see if 'UCT/path' has CVEs in it and return path
    """
    p = path
    found = False
    if len(glob.glob("%s/CVE-*" % path)) > 0:
        found = True
    elif not path.startswith("/") and "UCT" in os.environ:
        tmp = os.path.join(os.environ["UCT"], path)
        if len(glob.glob("%s/CVE-*" % tmp)) > 0:
            found = True
            p = tmp
            # print("INFO: using '%s'" % p, file=sys.stderr)

    if not found:
        print(
            "WARN: could not find CVEs in '%s' (or relative to UCT)" % path,
            file=sys.stderr,
        )
    return p


if "UCT" in os.environ:
    subprojects_dir = os.environ["UCT"] + "/subprojects"
else:
    subprojects_dir = "subprojects"

PRODUCT_UBUNTU = "ubuntu"

# common to all scripts
# these get populated by the contents of subprojects defined below
all_releases = []
eol_releases = []
external_releases = []
releases = []
devel_release = ""

# known subprojects which are supported by cve_lib - in general each
# subproject is defined by the combination of a product and series as
# <product/series>.
#
# For each subproject, it is either internal (ie is part of this static
# dict) or external (found dynamically at runtime by
# load_external_subprojects()).
#
# eol specifies whether the subproject is now end-of-life.  packages
# specifies list of files containing the names of supported packages for the
# subproject. alias defines an alternate preferred name for the subproject
# (this is often used to support historical names for projects etc).
subprojects = {
    "bluefield/jammy": {
        "eol": False,
        "oval": True,
        "packages": ["bluefield-jammy-supported.txt"],
        "name": "Ubuntu 22.04 LTS for NVIDIA BlueField",
        "codename": "Jammy Jellyfish",
        "ppas": [
                 {"ppa": "canonical-kernel-bluefield/release", "pocket": "release"}
                ],
        "parent": "ubuntu/jammy",
        "description": "Available for NVIDIA BlueField platforms",
    },
    "stable-phone-overlay/vivid": {
        "eol": True,
        "packages": ["vivid-stable-phone-overlay-supported.txt"],
        "name": "Ubuntu Touch 15.04",
        "alias": "vivid/stable-phone-overlay",
    },
    "ubuntu-core/vivid": {
        "eol": True,
        "packages": ["vivid-ubuntu-core-supported.txt"],
        "name": "Ubuntu Core 15.04",
        "alias": "vivid/ubuntu-core",
    },
    "esm/precise": {
        "eol": True,
        "packages": ["precise-esm-supported.txt"],
        "name": "Ubuntu 12.04 ESM",
        "codename": "Precise Pangolin",
        "alias": "precise/esm",
        "ppas": [{ "ppa": "ubuntu-esm/esm", "pocket": "security"}],
        "parent": "ubuntu/precise",
        "description": "Available with UA Infra or UA Desktop: https://ubuntu.com/advantage",
        "stamp": 1493521200,
    },
    "esm/trusty": {
        "eol": False,
        "oval": True,
        "packages": ["trusty-esm-supported.txt"],
        "name": "Ubuntu 14.04 LTS",
        "codename": "Trusty Tahr",
        "alias": "trusty/esm",
        "ppas": [
                 {"ppa": "ubuntu-esm/esm-infra-security", "pocket": "security"},
                 {"ppa": "ubuntu-esm/esm-infra-updates",  "pocket": "updates"}
                ],
        "parent": "ubuntu/trusty",
        "description": "Available with Ubuntu Pro (Infra-only): https://ubuntu.com/pro",
        "stamp": 1556593200,
    },
    "esm-infra/xenial": {
        "eol": False,
        "oval": True,
        "components": ["main", "restricted"],
        "packages": ["esm-infra-xenial-supported.txt"],
        "name": "Ubuntu 16.04 LTS",
        "codename": "Xenial Xerus",
        "ppas": [
                 {"ppa": "ubuntu-esm/esm-infra-security", "pocket": "security"},
                 {"ppa": "ubuntu-esm/esm-infra-updates",  "pocket": "updates"}
                ],
        "parent": "ubuntu/xenial",
        "description": "Available with Ubuntu Pro (Infra-only): https://ubuntu.com/pro",
        "stamp": 1618963200,
    },
    "esm-infra/bionic": {
        "eol": False,
        "oval": True,
        "components": ["main", "restricted"],
        "packages": ["esm-infra-bionic-supported.txt"],
        "name": "Ubuntu 18.04 LTS",
        "codename": "Bionic Beaver",
        "ppas": [
                 {"ppa": "ubuntu-esm/esm-infra-security", "pocket": "security"},
                 {"ppa": "ubuntu-esm/esm-infra-updates",  "pocket": "updates"}
                ],
        "parent": "ubuntu/bionic",
        "description": "Available with Ubuntu Pro (Infra-only): https://ubuntu.com/pro",
        "stamp": 1685539024,
    },
    "esm-infra-legacy/trusty": {
        "eol": False,
        "oval": False, #TODO: Change to True when we are ready for generating data
        "packages": ["esm-infra-legacy-trusty-supported.txt"],
        "name": "Ubuntu 14.04 LTS",
        "codename": "Trusty Tahr",
        "ppas": [
                 {"ppa": "ubuntu-esm/esm-infra-legacy-security", "pocket": "security"},
                 {"ppa": "ubuntu-esm/esm-infra-legacy-updates",  "pocket": "updates"}
                ],
        "parent": "esm/trusty",
        "description": "Available with Ubuntu Pro with Legacy support add-on: https://ubuntu.com/pro",
        "stamp": None, #TODO: to be calculate when finally public
    },
    "esm-apps/xenial": {
        "eol": False,
        "oval": True,
        "components": ["universe", "multiverse"],
        "packages": ["esm-apps-xenial-supported.txt"],
        "name": "Ubuntu 16.04 LTS",
        "codename": "Xenial Xerus",
        "ppas": [
                 {"ppa": "ubuntu-esm/esm-apps-security", "pocket": "security"},
                 {"ppa": "ubuntu-esm/esm-apps-updates",  "pocket": "updates"}
                ],
        "parent": "esm-infra/xenial",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
        "stamp": 1618963200,
    },
    "esm-apps/bionic": {
        "eol": False,
        "oval": True,
        "components": ["universe", "multiverse"],
        "packages": ["esm-apps-bionic-supported.txt"],
        "name": "Ubuntu 18.04 LTS",
        "codename": "Bionic Beaver",
        "ppas": [
                 {"ppa": "ubuntu-esm/esm-apps-security", "pocket": "security"},
                 {"ppa": "ubuntu-esm/esm-apps-updates",  "pocket": "updates"}
                ],
        "parent": "esm-infra/bionic",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
        "stamp": 1524870000,
    },
    "esm-apps/focal": {
        "eol": False,
        "oval": True,
        "components": ["universe", "multiverse"],
        "packages": ["esm-apps-focal-supported.txt"],
        "name": "Ubuntu 20.04 LTS",
        "codename": "Focal Fossa",
        "ppas": [
                 {"ppa": "ubuntu-esm/esm-apps-security", "pocket": "security"},
                 {"ppa": "ubuntu-esm/esm-apps-updates",  "pocket": "updates"}
                ],
        "parent": "ubuntu/focal",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
        "stamp": 1587567600,
    },
    "esm-apps/jammy": {
        "eol": False,
        "oval": True,
        "components": ["universe", "multiverse"],
        "packages": ["esm-apps-jammy-supported.txt"],
        "name": "Ubuntu 22.04 LTS",
        "codename": "Jammy Jellyfish",
        "ppas": [
                 {"ppa": "ubuntu-esm/esm-apps-security", "pocket": "security"},
                 {"ppa": "ubuntu-esm/esm-apps-updates",  "pocket": "updates"}
                ],
        "parent": "ubuntu/jammy",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
        "stamp": 1650693600,
    },
    "esm-apps/noble": {
        "eol": False,
        "oval": True,
        "components": ["universe", "multiverse"],
        "packages": ["esm-apps-noble-supported.txt"],
        "name": "Ubuntu 24.04 LTS",
        "codename": "Noble Numbat",
        "ppas": [
                 {"ppa": "ubuntu-esm/esm-apps-security", "pocket": "security"},
                 {"ppa": "ubuntu-esm/esm-apps-updates",  "pocket": "updates"}
                ],
        "parent": "ubuntu/noble",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
        "stamp": 1714060800,
    },
    "fips/xenial": {
        "eol": False,
        "oval": True,
        "packages": ["fips-xenial-supported.txt"],
        "name": "Ubuntu 16.04 FIPS Certified",
        "codename": "Xenial Xerus",
        "ppas": [{"ppa" : "ubuntu-advantage/fips", "pocket": "security"}],
        "parent": "ubuntu/xenial",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
    },
    "fips/bionic": {
        "eol": False,
        "oval": True,
        "packages": ["fips-bionic-supported.txt"],
        "name": "Ubuntu 18.04 FIPS Certified",
        "codename": "Bionic Beaver",
        "ppas": [{"ppa" : "ubuntu-advantage/fips", "pocket": "security"}],
        "parent": "ubuntu/bionic",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
    },
    "fips/focal": {
        "eol": False,
        "oval": True,
        "packages": ["fips-focal-supported.txt"],
        "name": "Ubuntu 20.04 FIPS Certified",
        "codename": "Focal Fossa",
        "ppas": [{"ppa" : "ubuntu-advantage/fips", "pocket": "security"}],
        "parent": "ubuntu/focal",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
    },
    "fips-updates/xenial": {
        "eol": False,
        "oval": True,
        "packages": ["fips-updates-xenial-supported.txt"],
        "name": "Ubuntu 16.04 FIPS Compliant",
        "codename": "Xenial Xerus",
        "ppas": [{"ppa" : "ubuntu-advantage/fips-updates", "pocket": "updates"}],
        "parent": "ubuntu/xenial",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
    },
    "fips-updates/bionic": {
        "eol": False,
        "oval": True,
        "packages": ["fips-updates-bionic-supported.txt"],
        "name": "Ubuntu 18.04 FIPS Compliant",
        "codename": "Bionic Beaver",
        "ppas": [{"ppa" : "ubuntu-advantage/fips-updates", "pocket": "updates"}],
        "parent": "ubuntu/bionic",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
    },
    "fips-updates/focal": {
        "eol": False,
        "oval": True,
        "packages": ["fips-updates-focal-supported.txt"],
        "name": "Ubuntu 20.04 FIPS Compliant",
        "codename": "Focal Fossa",
        "ppas": [{"ppa" : "ubuntu-advantage/fips-updates", "pocket": "updates"}],
        "parent": "ubuntu/focal",
        "description": "Available with Ubuntu Pro: https://ubuntu.com/pro",
    },
    "ros-esm/kinetic": {
        "eol": False,
        "oval": False,
        "packages": ["ros-esm-xenial-kinetic-supported.txt"],
        "name": "Ubuntu 16.04 ROS ESM",
        "codename": "Xenial Xerus",
        "alias": "ros-esm/xenial",
        "ppas": [{"ppa": "ubuntu-robotics-packagers/ros-security", "pocket": "security"}],
        "parent": "ubuntu/xenial",
        "description": "Available with Ubuntu Advantage: https://ubuntu.com/advantage",
    },
    "ros-esm/melodic": {
        "eol": False,
        "oval": False,
        "packages": ["ros-esm-bionic-melodic-supported.txt"],
        "name": "Ubuntu 18.04 ROS ESM",
        "codename": "Bionic Beaver",
        "alias": "ros-esm/bionic",
        "ppas": [{"ppa": "ubuntu-robotics-packagers/ros-security", "pocket": "security"}],
        "parent": "ubuntu/bionic",
        "description": "Available with Ubuntu Advantage: https://ubuntu.com/advantage",
    },
    "ubuntu/warty": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 4.10",
        "version": 4.10,
        "codename": "Warty Warthog",
        "alias": "warty",
        "description": "Interim Release",
        "stamp": 1098748800,
    },
    "ubuntu/hoary": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 5.04",
        "version": 5.04,
        "codename": "Hoary Hedgehog",
        "alias": "hoary",
        "description": "Interim Release",
        "stamp": 1112918400,
    },
    "ubuntu/breezy": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 5.10",
        "version": 5.10,
        "codename": "Breezy Badger",
        "alias": "breezy",
        "description": "Interim Release",
        "stamp": 1129075200,
    },
    "ubuntu/dapper": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 6.06 LTS",
        "version": 6.06,
        "codename": "Dapper Drake",
        "alias": "dapper",
        "description": "Long Term Support",
        "stamp": 1149120000,
    },
    "ubuntu/edgy": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 6.10",
        "version": 6.10,
        "codename": "Edgy Eft",
        "alias": "edgy",
        "description": "Interim Release",
        "stamp": 1161864000,
    },
    "ubuntu/feisty": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 7.04",
        "version": 7.04,
        "codename": "Feisty Fawn",
        "alias": "feisty",
        "description": "Interim Release",
        "stamp": 1176984000,
    },
    "ubuntu/gutsy": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 7.10",
        "version": 7.10,
        "codename": "Gutsy Gibbon",
        "alias": "gutsy",
        "description": "Interim Release",
        "stamp": 1192708800,
    },
    "ubuntu/hardy": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 8.04 LTS",
        "version": 8.04,
        "codename": "Hardy Heron",
        "alias": "hardy",
        "description": "Long Term Support",
        "stamp": 1209038400,
    },
    "ubuntu/intrepid": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 8.10",
        "version": 8.10,
        "codename": "Intrepid Ibex",
        "alias": "intrepid",
        "description": "Interim Release",
        "stamp": 1225368000,
    },
    "ubuntu/jaunty": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 9.04",
        "version": 9.04,
        "codename": "Jaunty Jackalope",
        "alias": "jaunty",
        "description": "Interim Release",
        "stamp": 1240488000,
    },
    "ubuntu/karmic": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 9.10",
        "version": 9.10,
        "codename": "Karmic Koala",
        "alias": "karmic",
        "description": "Interim Release",
        "stamp": 1256817600,
    },
    "ubuntu/lucid": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 10.04 LTS",
        "version": 10.04,
        "codename": "Lucid Lynx",
        "alias": "lucid",
        "description": "Long Term Support",
        "stamp": 1272565800,
    },
    "ubuntu/maverick": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 10.10",
        "version": 10.10,
        "codename": "Maverick Meerkat",
        "alias": "maverick",
        "description": "Interim Release",
        "stamp": 1286706600,
    },
    "ubuntu/natty": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 11.04",
        "version": 11.04,
        "codename": "Natty Narwhal",
        "alias": "natty",
        "description": "Interim Release",
        "stamp": 1303822800,
    },
    "ubuntu/oneiric": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 11.10",
        "version": 11.10,
        "codename": "Oneiric Ocelot",
        "alias": "oneiric",
        "description": "Interim Release",
        "stamp": 1318446000,
    },
    "ubuntu/precise": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 12.04 LTS",
        "version": 12.04,
        "codename": "Precise Pangolin",
        "alias": "precise",
        "description": "Long Term Support",
        "stamp": 1335423600,
    },
    "ubuntu/quantal": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 12.10",
        "version": 12.10,
        "codename": "Quantal Quetzal",
        "alias": "quantal",
        "description": "Interim Release",
        "stamp": 1350547200,
    },
    "ubuntu/raring": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 13.04",
        "version": 13.04,
        "codename": "Raring Ringtail",
        "alias": "raring",
        "description": "Interim Release",
        "stamp": 1366891200,
    },
    "ubuntu/saucy": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 13.10",
        "version": 13.10,
        "codename": "Saucy Salamander",
        "alias": "saucy",
        "description": "Interim Release",
        "stamp": 1381993200,
    },
    "ubuntu/trusty": {
        "eol": True,
        "oval": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 14.04 LTS",
        "version": 14.04,
        "codename": "Trusty Tahr",
        "alias": "trusty",
        "description": "Long Term Support",
        "stamp": 1397826000,
    },
    "ubuntu/utopic": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 14.10",
        "version": 14.10,
        "codename": "Utopic Unicorn",
        "alias": "utopic",
        "description": "Interim Release",
        "stamp": 1414083600,
    },
    "ubuntu/vivid": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 15.04",
        "version": 15.04,
        "codename": "Vivid Vervet",
        "alias": "vivid",
        "description": "Interim Release",
        "stamp": 1429027200,
    },
    "ubuntu/wily": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 15.10",
        "version": 15.10,
        "codename": "Wily Werewolf",
        "alias": "wily",
        "description": "Interim Release",
        "stamp": 1445518800,
    },
    "ubuntu/xenial": {
        "eol": True,
        "oval": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 16.04 LTS",
        "version": 16.04,
        "codename": "Xenial Xerus",
        "alias": "xenial",
        "description": "Long Term Support",
        "stamp": 1461279600,
    },
    "ubuntu/yakkety": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 16.10",
        "version": 16.10,
        "codename": "Yakkety Yak",
        "alias": "yakkety",
        "description": "Interim Release",
        "stamp": 1476518400,
    },
    "ubuntu/zesty": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 17.04",
        "version": 17.04,
        "codename": "Zesty Zapus",
        "alias": "zesty",
        "description": "Interim Release",
        "stamp": 1492153200,
    },
    "ubuntu/artful": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 17.10",
        "version": 17.10,
        "codename": "Artful Aardvark",
        "alias": "artful",
        "description": "Interim Release",
        "stamp": 1508418000,
    },
    "ubuntu/bionic": {
        "eol": True,
        "oval": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 18.04 LTS",
        "version": 18.04,
        "codename": "Bionic Beaver",
        "alias": "bionic",
        "description": "Long Term Support",
        "stamp": 1524870000,
    },
    "ubuntu/cosmic": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 18.10",
        "version": 18.10,
        "codename": "Cosmic Cuttlefish",
        "alias": "cosmic",
        "description": "Interim Release",
        "stamp": 1540040400,
    },
    "ubuntu/disco": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 19.04",
        "version": 19.04,
        "codename": "Disco Dingo",
        "alias": "disco",
        "description": "Interim Release",
        "stamp": 1555581600,
    },
    "ubuntu/eoan": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 19.10",
        "version": 19.10,
        "codename": "Eoan Ermine",
        "alias": "eoan",
        "description": "Interim Release",
        "stamp": 1571234400,
    },
    "ubuntu/focal": {
        "eol": False,
        "oval": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 20.04 LTS",
        "version": 20.04,
        "codename": "Focal Fossa",
        "alias": "focal",
        "description": "Long Term Support",
        "stamp": 1587567600,
    },
    "ubuntu/groovy": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 20.10",
        "version": 20.10,
        "codename": "Groovy Gorilla",
        "alias": "groovy",
        "description": "Interim Release",
        "stamp": 1603288800,
    },
    "ubuntu/hirsute": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 21.04",
        "version": 21.04,
        "codename": "Hirsute Hippo",
        "alias": "hirsute",
        "description": "Interim Release",
        "stamp": 1619049600,
    },
    "ubuntu/impish": {
        "eol": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 21.10",
        "version": 21.10,
        "codename": "Impish Indri",
        "alias": "impish",
        "description": "Interim Release",
        "stamp": 1634220000,
    },
    "ubuntu/jammy": {
        "eol": False,
        "oval": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 22.04 LTS",
        "version": 22.04,
        "codename": "Jammy Jellyfish",
        "alias": "jammy",
        "description": "Long Term Support",
        "stamp": 1650693600,
    },
    "ubuntu/kinetic": {
        "eol": True,
        "oval": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 22.10",
        "version": 22.10,
        "codename": "Kinetic Kudu",
        "alias": "kinetic",
        "devel": False,
        "description": "Interim Release",
        "stamp": 1666461600,
    },
    "ubuntu/lunar": {
        "eol": True,
        "oval": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 23.04",
        "version": 23.04,
        "codename": "Lunar Lobster",
        "alias": "lunar",
        "devel": False,
        "description": "Interim Release",
        "stamp": 1682431200,
    },
    "ubuntu/mantic": {
        "eol": True,
        "oval": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 23.10",
        "version": 23.10,
        "codename": "Mantic Minotaur",
        "alias": "mantic",
        "devel": False,  # there can be only one ⚔
        "description": "Interim Release",
        "stamp": 1697493600,
    },
    "ubuntu/noble": {
        "eol": False,
        "oval": True,
        "components": ["main", "restricted", "universe", "multiverse"],
        "name": "Ubuntu 24.04 LTS",
        "version": 24.04,
        "codename": "Noble Numbat",
        "alias": "noble",
        "devel": False,  # there can be only one ⚔
        "description": "Long Term Release",
        "stamp": 1714060800,
    },
   "ubuntu/oracular": {
       "eol": False,
       "oval": True,
       "components": ["main", "restricted", "universe", "multiverse"],
       "name": "Ubuntu 24.10",
       "version": 24.10,
       "codename": "Oracular Oriole",
       "alias": "oracular",
       "devel": True,  # there can be only one ⚔
       "description": "Interim Release",
   },
    "snap": {
        "eol": False,
        "oval": False,
        "packages": ["snap-supported.txt"],
    }
}


def product_series(rel):
    """Return the product,series tuple for rel."""
    series = ""
    parts = rel.split("/", 1)
    product = parts[0]
    if len(parts) == 2:
        series = parts[1]
    return product, series


# get the subproject details for rel along with
# it's canonical name, product and series
def get_subproject_details(rel):
    """Return the product,series,details tuple for rel."""
    canon, product, series, details = None, None, None, None
    try:
        details = subprojects[rel]
        product, series = product_series(rel)
        canon = product + "/" + series
    except (ValueError, KeyError):
        # look for alias
        for r in subprojects:
            try:
                if subprojects[r]["alias"] == rel:
                    product, series = product_series(r)
                    details = subprojects[r]
                    canon = product + "/" + series
                    break
            except KeyError:
                pass
            if details is not None:
                break
    return canon, product, series, details


def release_alias(rel):
    """Return the alias for rel or just rel if no alias is defined."""
    alias = rel
    _, _, _, details = get_subproject_details(rel)
    try:
        alias = details["alias"]
    except (KeyError, TypeError):
        pass
    return alias


def release_parent(rel):
    """Return the parent for rel or None if no parent is defined."""
    parent = None
    _, _, _, details = get_subproject_details(rel)
    try:
        parent = release_alias(details["parent"])
    except (KeyError, TypeError):
        pass
    return parent


def get_external_subproject_cve_dir(subproject):
    """Get the directory where CVE files are stored for the subproject.

    Get the directory where CVE files are stored for a subproject. In
    general this is within the higher level project directory, not within
    the specific subdirectory for the particular series that defines this
    subproject.

    """
    rel, product, _, _ = get_subproject_details(subproject)
    if rel not in external_releases:
        raise ValueError("%s is not an external subproject" % rel)
    # CVEs live in the product dir
    return os.path.join(subprojects_dir, product)


def get_external_subproject_dir(subproject):
    """Get the directory for the given external subproject."""
    rel, _, _, _ = get_subproject_details(subproject)
    if rel not in external_releases:
        raise ValueError("%s is not an external subproject" % rel)
    return os.path.join(subprojects_dir, rel)


def read_external_subproject_config(subproject):
    """Read and return the configuration for the given subproject."""
    sp_dir = get_external_subproject_dir(subproject)
    config_yaml = os.path.join(sp_dir, "config.yaml")
    with open(config_yaml) as cfg:
        return yaml.safe_load(cfg)


def find_files_recursive(path, name):
    """Return a list of all files under path with name."""
    matches = []
    for root, _, files in os.walk(path, followlinks=True):
        for f in files:
            if f == name:
                filepath = os.path.join(root, f)
                matches.append(filepath)
    return matches


def find_external_subproject_cves(cve):
    """
    Return the list of external subproject CVE snippets for the given CVE.
    """
    cves = []
    for rel in external_releases:
        # fallback to the series specific subdir rather than just the
        # top-level project directory even though this is preferred
        for d in [
            get_external_subproject_cve_dir(rel),
            get_external_subproject_dir(rel),
        ]:
            path = os.path.join(d, cve)
            if os.path.exists(path):
                cves.append(path)
    return cves


def load_external_subprojects():
    """Search for and load subprojects into the global subprojects dict.

    Search for and load subprojects into the global subprojects dict.

    A subproject is defined as a directory which resides within
    subprojects_dir and contains a supported.txt file. It can also contain
    a project.yml file which specifies configuration directives for the
    project as well as snippet CVE files. By convention, a subproject is
    usually defined as the combination of a product and series, ie:

    esm-apps/focal

    as such in this case there would expect to be within subprojects_dir a
    directory called esm-apps/ and within that a subdirectory called
    focal/. Inside this focal/ subdirectory a supported.txt file would list
    the packages which are supported by the esm-apps/focal subproject. By
    convention, snippet CVE files should reside within the esm-apps/
    project directory rather than the esm-apps/focal/ subdirectory to avoid
    unnecessary fragmentation across different subproject series.

    """
    for supported_txt in find_files_recursive(
        subprojects_dir, "supported.txt"
    ):
        # rel name is the path component between subprojects/ and
        # /supported.txt
        rel = supported_txt[
            len(subprojects_dir) + 1:-len("supported.txt") - 1
        ]
        external_releases.append(rel)
        subprojects.setdefault(rel, {"packages": [], "eol": False})
        # an external subproject can append to an internal one
        subprojects[rel]["packages"].append(supported_txt)
        try:
            # use config to populate other parts of the
            # subproject settings
            config = read_external_subproject_config(rel)
            subprojects[rel].setdefault("ppa", config["ppa"])
            subprojects[rel].setdefault("name", config["name"])
            subprojects[rel].setdefault("description", config["description"])
            subprojects[rel].setdefault("parent", config["parent"])
        except Exception:
            pass


load_external_subprojects()

for release in subprojects:
    details = subprojects[release]
    rel = release_alias(release)
    # prefer the alias name
    all_releases.append(rel)
    if details["eol"]:
        eol_releases.append(rel)
    if "devel" in details and details["devel"]:
        if devel_release != "":
            raise ValueError("there can be only one ⚔ devel")
        devel_release = rel
    # ubuntu specific releases
    product, series = product_series(release)
    if product == PRODUCT_UBUNTU:
        releases.append(rel)


valid_cve_tags = {
    "cisa-kev": (
        "This vulnerability is listed in the CISA Known Exploited "
        "Vulnerabilities Catalog. For more details see "
        "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
    ),
}

valid_package_tags = {
    "universe-binary": (
        "Binaries built from this source package are in universe and so are "
        "supported by the community. For more details see "
        "https://wiki.ubuntu.com/SecurityTeam/FAQ#Official_Support"
    ),
    "not-ue": (
        "This package is not directly supported by the Ubuntu Security Team"
    ),
    "apparmor": (
        "This vulnerability is mitigated in part by an AppArmor profile. "
        "For more details see "
        "https://wiki.ubuntu.com/Security/Features#apparmor"
    ),
    "stack-protector": (
        "This vulnerability is mitigated in part by the use of gcc's stack "
        "protector in Ubuntu. For more details see "
        "https://wiki.ubuntu.com/Security/Features#stack-protector"
    ),
    "fortify-source": (
        "This vulnerability is mitigated in part by the use of "
        "-D_FORTIFY_SOURCE=2 in Ubuntu. For more details see "
        "https://wiki.ubuntu.com/Security/Features#fortify-source"
    ),
    "symlink-restriction": (
        "This vulnerability is mitigated in part by the use of symlink "
        "restrictions in Ubuntu. For more details see "
        "https://wiki.ubuntu.com/Security/Features#symlink"
    ),
    "hardlink-restriction": (
        "This vulnerability is mitigated in part by the use of hardlink "
        "restrictions in Ubuntu. For more details see "
        "https://wiki.ubuntu.com/Security/Features#hardlink"
    ),
    "heap-protector": (
        "This vulnerability is mitigated in part by the use of GNU C Library "
        "heap protector in Ubuntu. For more details see "
        "https://wiki.ubuntu.com/Security/Features#heap-protector"
    ),
    "pie": (
        "This vulnerability is mitigated in part by the use of Position "
        "Independent Executables in Ubuntu. For more details see "
        "https://wiki.ubuntu.com/Security/Features#pie"
    ),
    "review-break-fix": (
        "This vulnerability automatically received break-fix commits entries "
        "when it was added and needs to be reviewed."
    ),
}

# Possible CVE priorities
PRIORITIES = ["negligible", "low", "medium", "high", "critical"]

NOTE_RE = re.compile(r"^\s+([A-Za-z0-9-]+)([>|]) *(.*)$")

EXIT_FAIL = 1
EXIT_OKAY = 0

# New CVE file format for release package field is:
# <product>[/<where or who>]_SOFTWARE[/<modifier>]: <status> [(<when>)]
# <product> is the Canonical product or supporting technology (eg, ‘esm-apps’
# or ‘snap’). ‘ubuntu’ is the implied product when ‘<product>/’ is omitted
# from the ‘<product>[/<where or who>]’ tuple (ie, where we might use
# ‘ubuntu/bionic_DEBSRCPKG’ for consistency, we continue to use
# ‘bionic_DEBSRCPKG’)
# <where or who> indicates where the software lives or in the case of snaps or
# other technologies with a concept of publishers, who the publisher is
# SOFTWARE is the name of the software as dictated by the product (eg, the deb
# source package, the name of the snap or the name of the software project
# <modifier> is an optional key for grouping collections of packages (eg,
# ‘melodic’ for the ROS Melodic release or ‘rocky’ for the OpenStack Rocky
# release)
# <status> indicates the statuses as defined in UCT (eg, needs-triage, needed,
# pending, released, etc)
# <when> indicates ‘when’ the software will be/was fixed when used with the
# ‘pending’ or ‘released’ status (eg, the source package version, snap
# revision, etc)
# e.g.: esm-apps/xenial_jackson-databind: released (2.4.2-3ubuntu0.1~esm2)
# e.g.: git/github.com/gogo/protobuf_gogoprotobuf: needs-triage
# This method should keep supporting existing current format:
# e.g.: bionic_jackson-databind: needs-triage
def parse_cve_release_package_field(
    cve, field, data, value, code, msg, linenum
):
    package = ""
    release = ""
    state = ""
    details = ""
    try:
        release, package = field.split("_", 1)
    except ValueError:
        msg += "%s: %d: bad field with '_': '%s'\n" % (cve, linenum, field)
        code = EXIT_FAIL
        return False, package, release, state, details, code, msg

    try:
        info = value.split(" ", 1)
    except ValueError:
        msg += "%s: %d: missing state for '%s': '%s'\n" % (
            cve,
            linenum,
            field,
            value,
        )
        code = EXIT_FAIL
        return False, package, release, state, details, code, msg

    state = info[0]
    if state == "":
        state = "needs-triage"

    if len(info) < 2:
        details = ""
    else:
        details = info[1].strip()

    if details.startswith("["):
        msg += "%s: %d: %s has details that starts with a bracket: '%s'\n" % (
            cve,
            linenum,
            field,
            details,
        )
        code = EXIT_FAIL
        return False, package, release, state, details, code, msg

    if details.startswith("("):
        details = details[1:]
    if details.endswith(")"):
        details = details[:-1]

    # Work-around for old-style of only recording released versions
    if details == "" and state[0] in ("0123456789"):
        details = state
        state = "released"

    valid_states = [
        "needs-triage",
        "needed",
        "active",
        "pending",
        "released",
        "deferred",
        "DNE",
        "ignored",
        "not-affected",
    ]
    if state not in valid_states:
        msg += (
            "%s: %d: %s has unknown state: '%s' (valid states are: %s)\n"
            % (
                cve,
                linenum,
                field,
                state,
                " ".join(valid_states),
            )
        )
        code = EXIT_FAIL
        return False, package, release, state, details, code, msg

    # Verify "released" kernels have version details
    # if state == 'released' and package in kernel_srcs and details == '':
    #    msg += "%s: %s_%s has state '%s' but lacks version note\n" % (
    #       cve, package, release, state
    #    )
    #    code = EXIT_FAIL

    # Verify "active" states have an Assignee
    if state == "active" and data["Assigned-to"].strip() == "":
        msg += "%s: %d: %s has state '%s' but lacks 'Assigned-to'\n" % (
            cve,
            linenum,
            field,
            state,
        )
        code = EXIT_FAIL
        return False, package, release, state, details, code, msg

    return True, package, release, state, details, code, msg


class NotesParser:
    def __init__(self):
        self.notes = list()
        self.user = None
        self.separator = None
        self.note = None

    def parse_line(self, cve, line, linenum, code):
        msg = ""
        m = NOTE_RE.match(line)
        if m is not None:
            new_user = m.group(1)
            new_sep = m.group(2)
            new_note = m.group(3)
        else:
            # follow up comments should have 2 space indent and
            # an author
            if self.user is None:
                msg += "%s: %d: Note entry with no author: '%s'\n" % (
                    cve,
                    linenum,
                    line[1:],
                )
                code = EXIT_FAIL
            if not line.startswith("  "):
                msg += (
                    "%s: %d: Note continuations should be indented by "
                    "2 spaces: '%s'.\n" % (cve, linenum, line)
                )
                code = EXIT_FAIL
            new_user = self.user
            new_sep = self.separator
            new_note = line.strip()
        if self.user and self.separator and self.note:
            # if is different user, start a new note
            if new_user != self.user:
                self.notes.append((self.user, self.note))
                self.user = new_user
                self.note = new_note
                self.separator = new_sep
            elif new_sep != self.separator:
                # finish this note and start a new one since this has new
                # semantics
                self.notes.append((self.user, self.note))
                self.separator = new_sep
                self.note = new_note
            else:
                if self.separator == "|":
                    self.note = self.note + " " + new_note
                else:
                    assert self.separator == ">"
                    self.note = self.note + "\n" + new_note
        else:
            # this is the first note
            self.user = new_user
            self.separator = new_sep
            self.note = new_note
        return code, msg

    def finalize(self):
        if self.user is not None and self.note is not None:
            # add last Note
            self.notes.append((self.user, self.note))
            self.user = None
            self.note = None
        notes = self.notes
        self.user = None
        self.separator = None
        self.notes = None
        return notes


def load_cve(cve, strict=False, srcmap=None):
    """Loads a given CVE into:
    dict( fields...
          'pkgs' -> dict(  pkg -> dict(  release ->  (state, details)   ) )
        )
    """

    msg = ""
    code = EXIT_OKAY
    required_fields = [
        "Candidate",
        "PublicDate",
        "References",
        "Description",
        "Ubuntu-Description",
        "Notes",
        "Bugs",
        "Priority",
        "Discovered-by",
        "Assigned-to",
        "CVSS",
    ]
    extra_fields = ["CRD", "PublicDateAtUSN", "Mitigation"]

    data = OrderedDict()
    # maps entries in data to their source line - if didn't supply one
    # create a local one to simplify the code
    if srcmap is None:
        srcmap = OrderedDict()
    srcmap.setdefault("pkgs", OrderedDict())
    srcmap.setdefault("tags", OrderedDict())
    data.setdefault("tags", OrderedDict())
    srcmap.setdefault("patches", OrderedDict())
    data.setdefault("patches", OrderedDict())
    affected = OrderedDict()
    lastfield = ""
    fields_seen = []
    if not os.path.exists(cve):
        raise ValueError("File does not exist: '%s'" % (cve))
    linenum = 0
    notes_parser = NotesParser()
    cvss_entries = []

    cve_file = codecs.open(cve, encoding="utf-8")

    for line in cve_file.readlines():
        line = line.rstrip()
        linenum += 1

        # Ignore blank/commented lines
        if len(line) == 0 or line.startswith("#"):
            continue
        if line.startswith(" "):
            try:
                # parse Notes properly
                if lastfield == "Notes":
                    code, newmsg = notes_parser.parse_line(
                        cve, line, linenum, code
                    )
                    if code != EXIT_OKAY:
                        msg += newmsg
                elif "Patches_" in lastfield:
                    try:
                        _, pkg = lastfield.split("_", 1)
                        patch_type, entry = line.split(":", 1)
                        patch_type = patch_type.strip()
                        entry = entry.strip()
                        data["patches"][pkg].append((patch_type, entry))
                        srcmap["patches"][pkg].append((cve, linenum))
                    except Exception as e:
                        msg += (
                            "%s: %d: Failed to parse '%s' entry %s: %s\n"
                            % (
                                cve,
                                linenum,
                                lastfield,
                                line,
                                e,
                            )
                        )
                        code = EXIT_FAIL
                elif lastfield == "CVSS":
                    try:
                        cvss = OrderedDict()
                        result = re.search(
                            r" (.+)\: (\S+)( \[(.*) (.*)\])?", line
                        )
                        if result is None:
                            continue
                        cvss["source"] = result.group(1)
                        cvss["vector"] = result.group(2)
                        entry = parse_cvss(cvss["vector"])
                        if entry is None:
                            raise RuntimeError(
                                "Failed to parse_cvss() without raising "
                                "an exception."
                            )
                        if result.group(3):
                            cvss["baseScore"] = result.group(4)
                            cvss["baseSeverity"] = result.group(5)

                        cvss_entries.append(cvss)
                        # CVSS in srcmap will be a tuple since this is the
                        # line where the CVSS block starts - so convert it
                        # to a dict first if needed
                        if type(srcmap["CVSS"]) is tuple:
                            srcmap["CVSS"] = OrderedDict()
                        srcmap["CVSS"].setdefault(
                            cvss["source"], (cve, linenum)
                        )
                    except Exception as e:
                        msg += "%s: %d: Failed to parse CVSS: %s\n" % (
                            cve,
                            linenum,
                            e,
                        )
                        code = EXIT_FAIL
                else:
                    data[lastfield] += "\n%s" % (line[1:])
            except KeyError as e:
                msg += "%s: %d: bad line '%s' (%s)\n" % (cve, linenum, line, e)
                code = EXIT_FAIL
            continue

        try:
            field, value = line.split(":", 1)
        except ValueError as e:
            msg += "%s: %d: bad line '%s' (%s)\n" % (cve, linenum, line, e)
            code = EXIT_FAIL
            continue

        lastfield = field = field.strip()
        if field in fields_seen:
            msg += "%s: %d: repeated field '%s'\n" % (cve, linenum, field)
            code = EXIT_FAIL
        else:
            fields_seen.append(field)
        value = value.strip()
        if field == "Candidate":
            data.setdefault(field, value)
            srcmap.setdefault(field, (cve, linenum))
            if (
                value != ""
                and not value.startswith("CVE-")
                and not value.startswith("UEM-")
                and not value.startswith("EMB-")
            ):
                msg += (
                    "%s: %d: unknown Candidate '%s' "
                    "(must be /(CVE|UEM|EMB)-/)\n"
                    % (
                        cve,
                        linenum,
                        value,
                    )
                )
                code = EXIT_FAIL
        elif "Priority" in field:
            # For now, throw away comments on Priority fields
            if " " in value:
                value = value.split()[0]
            if "Priority_" in field:
                try:
                    _, pkg = field.split("_", 1)
                except ValueError:
                    msg += "%s: %d: bad field with 'Priority_': '%s'\n" % (
                        cve,
                        linenum,
                        field,
                    )
                    code = EXIT_FAIL
                    continue
            data.setdefault(field, value)
            srcmap.setdefault(field, (cve, linenum))
            if value not in ["untriaged", "not-for-us"] + PRIORITIES:
                msg += "%s: %d: unknown Priority '%s'\n" % (
                    cve,
                    linenum,
                    value,
                )
                code = EXIT_FAIL
        elif "Patches_" in field:
            try:
                _, pkg = field.split("_", 1)
            except ValueError:
                msg += "%s: %d: bad field with 'Patches_': '%s'\n" % (
                    cve,
                    linenum,
                    field,
                )
                code = EXIT_FAIL
                continue
            # value should be empty
            if len(value) > 0:
                msg += "%s: %d: '%s' field should have no value\n" % (
                    cve,
                    linenum,
                    field,
                )
                code = EXIT_FAIL
                continue
            data["patches"].setdefault(pkg, list())
            srcmap["patches"].setdefault(pkg, list())
        # This changes are needed to support global `Tags:`
        elif "Tags" in field:
            """These are processed into the "tags" hash"""
            try:
                _, pkg = field.split("_", 1)
            except ValueError:
                # no package specified - this is the global tags field - use a
                # key of '*' to store it in the package hash
                pkg = GLOBAL_TAGS_KEY
            data["tags"].setdefault(pkg, set())
            srcmap["tags"].setdefault(pkg, (cve, linenum))
            for word in value.strip().split(" "):
                if pkg == GLOBAL_TAGS_KEY and word not in valid_cve_tags:
                    msg += "%s: %d: invalid CVE tag '%s': '%s'\n" % (
                        cve,
                        linenum,
                        word,
                        field,
                    )
                    code = EXIT_FAIL
                    continue
                elif pkg != GLOBAL_TAGS_KEY and word not in valid_package_tags:
                    msg += "%s: %d: invalid package tag '%s': '%s'\n" % (
                        cve,
                        linenum,
                        word,
                        field,
                    )
                    code = EXIT_FAIL
                    continue
                data["tags"][pkg].add(word)
        elif "_" in field:
            (
                success,
                pkg,
                rel,
                state,
                details,
                code,
                msg,
            ) = parse_cve_release_package_field(
                cve, field, data, value, code, msg, linenum
            )
            if not success:
                assert code == EXIT_FAIL
                continue
            canon, _, _, _ = get_subproject_details(rel)
            if canon is None and rel not in ["upstream", "devel"]:
                msg += "%s: %d: unknown entry '%s'\n" % (cve, linenum, rel)
                code = EXIT_FAIL
                continue
            affected.setdefault(pkg, OrderedDict())
            if rel in affected[pkg]:
                msg += (
                    "%s: %d: duplicate entry for '%s': original at line %d\n"
                    % (
                        cve,
                        linenum,
                        rel,
                        srcmap["pkgs"][pkg][rel][1],
                    )
                )
                code = EXIT_FAIL
                continue
            affected[pkg].setdefault(rel, [state, details])
            srcmap["pkgs"].setdefault(pkg, OrderedDict())
            srcmap["pkgs"][pkg].setdefault(rel, (cve, linenum))
        elif field not in required_fields + extra_fields:
            msg += "%s: %d: unknown field '%s'\n" % (cve, linenum, field)
            code = EXIT_FAIL
        else:
            data.setdefault(field, value)
            srcmap.setdefault(field, (cve, linenum))

    cve_file.close()

    data["Notes"] = notes_parser.finalize()
    data["CVSS"] = cvss_entries

    # Check for required fields
    for field in required_fields:
        nonempty = ["Candidate"]
        if strict:
            nonempty += ["PublicDate"]
        # boilerplate files are special and can (should?) be empty
        if "boilerplate" in cve:
            nonempty = []

        if field not in data or field not in fields_seen:
            msg += "%s: %d: missing field '%s'\n" % (cve, linenum, field)
            code = EXIT_FAIL
        elif field in nonempty and data[field].strip() == "":
            msg += "%s: %d: required field '%s' is empty\n" % (
                cve,
                linenum,
                field,
            )
            code = EXIT_FAIL

    # Fill in defaults for missing fields
    if "Priority" not in data:
        data.setdefault("Priority", "untriaged")
        srcmap.setdefault("Priority", (cve, 1))

    # entries need an upstream entry if any entries are from the internal
    # list of subprojects
    for pkg in affected:
        needs_upstream = False
        for rel in affected[pkg]:
            if rel not in external_releases:
                needs_upstream = True
        if needs_upstream and "upstream" not in affected[pkg]:
            msg += "%s: %d: missing upstream '%s'\n" % (cve, linenum, pkg)
            code = EXIT_FAIL

    data["pkgs"] = affected

    code, msg = load_external_subproject_cve_data(cve, data, srcmap, code, msg)

    if code != EXIT_OKAY:
        raise ValueError(msg.strip())
    return data


def amend_external_subproject_pkg(cve, data, srcmap, amendments, code, msg):
    linenum = 0
    for line in amendments.splitlines():
        linenum += 1
        if len(line) == 0 or line.startswith("#") or line.startswith(" "):
            continue
        try:
            field, value = line.split(":", 1)
            field = field.strip()
            value = value.strip()
        except ValueError as e:
            msg += "%s: bad line '%s' (%s)\n" % (cve, line, e)
            code = EXIT_FAIL
            return code, msg

        if "_" in field:
            (
                success,
                pkg,
                release,
                state,
                details,
                code,
                msg,
            ) = parse_cve_release_package_field(
                cve, field, data, value, code, msg, linenum
            )
            if not success:
                return code, msg

            data.setdefault("pkgs", OrderedDict())
            data["pkgs"].setdefault(pkg, OrderedDict())
            srcmap["pkgs"].setdefault(pkg, OrderedDict())
            # override existing release info if it exists
            data["pkgs"][pkg][release] = [state, details]
            srcmap["pkgs"][pkg][release] = (cve, linenum)

    return code, msg


def load_external_subproject_cve_data(cve, data, srcmap, code, msg):
    cve_id = os.path.basename(cve)
    for f in find_external_subproject_cves(cve_id):
        with codecs.open(f, "r", encoding="utf-8") as fp:
            amendments = fp.read()
            fp.close()
        code, msg = amend_external_subproject_pkg(
            f, data, srcmap, amendments, code, msg
        )

    return code, msg


def parse_cvss(cvss):
    # parse a CVSS string into components suitable for MITRE / NVD JSON
    # format - assumes only the Base metric group from
    # https://www.first.org/cvss/specification-document since this is
    # mandatory - also validates by raising exceptions on errors
    metrics = {
        "attackVector": {
            "abbrev": "AV",
            "values": {
                "NETWORK": 0.85,
                "ADJACENT": 0.62,
                "LOCAL": 0.55,
                "PHYSICAL": 0.2,
            },
        },
        "attackComplexity": {
            "abbrev": "AC",
            "values": {"LOW": 0.77, "HIGH": 0.44},
        },
        "privilegesRequired": {
            "abbrev": "PR",
            "values": {
                "NONE": 0.85,
                # [ scope unchanged, changed ]
                "LOW": [0.62, 0.68],  # depends on scope
                "HIGH": [0.27, 0.5],
            },  # depends on scope
        },
        "userInteraction": {
            "abbrev": "UI",
            "values": {"NONE": 0.85, "REQUIRED": 0.62},
        },
        "scope": {"abbrev": "S", "values": {"UNCHANGED", "CHANGED"}},
        "confidentialityImpact": {
            "abbrev": "C",
            "values": {"HIGH": 0.56, "LOW": 0.22, "NONE": 0},
        },
        "integrityImpact": {
            "abbrev": "I",
            "values": {"HIGH": 0.56, "LOW": 0.22, "NONE": 0},
        },
        "availabilityImpact": {
            "abbrev": "A",
            "values": {"HIGH": 0.56, "LOW": 0.22, "NONE": 0},
        },
    }
    severities = {
        "NONE": 0.0,
        "LOW": 3.9,
        "MEDIUM": 6.9,
        "HIGH": 8.9,
        "CRITICAL": 10.0,
    }
    js = None
    # coerce cvss into a string
    cvss = str(cvss)
    for c in cvss.split("/"):
        elements = c.split(":")
        if len(elements) != 2:
            raise ValueError("Invalid CVSS element '%s'" % c)
        valid = False
        metric = elements[0]
        value = elements[1]
        if metric == "CVSS":
            if value == "3.0" or value == "3.1":
                js = {"baseMetricV3": {"cvssV3": {"version": value}}}
                valid = True
            else:
                raise ValueError(
                    "Unable to process CVSS version '%s' (we only support 3.x)"
                    % value
                )
        else:
            for m in metrics.keys():
                if metrics[m]["abbrev"] == metric:
                    for val in metrics[m]["values"]:
                        if val[0:1] == value:
                            js["baseMetricV3"]["cvssV3"][m] = val
                            valid = True
        if not valid:
            raise ValueError("Invalid CVSS elements '%s:%s'" % (metric, value))
    for m in metrics.keys():
        if m not in js["baseMetricV3"]["cvssV3"]:
            raise ValueError("Missing required CVSS base element %s" % m)
    # add vectorString
    js["baseMetricV3"]["cvssV3"]["vectorString"] = cvss

    # now calculate CVSS scores
    iss = 1 - (
        (
            1
            - metrics["confidentialityImpact"]["values"][
                js["baseMetricV3"]["cvssV3"]["confidentialityImpact"]
            ]
        )
        * (
            1
            - metrics["integrityImpact"]["values"][
                js["baseMetricV3"]["cvssV3"]["integrityImpact"]
            ]
        )
        * (
            1
            - metrics["availabilityImpact"]["values"][
                js["baseMetricV3"]["cvssV3"]["availabilityImpact"]
            ]
        )
    )
    if js["baseMetricV3"]["cvssV3"]["scope"] == "UNCHANGED":
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * pow(iss - 0.02, 15)
    attackVector = metrics["attackVector"]["values"][
        js["baseMetricV3"]["cvssV3"]["attackVector"]
    ]
    attackComplexity = metrics["attackComplexity"]["values"][
        js["baseMetricV3"]["cvssV3"]["attackComplexity"]
    ]
    privilegesRequired = metrics["privilegesRequired"]["values"][
        js["baseMetricV3"]["cvssV3"]["privilegesRequired"]
    ]
    # privilegesRequires could be a list if is LOW or HIGH (and then the
    # value depends on whether the scope is unchanged or not)
    if isinstance(privilegesRequired, list):
        if js["baseMetricV3"]["cvssV3"]["scope"] == "UNCHANGED":
            privilegesRequired = privilegesRequired[0]
        else:
            privilegesRequired = privilegesRequired[1]
    userInteraction = metrics["userInteraction"]["values"][
        js["baseMetricV3"]["cvssV3"]["userInteraction"]
    ]
    exploitability = (
        8.22
        * attackVector
        * attackComplexity
        * privilegesRequired
        * userInteraction
    )
    if impact <= 0:
        base_score = 0
    elif js["baseMetricV3"]["cvssV3"]["scope"] == "UNCHANGED":
        # use ceil and * 10 / 10 to get rounded up to nearest 10th decimal
        # (where rounded-up is say 0.01 -> 0.1)
        base_score = math.ceil(min(impact + exploitability, 10) * 10) / 10
    else:
        base_score = (
            math.ceil(min(1.08 * (impact + exploitability), 10) * 10) / 10
        )
    js["baseMetricV3"]["cvssV3"]["baseScore"] = base_score
    for severity in severities.keys():
        if base_score <= severities[severity]:
            js["baseMetricV3"]["cvssV3"]["baseSeverity"] = severity
            break
    # these use normal rounding to 1 decimal place
    js["baseMetricV3"]["exploitabilityScore"] = round(exploitability * 10) / 10
    js["baseMetricV3"]["impactScore"] = round(impact * 10) / 10
    return js
