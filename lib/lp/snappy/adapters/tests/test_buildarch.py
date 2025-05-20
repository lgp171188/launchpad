# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from functools import partial

from testscenarios import WithScenarios, load_tests_apply_scenarios
from testtools.matchers import HasLength, MatchesException, Raises

from lp.snappy.adapters.buildarch import (
    AllConflictInBuildForError,
    AllConflictInBuildOnError,
    CraftPlatformsBuildPlanError,
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
            "no architectures, build one per supported architecture",
            {
                "architectures": None,
                "supported_architectures": ["amd64", "i386", "armhf"],
                "base": "core18",
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                        "platform_name": None,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": None,
                    },
                    {
                        "architecture": "armhf",
                        "target_architectures": ["armhf"],
                        "required": True,
                        "platform_name": None,
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
                        "platform_name": None,
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
                        "platform_name": None,
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
                        "platform_name": None,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": None,
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
                        "platform_name": None,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": None,
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
                        "platform_name": None,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": None,
                    },
                    {
                        "architecture": "armhf",
                        "target_architectures": ["armhf"],
                        "required": False,
                        "platform_name": None,
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
                        "platform_name": None,
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
                        "platform_name": None,
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
                        "platform_name": None,
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
                        "platform_name": None,
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
                        "platform_name": None,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": None,
                    },
                ],
            },
        ),
        (
            "build-on contains both all and another architecture",
            {
                "architectures": [{"build-on": ["all", "amd64"]}],
                "supported_architectures": ["amd64"],
                "expected_exception": MatchesException(
                    AllConflictInBuildOnError
                ),
            },
        ),
        (
            "build-for contains both all and another architecture",
            {
                "architectures": [
                    {"build-on": "amd64", "build-for": ["amd64", "all"]}
                ],
                "supported_architectures": ["amd64"],
                "expected_exception": MatchesException(
                    AllConflictInBuildForError
                ),
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
                        "platform_name": None,
                    },
                    {
                        "architecture": "amd64",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": None,
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
                "expected_exception": MatchesException(DuplicateBuildOnError),
            },
        ),
        (
            "platforms with configuration",
            {
                "base": "core24",
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
                        "platform_name": "ubuntu-amd64",
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": "ubuntu-i386",
                    },
                ],
            },
        ),
        (
            "platforms with shorthand configuration",
            {
                "base": "core24",
                "platforms": {
                    "amd64": None,
                    "i386": None,
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                        "platform_name": "amd64",
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": "i386",
                    },
                ],
            },
        ),
        (
            "platforms with unsupported architecture",
            {
                "base": "core24",
                "platforms": {
                    "ubuntu-unsupported": None,
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": MatchesException(
                    CraftPlatformsBuildPlanError,
                    "Failed to compute the build plan for the snapcraft "
                    r"file with error*",
                ),
            },
        ),
        (
            # multiple architecture values in "build-for" and "build-on"
            # are not allowed by snapcraft and such configs are invalid.
            # As craft_platforms is a separate, generalized API, it still
            # returns a build plan which we then filter and pair a native
            # build with native architecture to run on.
            "platforms with multiple architectures",
            {
                "base": "core24",
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
                        "target_architectures": ["amd64"],
                        "required": True,
                        "platform_name": "ubuntu-amd64-i386",
                    },
                ],
            },
        ),
        (
            "platforms with conflict in build-on",
            {
                "base": "core24",
                "platforms": {
                    "ubuntu-conflict": {
                        "build-on": ["all", "amd64"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": MatchesException(
                    CraftPlatformsBuildPlanError,
                    "Failed to compute the build plan for the snapcraft "
                    "file with error: 'all' is not a valid DebianArchitecture",
                ),
            },
        ),
        (
            "platforms with conflict in build-for",
            {
                "base": "core24",
                "platforms": {
                    "ubuntu-conflict": {
                        "build-on": ["amd64"],
                        "build-for": ["all", "amd64"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": MatchesException(
                    CraftPlatformsBuildPlanError,
                    "Failed to compute the build plan for the snapcraft "
                    "file with error: build-for: all must be the only "
                    "build-for architecture Resolution: Provide only one "
                    "platform with only build-for: all or remove 'all' from "
                    "build-for options.",
                ),
            },
        ),
        (
            "platforms with invalid architecture in build-on",
            {
                "base": "core24",
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["invalid"],
                        "build-for": ["amd64"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": MatchesException(
                    CraftPlatformsBuildPlanError,
                    (
                        "Failed to compute the build plan for the snapcraft "
                        "file with error: 'invalid' is not a valid "
                        "DebianArchitecture"
                    ),
                ),
            },
        ),
        (
            "platforms with invalid architecture in build-for",
            {
                "base": "core24",
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["invalid"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": MatchesException(
                    CraftPlatformsBuildPlanError,
                    (
                        "Failed to compute the build plan for the snapcraft "
                        "file with error: 'invalid' is not a valid "
                        "DebianArchitecture"
                    ),
                ),
            },
        ),
        (
            "platforms with duplicate build-on",
            {
                "snap_base_features": {
                    SnapBaseFeature.ALLOW_DUPLICATE_BUILD_ON: False
                },
                "base": "core24",
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
                "expected_exception": MatchesException(DuplicateBuildOnError),
            },
        ),
        (
            "platforms with multiple build-for for the same build-on",
            {
                "snap_base_features": {
                    SnapBaseFeature.ALLOW_DUPLICATE_BUILD_ON: True
                },
                "base": "core24",
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
                        "platform_name": "ubuntu-amd64",
                    },
                    {
                        "architecture": "amd64",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": "ubuntu-amd64-i386",
                    },
                ],
            },
        ),
        (
            "platforms with 'all' keyword in 'build-on'",
            {
                "base": "core24",
                "platforms": {
                    "ubuntu-all": {
                        "build-on": ["all"],
                        "build-for": ["all"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected_exception": MatchesException(
                    CraftPlatformsBuildPlanError,
                    "Failed to compute the build plan for the snapcraft "
                    "file with error: 'all' is not a valid DebianArchitecture",
                ),
            },
        ),
        (
            "platforms with 'all' keyword in 'build-for'",
            {
                "base": "core24",
                "platforms": {
                    "ubuntu-all": {
                        "build-on": ["amd64"],
                        "build-for": ["all"],
                    },
                },
                "supported_architectures": ["amd64", "i386", "armhf"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["all"],
                        "required": True,
                        "platform_name": "ubuntu-all",
                    },
                ],
            },
        ),
        (
            "no platforms entry",
            {
                "base": "core24",
                "supported_architectures": ["amd64", "i386"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                        "platform_name": None,
                    },
                    {
                        "architecture": "i386",
                        "target_architectures": ["i386"],
                        "required": True,
                        "platform_name": None,
                    },
                ],
            },
        ),
        (
            "platforms with shorthand and unsupported architecture skipped",
            {
                "base": "core24",
                "platforms": {
                    "amd64": None,
                    "arm64": None,
                },
                "supported_architectures": ["amd64", "i386"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                        "platform_name": "amd64",
                    }
                ],
            },
        ),
        (
            "platforms with shorthand and supported architectures",
            {
                "base": "core24",
                "platforms": {
                    "amd64": None,
                    "arm64": None,
                },
                "supported_architectures": ["amd64", "arm64"],
                "expected": [
                    {
                        "architecture": "amd64",
                        "target_architectures": ["amd64"],
                        "required": True,
                        "platform_name": "amd64",
                    },
                    {
                        "architecture": "arm64",
                        "target_architectures": ["arm64"],
                        "required": True,
                        "platform_name": "arm64",
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
        if hasattr(self, "base"):
            snapcraft_data["base"] = self.base
        snap_base_features = getattr(self, "snap_base_features", {})
        snap_base = self.factory.makeSnapBase(features=snap_base_features)
        if hasattr(self, "expected_exception"):
            determine_arches_to_builds = partial(
                determine_architectures_to_build,
                snap_base,
                snapcraft_data,
                self.supported_architectures,
            )
            self.assertThat(
                determine_arches_to_builds,
                Raises(self.expected_exception),
            )
        else:
            build_instances = determine_architectures_to_build(
                snap_base, snapcraft_data, self.supported_architectures
            )
            self.assertThat(build_instances, HasLength(len(self.expected)))
            for instance in build_instances:
                self.assertIn(instance.__dict__, self.expected)


load_tests = load_tests_apply_scenarios
