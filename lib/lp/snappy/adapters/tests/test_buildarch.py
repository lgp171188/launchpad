# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from testscenarios import WithScenarios, load_tests_apply_scenarios
from testtools.matchers import HasLength

from lp.snappy.adapters.buildarch import (
    AllConflictInBuildForError,
    AllConflictInBuildOnError,
    BadPropertyError,
    DuplicateBuildOnError,
    SnapArchitecture,
    SnapBuildInstance,
    UnsupportedBuildOnError,
    determine_architectures_to_build,
)
from lp.snappy.interfaces.snapbase import SnapBaseFeature
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestSnapArchitecture(WithScenarios, TestCase):
    scenarios = [
        (
            "lists",
            {
                "architectures": {
                    "build-on": ["amd64"],
                    "build-for": ["amd64"],
                },
                "expected_build_on": ["amd64"],
                "expected_build_for": ["amd64"],
                "expected_build_error": None,
            },
        ),
        (
            "strings",
            {
                "architectures": {"build-on": "amd64", "build-for": "amd64"},
                "expected_build_on": ["amd64"],
                "expected_build_for": ["amd64"],
                "expected_build_error": None,
            },
        ),
        (
            "no build-for",
            {
                "architectures": {"build-on": ["amd64"]},
                "expected_build_on": ["amd64"],
                "expected_build_for": ["amd64"],
                "expected_build_error": None,
            },
        ),
        (
            "not required",
            {
                "architectures": {
                    "build-on": ["amd64"],
                    "build-for": "amd64",
                    "build-error": "ignore",
                },
                "expected_build_on": ["amd64"],
                "expected_build_for": ["amd64"],
                "expected_build_error": "ignore",
            },
        ),
        (
            "build-for",
            {
                "architectures": {"build-on": ["amd64"], "build-for": "all"},
                "expected_build_on": ["amd64"],
                "expected_build_for": ["all"],
                "expected_build_error": None,
            },
        ),
        (
            "run-on",
            {
                "architectures": {"build-on": ["amd64"], "run-on": "all"},
                "expected_build_on": ["amd64"],
                "expected_build_for": ["all"],
                "expected_build_error": None,
            },
        ),
    ]

    def test_architecture(self):
        architecture = SnapArchitecture.from_dict(self.architectures)
        self.assertEqual(self.expected_build_on, architecture.build_on)
        self.assertEqual(self.expected_build_for, architecture.build_for)
        self.assertEqual(self.expected_build_error, architecture.build_error)


class TestSnapBuildInstance(WithScenarios, TestCase):
    # Single-item scenarios taken from the architectures document:
    # https://forum.snapcraft.io/t/architectures/4972
    scenarios = [
        (
            "i386",
            {
                "architecture": SnapArchitecture(
                    build_on="i386", build_for=["amd64", "i386"]
                ),
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_architecture": "i386",
                "expected_target_architectures": ["amd64", "i386"],
                "expected_required": True,
            },
        ),
        (
            "amd64",
            {
                "architecture": SnapArchitecture(
                    build_on="amd64", build_for="all"
                ),
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_architecture": "amd64",
                "expected_target_architectures": ["all"],
                "expected_required": True,
            },
        ),
        (
            "amd64 priority",
            {
                "architecture": SnapArchitecture(
                    build_on=["amd64", "i386"], build_for="all"
                ),
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_architecture": "amd64",
                "expected_target_architectures": ["all"],
                "expected_required": True,
            },
        ),
        (
            "i386 priority",
            {
                "architecture": SnapArchitecture(
                    build_on=["amd64", "i386"], build_for="all"
                ),
                "supported_architectures": ["i386", "amd64", "armhf"],
                "expected_architecture": "i386",
                "expected_target_architectures": ["all"],
                "expected_required": True,
            },
        ),
        (
            "optional",
            {
                "architecture": SnapArchitecture(
                    build_on="amd64", build_error="ignore"
                ),
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_architecture": "amd64",
                "expected_target_architectures": ["amd64"],
                "expected_required": False,
            },
        ),
        (
            "build on all",
            {
                "architecture": SnapArchitecture(build_on=["all"]),
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_architecture": "amd64",
                "expected_target_architectures": ["all"],
                "expected_required": True,
            },
        ),
        (
            "build on all, build for i386",
            {
                "architecture": SnapArchitecture(
                    build_on=["all"], build_for="i386"
                ),
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_architecture": "i386",
                "expected_target_architectures": ["i386"],
                "expected_required": True,
            },
        ),
    ]

    def test_build_instance(self):
        instance = SnapBuildInstance(
            self.architecture, self.supported_architectures
        )
        self.assertEqual(self.expected_architecture, instance.architecture)
        self.assertEqual(
            self.expected_target_architectures, instance.target_architectures
        )
        self.assertEqual(self.expected_required, instance.required)


class TestSnapBuildInstanceError(TestCase):
    def test_no_matching_arch_raises(self):
        architecture = SnapArchitecture(build_on="amd64", build_for="amd64")
        raised = self.assertRaises(
            UnsupportedBuildOnError, SnapBuildInstance, architecture, ["i386"]
        )
        self.assertEqual(["amd64"], raised.build_on)


class TestDetermineArchitecturesToBuild(WithScenarios, TestCaseWithFactory):
    # Scenarios taken from the architectures document:
    # https://forum.snapcraft.io/t/architectures/4972

    layer = ZopelessDatabaseLayer

    scenarios = [
        (
            "none",
            {
                "architectures": None,
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                    },
                    {
                        "architecture": "armhf",
                        "target_architectures": ["armhf"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "i386",
            {
                "architectures": [
                    {"build-on": "i386", "build-for": ["amd64", "i386"]},
                ],
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "i386",
                        "target_architectures": ["amd64", "i386"],
                        "required": True,
                    }
                ],
            },
        ),
        (
            "amd64",
            {
                "architectures": [{"build-on": "amd64", "build-for": "all"}],
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["all"],
                        "required": True,
                    }
                ],
            },
        ),
        (
            "amd64 and i386",
            {
                "architectures": [
                    {"build-on": "amd64", "build-for": "amd64"},
                    {"build-on": "i386", "build-for": "i386"},
                ],
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "amd64 and i386 shorthand",
            {
                "architectures": [
                    {"build-on": "amd64"},
                    {"build-on": "i386"},
                ],
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "amd64, i386, and armhf",
            {
                "architectures": [
                    {"build-on": "amd64", "build-for": "amd64"},
                    {"build-on": "i386", "build-for": "i386"},
                    {
                        "build-on": "armhf",
                        "build-for": "armhf",
                        "build-error": "ignore",
                    },
                ],
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                    },
                    {
                        "architecture": "armhf",
                        "target_architectures": ["armhf"],
                        "required": False,
                    },
                ],
            },
        ),
        (
            "amd64 priority",
            {
                "architectures": [
                    {"build-on": ["amd64", "i386"], "build-for": "all"},
                ],
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["all"],
                        "required": True,
                    }
                ],
            },
        ),
        (
            "i386 priority",
            {
                "architectures": [
                    {"build-on": ["amd64", "i386"], "build-for": "all"},
                ],
                "supported_architectures": ["i386", "amd64", "armhf"],
                "expected": [
                    {
                        "architecture": "i386",
                        "target_architectures": ["all"],
                        "required": True,
                    }
                ],
            },
        ),
        (
            "old style i386 priority",
            {
                "architectures": ["amd64", "i386"],
                "supported_architectures": ["i386", "amd64", "armhf"],
                "expected": [
                    {
                        "architecture": "i386",
                        "target_architectures": ["amd64", "i386"],
                        "required": True,
                    }
                ],
            },
        ),
        (
            "old style amd64 priority",
            {
                "architectures": ["amd64", "i386"],
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64", "i386"],
                        "required": True,
                    }
                ],
            },
        ),
        (
            "more architectures listed than are supported",
            {
                "architectures": [
                    {"build-on": "amd64"},
                    {"build-on": "i386"},
                    {"build-on": "armhf"},
                ],
                "supported_architectures": ["amd64", "i386"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "build-on contains both all and another architecture",
            {
                "architectures": [{"build-on": ["all", "amd64"]}],
                "supported_architectures": ["amd64"],
                "expected_exception": AllConflictInBuildOnError,
            },
        ),
        (
            "build-for contains both all and another architecture",
            {
                "architectures": [
                    {"build-on": "amd64", "build-for": ["amd64", "all"]}
                ],
                "supported_architectures": ["amd64"],
                "expected_exception": AllConflictInBuildForError,
            },
        ),
        (
            "multiple build-for for the same build-on",
            {
                "snap_base_features": {
                    SnapBaseFeature.ALLOW_DUPLICATE_BUILD_ON: True
                },
                "architectures": [
                    {"build-on": "amd64", "build-for": ["amd64"]},
                    {"build-on": "amd64", "build-for": ["i386"]},
                ],
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                    {
                        "architecture": "amd64",
                        "target_architectures": ["i386"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "multiple build-for for the same build-on: old base",
            {
                "snap_base_features": {
                    SnapBaseFeature.ALLOW_DUPLICATE_BUILD_ON: False
                },
                "architectures": [
                    {"build-on": "amd64", "build-for": ["amd64"]},
                    {"build-on": "amd64", "build-for": ["i386"]},
                ],
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": DuplicateBuildOnError,
            },
        ),
        (
            "platforms with configuration",
            {
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["amd64"],
                    },
                    "ubuntu-i386": {
                        "build-on": ["i386"],
                        "build-for": ["i386"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "platforms with shorthand configuration",
            {
                "platforms": {
                    "amd64": {},
                    "i386": {},
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "platforms with unsupported architecture",
            {
                "platforms": {
                    "ubuntu-unsupported": {},
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": BadPropertyError,
            },
        ),
        (
            "platforms with multiple architectures",
            {
                "platforms": {
                    "ubuntu-amd64-i386": {
                        "build-on": ["amd64", "i386"],
                        "build-for": ["amd64", "i386"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64", "i386"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "platforms with conflict in build-on",
            {
                "platforms": {
                    "ubuntu-conflict": {
                        "build-on": ["all", "amd64"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": AllConflictInBuildOnError,
            },
        ),
        (
            "platforms with conflict in build-for",
            {
                "platforms": {
                    "ubuntu-conflict": {
                        "build-on": ["amd64"],
                        "build-for": ["all", "amd64"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": AllConflictInBuildForError,
            },
        ),
        (
            "platforms with unsupported architecture in build-on",
            {
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["unsupported"],
                        "build-for": ["amd64"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                # Launchpad ignores architectures that it does not know about
                "expected": [],
            },
        ),
        (
            "platforms with 1/2 unsupported architectures in build-on",
            {
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["unsupported", "amd64"],
                        "build-for": ["amd64"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "platforms with duplicate build-on",
            {
                "snap_base_features": {
                    SnapBaseFeature.ALLOW_DUPLICATE_BUILD_ON: False
                },
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["amd64"],
                    },
                    "ubuntu-amd64-duplicate": {
                        "build-on": ["amd64"],
                        "build-for": ["i386"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": DuplicateBuildOnError,
            },
        ),
        (
            "platforms with multiple build-for for the same build-on",
            {
                "snap_base_features": {
                    SnapBaseFeature.ALLOW_DUPLICATE_BUILD_ON: True
                },
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["amd64"],
                    },
                    "ubuntu-amd64-i386": {
                        "build-on": ["amd64"],
                        "build-for": ["i386"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                    },
                    {
                        "architecture": "amd64",
                        "target_architectures": ["i386"],
                        "required": True,
                    },
                ],
            },
        ),
        (
            "platforms with all keyword",
            {
                "platforms": {
                    "ubuntu-all": {
                        "build-on": ["all"],
                        "build-for": ["all"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["all"],
                        "required": True,
                    },
                ],
            },
        ),
    ]

    def test_parser(self):
        snapcraft_data = {}
        if hasattr(self, "architectures"):
            snapcraft_data["architectures"] = self.architectures
        if hasattr(self, "platforms"):
            snapcraft_data["platforms"] = self.platforms
        snap_base_features = getattr(self, "snap_base_features", {})
        snap_base = self.factory.makeSnapBase(features=snap_base_features)
        if hasattr(self, "expected_exception"):
            self.assertRaises(
                self.expected_exception,
                determine_architectures_to_build,
                snap_base,
                snapcraft_data,
                self.supported_architectures,
            )
        else:
            build_instances = determine_architectures_to_build(
                snap_base, snapcraft_data, self.supported_architectures
            )
            self.assertThat(build_instances, HasLength(len(self.expected)))
            for instance in build_instances:
                self.assertIn(instance.__dict__, self.expected)


load_tests = load_tests_apply_scenarios
