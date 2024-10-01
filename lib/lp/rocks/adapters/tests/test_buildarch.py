# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from functools import partial

from testscenarios import WithScenarios, load_tests_apply_scenarios
from testtools.matchers import (
    Equals,
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
from lp.rocks.adapters.buildarch import (
    RockBase,
    RockBaseConfiguration,
    determine_instances_to_build,
)
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.layers import LaunchpadZopelessLayer


class TestRockBaseConfiguration(WithScenarios, TestCase):

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
                    RockBase(
                        name="ubuntu", channel="18.04", architectures=["amd64"]
                    ),
                ],
                "expected_run_on": [
                    RockBase(
                        name="ubuntu",
                        channel="20.04",
                        architectures=["amd64", "arm64"],
                    ),
                    RockBase(
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
                    RockBase(name="ubuntu", channel="20.04")
                ],
                "expected_run_on": [RockBase(name="ubuntu", channel="20.04")],
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
                    RockBase(
                        name="ubuntu", channel="20.04", architectures=["amd64"]
                    ),
                ],
                "expected_run_on": [
                    RockBase(
                        name="ubuntu", channel="20.04", architectures=["amd64"]
                    ),
                ],
            },
        ),
    ]

    def test_base(self):
        config = RockBaseConfiguration.from_dict(self.base)
        self.assertEqual(self.expected_build_on, config.build_on)
        self.assertEqual(self.expected_run_on, config.run_on)


class TestDetermineInstancesToBuild(WithScenarios, TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    scenarios = [
        (
            "single entry, single arch",
            {
                "base": "ubuntu@18.04",
                "platforms": {
                    "amd64": None,
                },
                "expected": [("18.04", "amd64")],
            },
        ),
        (
            "single entry, multiple arches",
            {
                "base": "ubuntu@18.04",
                "platforms": {
                    "amd64": None,
                    "riscv64": None,
                },
                "expected": [("18.04", "amd64"), ("18.04", "riscv64")],
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
        rockcraft_data = {"base": self.base, "platforms": self.platforms}
        build_instances_factory = partial(
            determine_instances_to_build,
            rockcraft_data,
            dases,
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
