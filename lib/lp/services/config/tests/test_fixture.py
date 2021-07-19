# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests of the config fixtures."""

__metaclass__ = type

import os.path
from textwrap import dedent

from lp.services.config import config
from lp.services.config.fixture import (
    ConfigFixture,
    ConfigMismatchError,
    ConfigUseFixture,
    )
from lp.testing import TestCase


class TestConfigUseFixture(TestCase):

    def test_sets_restores_instance(self):
        fixture = ConfigUseFixture('foo')
        orig_instance = config.instance_name
        fixture.setUp()
        try:
            self.assertEqual('foo', config.instance_name)
        finally:
            fixture.cleanUp()
        self.assertEqual(orig_instance, config.instance_name)


class TestConfigFixture(TestCase):

    def test_copies_and_derives(self):
        fixture = ConfigFixture('testtestconfig', 'testrunner')
        to_copy = [
            'test-process-lazr.conf',
            ]
        fixture.setUp()
        try:
            for base in to_copy:
                path = 'configs/testtestconfig/' + base
                source = 'configs/testrunner/' + base
                with open(source, 'rb') as f:
                    old = f.read()
                with open(path, 'rb') as f:
                    new = f.read()
                self.assertEqual(old, new)
            confpath = 'configs/testtestconfig/launchpad-lazr.conf'
            with open(confpath) as f:
                lazr_config = f.read()
            self.assertEqual(
                "[meta]\n"
                "extends: ../testrunner/launchpad-lazr.conf",
                lazr_config.strip())
        finally:
            fixture.cleanUp()

    def test_add_and_remove_section(self):
        fixture = ConfigFixture('testtestconfig', 'testrunner')
        fixture.setUp()
        try:
            confpath = 'configs/testtestconfig/launchpad-lazr.conf'
            with open(confpath) as f:
                lazr_config = f.read()
            self.assertEqual(dedent("""\
                [meta]
                extends: ../testrunner/launchpad-lazr.conf
                """), lazr_config)

            fixture.add_section(dedent("""\
                [test1]
                key: false
                """))
            with open(confpath) as f:
                lazr_config = f.read()
            self.assertEqual(dedent("""\
                [meta]
                extends: ../testrunner/launchpad-lazr.conf

                [test1]
                key: false
                """), lazr_config)

            fixture.add_section(dedent("""\
                [test2]
                key: true
                """))
            with open(confpath) as f:
                lazr_config = f.read()
            self.assertEqual(dedent("""\
                [meta]
                extends: ../testrunner/launchpad-lazr.conf

                [test1]
                key: false

                [test2]
                key: true
                """), lazr_config)

            fixture.remove_section(dedent("""\
                [test1]
                key: false
                """))
            with open(confpath) as f:
                lazr_config = f.read()
            self.assertEqual(dedent("""\
                [meta]
                extends: ../testrunner/launchpad-lazr.conf

                [test2]
                key: true
                """), lazr_config)
        finally:
            fixture.cleanUp()

    def test_remove_section_unexpected_value(self):
        fixture = ConfigFixture('testtestconfig', 'testrunner')
        fixture.setUp()
        try:
            confpath = os.path.abspath(
                'configs/testtestconfig/launchpad-lazr.conf')

            fixture.add_section(dedent("""\
                [test1]
                key: false
                """))

            self.assertRaisesWithContent(
                ConfigMismatchError,
                "Can't remove test1.key option from %s: "
                "expected value 'true', current value 'false'" % confpath,
                fixture.remove_section,
                dedent("""\
                    [test1]
                    key: true
                    """))
        finally:
            fixture.cleanUp()
