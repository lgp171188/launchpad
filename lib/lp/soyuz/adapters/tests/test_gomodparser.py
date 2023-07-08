# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""go.mod parser tests."""

from lp.soyuz.adapters.gomodparser import GoModParserException, parse_go_mod
from lp.testing import TestCase
from lp.testing.layers import BaseLayer


class TestParseGoMod(TestCase):
    layer = BaseLayer

    def test_module_identifier(self):
        self.assertEqual(
            "example.com/foo/bar", parse_go_mod("module example.com/foo/bar\n")
        )

    def test_module_interpreted_string(self):
        self.assertEqual(
            "example.com/foo/bar",
            parse_go_mod('module "example\\.com\\/foo/bar"\n'),
        )

    def test_module_raw_string(self):
        self.assertEqual(
            "example.com/foo/bar",
            parse_go_mod("module `example.com/foo/bar`\n"),
        )

    def test_ignores_other_directives(self):
        self.assertEqual(
            "foo",
            parse_go_mod(
                "module foo\n"
                "\n"
                "go 1.18\n"
                "replace (\n"
                "\txyz v1 => ./a\n"
                "\txyz v2 => ./b\n"
                ")\n"
            ),
        )

    def test_parse_failed(self):
        self.assertRaisesWithContent(
            GoModParserException,
            "Parse failed at line 1, column 9",
            parse_go_mod,
            "module (",
        )

    def test_no_module_directive(self):
        self.assertRaisesWithContent(
            GoModParserException,
            "No 'module' directive found",
            parse_go_mod,
            "go 1.18\n",
        )
