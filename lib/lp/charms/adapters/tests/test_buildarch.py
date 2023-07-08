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
    CharmBase,
    CharmBaseConfiguration,
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
            "no bases specified",
            {
                "bases": None,
                "expected": [
                    ("20.04", "amd64"),
                    ("20.04", "arm64"),
                    ("20.04", "riscv64"),
                ],
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
    ]

    def test_parser(self):
        distro_serieses = [
            self.factory.makeDistroSeries(
                distribution=getUtility(ILaunchpadCelebrities).ubuntu,
                version=version,
            )
            for version in ("20.04", "18.04")
        ]
        dases = []
        for arch_tag in ("amd64", "arm64", "riscv64"):
            try:
                processor = getUtility(IProcessorSet).getByName(arch_tag)
            except ProcessorNotFound:
                processor = self.factory.makeProcessor(
                    name=arch_tag, supports_virtualized=True
                )
            for distro_series in distro_serieses:
                dases.append(
                    self.factory.makeDistroArchSeries(
                        distroseries=distro_series,
                        architecturetag=arch_tag,
                        processor=processor,
                    )
                )
        charmcraft_data = {}
        if self.bases is not None:
            charmcraft_data["bases"] = self.bases
        build_instances_factory = partial(
            determine_instances_to_build,
            charmcraft_data,
            dases,
            distro_serieses[0],
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
