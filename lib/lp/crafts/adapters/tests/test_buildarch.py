# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from functools import partial

from testscenarios import WithScenarios, load_tests_apply_scenarios
from testtools.matchers import (
    Equals,
    MatchesException,
    MatchesListwise,
    MatchesStructure,
    Raises,
)
from zope.component import getUtility

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.interfaces.processor import (
    IProcessorSet,
    ProcessorNotFound,
)
from lp.crafts.adapters.buildarch import (
    BadPropertyError,
    CraftBase,
    MissingPropertyError,
    determine_instances_to_build,
)
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.layers import LaunchpadZopelessLayer


class TestCraftBase(TestCase):
    def test_init(self):
        base = CraftBase("ubuntu", "22.04", "amd64")
        self.assertEqual("ubuntu", base.name)
        self.assertEqual("22.04", base.channel)
        self.assertEqual("amd64", base.architectures)

    def test_init_no_architectures(self):
        base = CraftBase("ubuntu", "22.04")
        self.assertEqual("ubuntu", base.name)
        self.assertEqual("22.04", base.channel)
        self.assertIsNone(base.architectures)

    def test_init_invalid_channel(self):
        self.assertRaises(BadPropertyError, CraftBase, "ubuntu", 22.04)

    def test_from_dict(self):
        properties = {
            "name": "ubuntu",
            "channel": "22.04",
            "architectures": "amd64",
        }
        base = CraftBase.from_dict(properties)
        self.assertEqual("ubuntu", base.name)
        self.assertEqual("22.04", base.channel)
        self.assertEqual("amd64", base.architectures)

    def test_from_dict_missing_name(self):
        properties = {
            "channel": "22.04",
        }
        self.assertRaises(
            MissingPropertyError, CraftBase.from_dict, properties
        )

    def test_from_dict_missing_channel(self):
        properties = {
            "name": "ubuntu",
        }
        self.assertRaises(
            MissingPropertyError, CraftBase.from_dict, properties
        )

    def test_equality(self):
        base1 = CraftBase("ubuntu", "22.04", "amd64")
        base2 = CraftBase("ubuntu", "22.04", "amd64")
        base3 = CraftBase("ubuntu", "20.04", "amd64")
        self.assertEqual(base1, base2)
        self.assertNotEqual(base1, base3)

    def test_hash(self):
        base1 = CraftBase("ubuntu", "22.04", "amd64")
        base2 = CraftBase("ubuntu", "22.04", "amd64")
        self.assertEqual(hash(base1), hash(base2))

    def test_str(self):
        base = CraftBase("ubuntu", "22.04", "amd64")
        self.assertEqual('ubuntu 22.04 "amd64"', str(base))

    def test_str_no_architectures(self):
        base = CraftBase("ubuntu", "22.04")
        self.assertEqual("ubuntu 22.04 null", str(base))


class TestDetermineInstancesToBuild(WithScenarios, TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    scenarios = [
        (
            "single platform",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "amd64": {},
                    },
                },
                "expected": [("22.04", "amd64")],
            },
        ),
        (
            "multiple platforms",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "amd64": {},
                        "arm64": {},
                    },
                },
                "expected": [("22.04", "amd64"), ("22.04", "arm64")],
            },
        ),
        (
            "build-for|on specified",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "amd64": {
                            "build-on": ["amd64"],
                            "build-for": "amd64",
                        },
                        "arm64": {
                            "build-on": ["arm64"],
                            "build-for": "arm64",
                        },
                    },
                },
                "expected": [("22.04", "amd64"), ("22.04", "arm64")],
            },
        ),
        (
            "build-for as list",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "amd64": {
                            "build-on": ["amd64"],
                            "build-for": ["amd64"],
                        },
                    },
                },
                "expected": [("22.04", "amd64")],
            },
        ),
        (
            "invalid build-for list",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "amd64": {
                            "build-on": ["amd64"],
                            "build-for": ["amd64", "arm64"],
                        },
                    },
                },
                "expected_exception": MatchesException(
                    BadPropertyError,
                    "'build-for' must be a single string or a list with "
                    "exactly one element for platform amd64",
                ),
            },
        ),
        (
            "build-on is required for unsupported architecture",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "amdtest": {"build-for": "amd64"},
                    },
                },
                "expected_exception": MatchesException(
                    MissingPropertyError,
                    "'build-on' is required when 'build-for' is specified or "
                    "for unsupported architecture amdtest",
                ),
            },
        ),
        (
            "build-for is required for unsupported architecture",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "amdtest": {"build-on": ["amd64"]},
                    },
                },
                "expected_exception": MatchesException(
                    MissingPropertyError,
                    "'build-for' is required for unsupported architecture "
                    "amdtest",
                ),
            },
        ),
        (
            "unsupported architecture with configuration",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "mips-arch": {
                            "build-on": ["mips"],
                            "build-for": "mips",
                        },
                    },
                },
                "expected_exception": MatchesException(
                    BadPropertyError,
                    "Unsupported architecture mips in platform mips-arch",
                ),
            },
        ),
        (
            "unsupported architecture without configuration",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "mips-arch": {},
                    },
                },
                "expected_exception": MatchesException(
                    MissingPropertyError,
                    "Configuration is required for unsupported architecture "
                    "mips-arch",
                ),
            },
        ),
        (
            "build-for as list",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "amd64": {"build-for": ["amd64"]},
                    },
                },
                "expected": [("22.04", "amd64")],
            },
        ),
        (
            "invalid build-for list",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "amd64": {"build-for": ["amd64", "arm64"]},
                    },
                },
                "expected_exception": MatchesException(
                    BadPropertyError,
                    "build-for must be a single string or a list with exactly "
                    "one element for platform amd64",
                ),
            },
        ),
        (
            "unsupported architecture",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                    "platforms": {
                        "mips-arch": {
                            "build-on": ["mips"],
                            "build-for": "mips",
                        },
                    },
                },
                "expected_exception": MatchesException(
                    BadPropertyError,
                    "Unsupported architecture mips in platform mips-arch",
                ),
            },
        ),
        (
            "bare base",
            {
                "sourcecraft_data": {
                    "base": "bare",
                    "build-base": "ubuntu@20.04",
                    "platforms": {
                        "amd64": {},
                    },
                },
                "expected": [("20.04", "amd64")],
            },
        ),
        (
            "missing base",
            {
                "sourcecraft_data": {
                    "platforms": {
                        "amd64": {},
                    },
                },
                "expected_exception": MatchesException(
                    MissingPropertyError,
                    "Craft specification is missing the 'base' property",
                ),
            },
        ),
        (
            "missing build-base for bare",
            {
                "sourcecraft_data": {
                    "base": "bare",
                    "platforms": {
                        "amd64": {},
                    },
                },
                "expected_exception": MatchesException(
                    MissingPropertyError,
                    "If base is 'bare', then build-base must be specified",
                ),
            },
        ),
        (
            "missing platforms",
            {
                "sourcecraft_data": {
                    "base": "ubuntu@22.04",
                },
                "expected_exception": MatchesException(
                    MissingPropertyError,
                    "Craft specification is missing the 'platforms' property",
                ),
            },
        ),
        (
            "invalid base format",
            {
                "sourcecraft_data": {
                    "base": "ubuntu-22.04",
                    "platforms": {
                        "amd64": {},
                    },
                },
                "expected_exception": MatchesException(
                    BadPropertyError,
                    "Invalid value for base 'ubuntu-22.04'. Expected value "
                    "should be like 'ubuntu@24.04'",
                ),
            },
        ),
    ]

    def setUp(self):
        super().setUp()
        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.distro_serieses = [
            self.factory.makeDistroSeries(
                distribution=self.ubuntu,
                version=version,
            )
            for version in ("24.04", "22.04", "20.04")
        ]
        self.dases = []
        for arch_tag in ("amd64", "arm64"):
            try:
                processor = getUtility(IProcessorSet).getByName(arch_tag)
            except ProcessorNotFound:
                processor = self.factory.makeProcessor(
                    name=arch_tag, supports_virtualized=True
                )
            for distro_series in self.distro_serieses:
                self.dases.append(
                    self.factory.makeDistroArchSeries(
                        distroseries=distro_series,
                        architecturetag=arch_tag,
                        processor=processor,
                    )
                )

    def test_determine_instances_to_build(self):
        build_instances_factory = partial(
            determine_instances_to_build,
            self.sourcecraft_data,
            self.dases,
        )

        if hasattr(self, "expected_exception"):
            self.assertThat(
                build_instances_factory, Raises(self.expected_exception)
            )
        else:
            self.assertThat(
                build_instances_factory(),
                MatchesListwise(
                    [
                        MatchesStructure(
                            distroseries=MatchesStructure.byEquality(
                                version=version
                            ),
                            architecturetag=Equals(arch_tag),
                        )
                        for version, arch_tag in self.expected
                    ]
                ),
            )


load_tests = load_tests_apply_scenarios
