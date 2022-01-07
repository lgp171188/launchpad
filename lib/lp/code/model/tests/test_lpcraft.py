# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os
from textwrap import dedent

from lp.code.model.lpcraft import load_configuration
from lp.testing import TestCase


class TestLoadConfiguration(TestCase):
    def create_configuration_file(self, s):
        path = os.path.join(self.makeTemporaryDirectory(), "launchpad.yaml")
        with open(path, "w") as f:
            f.write(s)
        return path

    def test_load_configuration_with_pipeline(self):
        c = dedent("""\
        pipeline:
            - test
        """)

        configuration = load_configuration(self.create_configuration_file(c))

        self.assertEqual(
            ["test"], configuration.pipeline
        )

    def test_load_configuration_with_pipeline_and_jobs(self):
        c = dedent("""\
        pipeline:
            - test
        jobs:
            test:
                series:
                    focal
            lint:
                series:
                    focal
            publish:
                series:
                    focal
        """)

        configuration = load_configuration(self.create_configuration_file(c))

        self.assertEqual(
            ["test"], configuration.pipeline,
        )

        self.assertEqual(
            {
                "test": [{'series': 'focal'}],
                "lint": [{'series': 'focal'}],
                "publish": [{'series': 'focal'}],
            }, configuration.jobs,
        )

    def test_expand_matrix(self):
        # if `architectures` is a string, it will be converted into a list
        c = dedent("""\
        pipeline:
            - test
        jobs:
            test:
                matrix:
                    - series: bionic
                      architectures: amd64
                    - series: focal
                      architectures: [amd64, s390x]
        """)

        configuration = load_configuration(self.create_configuration_file(c))

        self.assertEqual(
            ["test"], configuration.pipeline,
        )

        self.assertEqual(
            {
                'test': [
                    {'series': 'bionic', 'architectures': ['amd64']},
                    {'series': 'focal', 'architectures': ['amd64', 's390x']}
                ]
            },
            configuration.jobs,
        )
