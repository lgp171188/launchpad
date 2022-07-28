# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from tempfile import NamedTemporaryFile

from lp.testing import TestCase
from lp.testing.html5browser import Browser


class TestBrowser(TestCase):
    """Verify Browser methods."""

    def setUp(self):
        super().setUp()
        self.file = NamedTemporaryFile(
            mode="w+", prefix="html5browser_", suffix=".html"
        )
        self.file.write(
            """
            <html><head>
            <script type="text/javascript">
                // First test
                setTimeout(function() {
                    window.top.test_results = JSON.stringify({
                        testCase: "first",
                        testName: "first",
                        type: "passed"
                    });
                    // Second test
                    setTimeout(function() {
                        window.top.test_results = JSON.stringify({
                            testCase: "second",
                            testName: "second",
                            type: "passed"
                        });
                        // Final results
                        setTimeout(function() {
                            window.top.test_results = JSON.stringify({
                                results: {"spam": "ham"},
                                type: "complete"
                            });
                        }, 200);
                    }, 200);
                }, 100);
            </script>
            </head><body></body></html>
        """
        )
        self.file.flush()
        self.file_uri = "file://{}".format(self.file.name)
        self.addCleanup(self.file.close)
        self.browser = Browser()
        self.addCleanup(self.browser.close)

    def test_load_test_results(self):
        results = self.browser.run_tests(self.file_uri, timeout=1000)
        self.assertEqual(results.status, results.Status.SUCCESS)
        self.assertEqual(
            results.results,
            {
                "type": "complete",
                "results": {"spam": "ham"},
            },
        )

    def test_timeout_error(self):
        results = self.browser.run_tests(self.file_uri, timeout=250)
        self.assertEqual(results.status, results.Status.TIMEOUT)
        self.assertIsNone(results.results)
        self.assertEqual(
            results.last_test_message,
            {"testCase": "first", "testName": "first", "type": "passed"},
        )

    def test_incremental_timeout_success(self):
        results = self.browser.run_tests(
            self.file_uri, timeout=1000, incremental_timeout=300
        )
        self.assertEqual(results.status, results.Status.SUCCESS)
        self.assertEqual(
            results.results,
            {
                "type": "complete",
                "results": {"spam": "ham"},
            },
        )

    def test_incremental_timeout_error(self):
        results = self.browser.run_tests(
            self.file_uri, timeout=1000, incremental_timeout=150
        )
        self.assertEqual(results.status, results.Status.TIMEOUT)
        self.assertIsNone(results.results)
        self.assertEqual(
            results.last_test_message,
            {"testCase": "first", "testName": "first", "type": "passed"},
        )
