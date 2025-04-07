from pathlib import Path

from lp.testing import TestCase
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.script import run_script


class TestUCTImportScript(TestCase):
    """Test the TestUCTImportScript class."""

    layer = LaunchpadZopelessLayer

    def test_no_path_given(self):
        """TestUCTImportScript errors when no path given"""
        exit_code, out, err = run_script(
            script="scripts/uct-import.py",
            args=[],
        )
        self.assertEqual(2, exit_code)
        self.assertEqual("", out)
        self.assertEqual(
            "Usage: uct-import.py [options] PATH\n\nuct-import.py: "
            "error: Please specify a path to import\n",
            err,
        )

    def test_load_from_file(self):
        load_from = Path(__file__).parent / "sampledata" / "CVE-2022-23222"
        exit_code, out, err = run_script(
            script="scripts/uct-import.py",
            args=[str(load_from)],
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("", out)
        self.assertIn("CVE-2022-23222 was not imported", err)

    def test_load_from_directory(self):
        load_from = Path(__file__).parent / "sampledata"
        exit_code, out, err = run_script(
            script="scripts/uct-import.py",
            args=[str(load_from)],
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("", out)
        self.assertIn("CVE-2007-0255 was not imported", err)
        self.assertIn("CVE-2022-3219 was not imported", err)
        self.assertIn("CVE-2022-23222 was not imported", err)

    def test_dry_run_does_not_crash(self):
        load_from = Path(__file__).parent / "sampledata" / "CVE-2022-23222"
        exit_code, out, err = run_script(
            script="scripts/uct-import.py",
            args=[str(load_from), "--dry-run"],
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("", out)
        self.assertRegex(err, r"^INFO    Importing.*CVE-2022-23222.*")

    def test_filter_cve(self):
        load_from = Path(__file__).parent / "sampledata"
        exit_code, out, err = run_script(
            script="scripts/uct-import.py",
            args=[str(load_from), "--filter", "2007*"],
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("", out)
        self.assertNotIn("CVE-2022-23222 was not imported", err)
        self.assertIn("CVE-2007-0255 was not imported", err)

        exit_code, out, err = run_script(
            script="scripts/uct-import.py",
            args=[str(load_from), "--filter", "2022*"],
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("", out)
        self.assertIn("CVE-2022-23222 was not imported", err)
        self.assertIn("CVE-2022-3219 was not imported", err)
        self.assertNotIn("CVE-2007-0255 was not imported", err)

        exit_code, out, err = run_script(
            script="scripts/uct-import.py",
            args=[str(load_from), "--filter", "20[02][27]*"],
        )
        self.assertEqual(0, exit_code)
        self.assertEqual("", out)
        self.assertIn("CVE-2022-23222 was not imported", err)
        self.assertIn("CVE-2022-3219 was not imported", err)
        self.assertIn("CVE-2007-0255 was not imported", err)
