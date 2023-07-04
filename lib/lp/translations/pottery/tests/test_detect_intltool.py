# Copyright 2009-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os
import tarfile
from textwrap import dedent

from breezy.controldir import ControlDir

from lp.services.config import config
from lp.testing import TestCase
from lp.testing.script import run_script
from lp.translations.pottery.detect_intltool import is_intltool_structure


class SetupTestPackageMixin:

    test_data_dir = "pottery_test_data"

    def prepare_package(self, packagename, buildfiles=None):
        """Unpack the specified package in a temporary directory.

        Change into the package's directory.

        :param packagename: The name of the package to prepare.
        :param buildfiles: A dictionary of path:content describing files to
            add to the package.
        """
        # First build the path for the package.
        packagepath = os.path.join(
            os.getcwd(),
            os.path.dirname(__file__),
            self.test_data_dir,
            packagename + ".tar.bz2",
        )
        # Then change into the temporary directory and unpack it.
        self.useTempDir()
        with tarfile.open(packagepath, "r|bz2") as tar:
            tar.extractall()
        os.chdir(packagename)

        if buildfiles is None:
            return

        # Add files as requested.
        for path, content in buildfiles.items():
            directory = os.path.dirname(path)
            if directory != "":
                try:
                    os.makedirs(directory)
                except FileExistsError:
                    # Doesn't matter if it already exists.
                    pass
            with open(path, "w") as the_file:
                the_file.write(content)

    def test_pottery_generate_intltool_script(self):
        # Let the script run to see it works fine.
        self.prepare_package("intltool_POTFILES_in_2")

        return_code, stdout, stderr = run_script(
            os.path.join(
                config.root,
                "scripts",
                "rosetta",
                "pottery-generate-intltool.py",
            )
        )

        self.assertEqual(0, return_code)
        self.assertEqual(
            dedent(
                """\
            module1/po/messages.pot
            po/messages.pot
            """
            ),
            stdout,
        )


class TestDetectIntltoolInBzrTree(TestCase, SetupTestPackageMixin):
    def prepare_tree(self):
        return ControlDir.create_standalone_workingtree(".")

    def test_detect_intltool_structure(self):
        # Detect a simple intltool structure.
        self.prepare_package("intltool_POTFILES_in_1")
        tree = self.prepare_tree()
        self.assertTrue(is_intltool_structure(tree))

    def test_detect_no_intltool_structure(self):
        # If no POTFILES.in exists, no intltool structure is assumed.
        self.prepare_package("intltool_POTFILES_in_1")
        os.remove("./po-intltool/POTFILES.in")
        tree = self.prepare_tree()
        self.assertFalse(is_intltool_structure(tree))

    def test_detect_intltool_structure_module(self):
        # Detect an intltool structure in subdirectories.
        self.prepare_package("intltool_POTFILES_in_2")
        tree = self.prepare_tree()
        self.assertTrue(is_intltool_structure(tree))
