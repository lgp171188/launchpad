# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from textwrap import dedent

from lp.code.interfaces.lpci import ILPCIConfiguration, LPCIConfigurationError
from lp.code.model.lpci import load_configuration
from lp.testing import TestCase


class TestLoadConfiguration(TestCase):
    def test_configuration_implements_interface(self):
        c = dedent(
            """\
        pipeline:
            - test
        jobs:
            test:
                series: focal
                architectures: [amd64]
        """
        )

        configuration = load_configuration(c)

        self.assertProvides(configuration, ILPCIConfiguration)

    def test_load_configuration_empty(self):
        self.assertRaisesWithContent(
            LPCIConfigurationError,
            "Empty configuration file",
            load_configuration,
            "",
        )

    def test_load_configuration_with_no_pipeline(self):
        c = dedent(
            """\
        jobs:
            test: {}
        """
        )

        self.assertRaisesWithContent(
            LPCIConfigurationError,
            "Configuration file does not declare 'pipeline'",
            load_configuration,
            c,
        )

    def test_load_configuration_with_pipeline_but_no_jobs(self):
        c = dedent(
            """\
        pipeline:
            - test
        """
        )

        self.assertRaisesWithContent(
            LPCIConfigurationError,
            "Configuration file does not declare 'jobs'",
            load_configuration,
            c,
        )

    def test_load_configuration_with_job_with_no_series(self):
        c = dedent(
            """\
        pipeline:
            - test
        jobs:
            test: {}
        """
        )

        self.assertRaisesWithContent(
            LPCIConfigurationError,
            "Job test:0 does not declare 'series'",
            load_configuration,
            c,
        )

    def test_load_configuration_with_job_with_no_architectures(self):
        c = dedent(
            """\
        pipeline:
            - test
        jobs:
            test:
                series: focal
        """
        )

        self.assertRaisesWithContent(
            LPCIConfigurationError,
            "Job test:0 does not declare 'architectures'",
            load_configuration,
            c,
        )

    def test_load_configuration_with_pipeline_and_jobs(self):
        c = dedent(
            """\
        pipeline:
            - [test, lint]
            - [publish]
        jobs:
            test:
                series: focal
                architectures: [amd64]
            lint:
                series: focal
                architectures: [amd64]
            publish:
                series: focal
                architectures: [amd64]
        """
        )

        configuration = load_configuration(c)

        self.assertEqual(
            [["test", "lint"], ["publish"]],
            configuration.pipeline,
        )
        self.assertEqual(
            {
                "test": [{"series": "focal", "architectures": ["amd64"]}],
                "lint": [{"series": "focal", "architectures": ["amd64"]}],
                "publish": [{"series": "focal", "architectures": ["amd64"]}],
            },
            configuration.jobs,
        )

    def test_expand_pipeline(self):
        # if `pipeline` is a string, it will be converted into a list
        c = dedent(
            """\
        pipeline:
            - test
        jobs:
            test:
                series: focal
                architectures: [amd64]
        """
        )

        configuration = load_configuration(c)

        self.assertEqual(
            [["test"]],
            configuration.pipeline,
        )
        self.assertEqual(
            {
                "test": [{"series": "focal", "architectures": ["amd64"]}],
            },
            configuration.jobs,
        )

    def test_expand_architectures(self):
        # if `architectures` is a string, it will be converted into a list
        c = dedent(
            """\
        pipeline:
            - [test]
        jobs:
            test:
                series: focal
                architectures: amd64
        """
        )

        configuration = load_configuration(c)

        self.assertEqual(
            [["test"]],
            configuration.pipeline,
        )
        self.assertEqual(
            {
                "test": [{"series": "focal", "architectures": ["amd64"]}],
            },
            configuration.jobs,
        )

    def test_expand_matrix(self):
        c = dedent(
            """\
        pipeline:
            - [test]
        jobs:
            test:
                matrix:
                    - series: bionic
                      architectures: amd64
                    - series: focal
                      architectures: [amd64, s390x]
        """
        )

        configuration = load_configuration(c)

        self.assertEqual(
            [["test"]],
            configuration.pipeline,
        )
        self.assertEqual(
            {
                "test": [
                    {"series": "bionic", "architectures": ["amd64"]},
                    {"series": "focal", "architectures": ["amd64", "s390x"]},
                ]
            },
            configuration.jobs,
        )
