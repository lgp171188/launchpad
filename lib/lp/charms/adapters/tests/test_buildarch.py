# Copyright 2021 Canonical Ltd.  This software is licensed under the
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
from lp.charms.adapters.buildarch import (
    BadPropertyError,
    CharmBase,
    CharmBaseConfiguration,
    CraftPlatformsBuildPlanError,
    DuplicateRunOnError,
    determine_instances_to_build,
)
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.layers import LaunchpadZopelessLayer


class TestCharmBaseConfiguration(WithScenarios, TestCase):
    scenarios = [
        (
            "expanded",
            {
                "base": {
                    "build-on": [
                        {
                            "name": "ubuntu",
                            "channel": "18.04",
                            "architectures": ["amd64"],
                        }
                    ],
                    "run-on": [
                        {
                            "name": "ubuntu",
                            "channel": "20.04",
                            "architectures": ["amd64", "arm64"],
                        },
                        {
                            "name": "ubuntu",
                            "channel": "18.04",
                            "architectures": ["amd64"],
                        },
                    ],
                },
                "expected_build_on": [
                    CharmBase(
                        name="ubuntu", channel="18.04", architectures=["amd64"]
                    ),
                ],
                "expected_run_on": [
                    CharmBase(
                        name="ubuntu",
                        channel="20.04",
                        architectures=["amd64", "arm64"],
                    ),
                    CharmBase(
                        name="ubuntu", channel="18.04", architectures=["amd64"]
                    ),
                ],
            },
        ),
        (
            "short form",
            {
                "base": {
                    "name": "ubuntu",
                    "channel": "20.04",
                },
                "expected_build_on": [
                    CharmBase(name="ubuntu", channel="20.04")
                ],
                "expected_run_on": [CharmBase(name="ubuntu", channel="20.04")],
            },
        ),
        (
            "no run-on",
            {
                "base": {
                    "build-on": [
                        {
                            "name": "ubuntu",
                            "channel": "20.04",
                            "architectures": ["amd64"],
                        }
                    ],
                },
                "expected_build_on": [
                    CharmBase(
                        name="ubuntu", channel="20.04", architectures=["amd64"]
                    ),
                ],
                "expected_run_on": [
                    CharmBase(
                        name="ubuntu", channel="20.04", architectures=["amd64"]
                    ),
                ],
            },
        ),
    ]

    def test_base(self):
        config = CharmBaseConfiguration.from_dict(self.base)
        self.assertEqual(self.expected_build_on, config.build_on)
        self.assertEqual(self.expected_run_on, config.run_on)


class TestDetermineInstancesToBuild(WithScenarios, TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    # Scenarios taken from the charmcraft build providers specification:
    # https://discourse.charmhub.io/t/charmcraft-bases-provider-support/4713
    scenarios = [
        # 'Bases' format scenarios
        (
            "single entry, single arch",
            {
                "bases": [
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "18.04",
                                "architectures": ["amd64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "18.04",
                                "architectures": ["amd64"],
                            }
                        ],
                    }
                ],
                "expected": [("18.04", "amd64")],
            },
        ),
        (
            "multiple entries, single arch",
            {
                "bases": [
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "18.04",
                                "architectures": ["amd64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "18.04",
                                "architectures": ["amd64"],
                            }
                        ],
                    },
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                    },
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["riscv64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["riscv64"],
                            }
                        ],
                    },
                ],
                "expected": [
                    ("18.04", "amd64"),
                    ("20.04", "amd64"),
                    ("20.04", "riscv64"),
                ],
            },
        ),
        (
            "single entry, multiple arches",
            {
                "bases": [
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64", "riscv64"],
                            }
                        ],
                    }
                ],
                "expected": [("20.04", "amd64")],
            },
        ),
        (
            "multiple entries, with cross-arch",
            {
                "bases": [
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["riscv64"],
                            }
                        ],
                    },
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                    },
                ],
                "expected": [("20.04", "amd64")],
            },
        ),
        (
            "multiple run-on entries",
            {
                "bases": [
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "18.04",
                                "architectures": ["amd64"],
                            },
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64", "riscv64"],
                            },
                        ],
                    }
                ],
                "expected": [("20.04", "amd64")],
            },
        ),
        (
            "multiple build-on entries",
            {
                "bases": [
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "18.04",
                                "architectures": ["amd64"],
                            },
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            },
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                    }
                ],
                "expected": [("18.04", "amd64")],
            },
        ),
        (
            "redundant outputs",
            {
                "bases": [
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "18.04",
                                "architectures": ["amd64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                    },
                    {
                        "build-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                        "run-on": [
                            {
                                "name": "ubuntu",
                                "channel": "20.04",
                                "architectures": ["amd64"],
                            }
                        ],
                    },
                ],
                "expected_exception": MatchesException(
                    DuplicateRunOnError,
                    r"ubuntu 20\.04 \[\"amd64\"\] is present in the 'run-on' "
                    r"of multiple items",
                ),
            },
        ),
        (
            "abbreviated, no architectures specified",
            {
                "bases": [
                    {
                        "name": "ubuntu",
                        "channel": "18.04",
                    }
                ],
                "expected": [
                    ("18.04", "amd64"),
                    ("18.04", "arm64"),
                    ("18.04", "riscv64"),
                ],
            },
        ),
        # Unified format scenarios
        (
            "unified single platform",
            {
                "bases": None,
                "base": "ubuntu@20.04",
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["amd64"],
                    }
                },
                "expected": [("20.04", "amd64")],
                "expected_platforms": ["ubuntu-amd64"],
            },
        ),
        (
            "unified multi-platforms",
            {
                "bases": None,
                "base": "ubuntu@20.04",
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["amd64"],
                    },
                    "ubuntu-arm64": {
                        "build-on": ["arm64"],
                        "build-for": ["arm64"],
                    },
                },
                "expected": [("20.04", "amd64"), ("20.04", "arm64")],
                "expected_platforms": ["ubuntu-amd64", "ubuntu-arm64"],
            },
        ),
        (
            "unified build-for all single platform",
            {
                "bases": None,
                "base": "ubuntu@20.04",
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["all"],
                    },
                },
                "expected": [("20.04", "amd64")],
                "expected_platforms": ["ubuntu-amd64"],
            },
        ),
        (
            "unified multiple build-for all platforms",
            {
                "bases": None,
                "base": "ubuntu@20.04",
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["all"],
                    },
                    "ubuntu-arm64": {
                        "build-on": ["arm64"],
                        "build-for": ["all"],
                    },
                },
                "expected": [("20.04", "amd64"), ("20.04", "arm64")],
                "expected_platforms": ["ubuntu-amd64", "ubuntu-arm64"],
            },
        ),
        (
            "unified without platforms, builds for all allowed archs",
            {
                "bases": None,
                "base": "ubuntu@20.04",
                "platforms": None,
                "expected": [
                    ("20.04", "amd64"),
                    ("20.04", "arm64"),
                    ("20.04", "riscv64"),
                ],
                "expected_platforms": ["amd64", "arm64", "riscv64"],
            },
        ),
        (
            "unified without supported series",
            {
                "bases": None,
                "base": "ubuntu@22.04",
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["amd64"],
                    },
                },
                "expected": [],
            },
        ),
        (
            "unified invalid platform name",
            {
                "bases": None,
                "base": "ubuntu@20.04",
                "platforms": {"not-a-valid-arch": None},
                "expected_exception": MatchesException(
                    CraftPlatformsBuildPlanError,
                    r"Failed to compute the build plan for base=.+",
                ),
            },
        ),
        (
            "unified missing build-on",
            {
                "bases": None,
                "base": "ubuntu@20.04",
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": [],
                        "build-for": ["amd64"],
                    },
                },
                "expected": [],
            },
        ),
        (
            "unified cross-compiling combinations, taking the first one",
            {
                "bases": None,
                "base": "ubuntu@20.04",
                "platforms": {
                    "ubuntu-cross": {
                        "build-on": ["amd64", "arm64"],
                        "build-for": ["riscv64"],
                    },
                },
                "expected": [("20.04", "amd64")],
                "expected_platforms": ["ubuntu-cross"],
            },
        ),
        (
            "unified base only with unsupported series",
            {
                "bases": None,
                "base": "ubuntu@99.99",
                "platforms": None,
                "expected": [],
            },
        ),
        (
            "unified base when base is dict",
            {
                "bases": None,
                "base": {"name": "ubuntu", "channel": "20.04"},
                "platforms": {
                    "ubuntu-amd64": {
                        "build-on": ["amd64"],
                        "build-for": ["amd64"],
                    },
                },
                "expected_exception": MatchesException(
                    BadPropertyError,
                    r"'base' must be a string, but got a dict: \{.+\}",
                ),
            },
        ),
        # No bases specified scenario
        (
            "no bases specified",
            {
                "bases": None,
                "base": None,
                "platforms": None,
                "expected": [
                    ("20.04", "amd64"),
                    ("20.04", "arm64"),
                    ("20.04", "riscv64"),
                ],
            },
        ),
    ]

    def test_parser(self):
        distro_serieses = [
            self.factory.makeDistroSeries(
                distribution=getUtility(ILaunchpadCelebrities).ubuntu,
                version=version,
            )
            for version in ("20.04", "18.04")
        ]
        supported_dases = []
        for arch_tag in ("amd64", "arm64", "riscv64"):
            try:
                processor = getUtility(IProcessorSet).getByName(arch_tag)
            except ProcessorNotFound:
                processor = self.factory.makeProcessor(
                    name=arch_tag, supports_virtualized=True
                )
            for distro_series in distro_serieses:
                supported_dases.append(
                    self.factory.makeDistroArchSeries(
                        distroseries=distro_series,
                        architecturetag=arch_tag,
                        processor=processor,
                    )
                )
        charmcraft_data = {}
        if getattr(self, "bases", None) is not None:
            charmcraft_data["bases"] = self.bases
        if getattr(self, "base", None) is not None:
            charmcraft_data["base"] = self.base
        if getattr(self, "platforms", None) is not None:
            charmcraft_data["platforms"] = self.platforms
        build_instances_factory = partial(
            determine_instances_to_build,
            charmcraft_data,
            supported_dases,
            distro_serieses[0],
        )
        if hasattr(self, "expected_exception"):
            self.assertThat(
                build_instances_factory, Raises(self.expected_exception)
            )
        else:
            result = build_instances_factory()
            # Assert the correct DistroArchSeries were selected for the build
            dases_only = [das for (_info, das) in result]
            self.assertThat(
                dases_only,
                MatchesListwise(
                    [
                        MatchesStructure(
                            distroseries=MatchesStructure.byEquality(
                                version=ver
                            ),
                            architecturetag=Equals(arch),
                        )
                        for ver, arch in self.expected
                    ]
                ),
            )
            # Assert the expected platform names (from BuildInfo.platform) are
            # returned correctly
            if hasattr(self, "expected_platforms"):
                expected_platforms = self.expected_platforms
            else:
                expected_platforms = [None] * len(self.expected)

            actual_platforms = [
                info.platform if info else None for (info, _das) in result
            ]
            self.assertEqual(expected_platforms, actual_platforms)


load_tests = load_tests_apply_scenarios
