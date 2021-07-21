# Copyright (C) 2011 - Curtis Hovey <sinzui.is at verizon.net>
# Copyright 2020 Canonical Ltd.
#
# This software is licensed under the MIT license:
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from tempfile import NamedTemporaryFile

from lp.testing import TestCase
from lp.testing.html5browser import (
    Command,
    Browser,
    )


load_page_set_window_status_returned = """\
    <html><head>
    <script type="text/javascript">
    window.status = '::::fnord';
    </script>
    </head><body></body></html>
    """

incremental_timeout_page = """\
    <html><head>
    <script type="text/javascript">
    window.status = '>>>>shazam';
    </script>
    </head><body></body></html>
    """


load_page_set_window_status_ignores_non_commands = """\
    <html><head>
    <script type="text/javascript">
    window.status = 'snarf';
    </script>
    </head><body>
    <script type="text/javascript">
    window.status = '::::pting';
    </script>
    </body></html>
    """

timeout_page = """\
    <html><head></head><body></body></html>
    """

initial_long_wait_page = """\
    <html><head>
    <script type="text/javascript">
    setTimeout(function() {
      window.status = '>>>>initial';
      setTimeout(function() {window.status = '::::ended'}, 200);
    }, 1000);
    </script>
    </head><body></body></html>"""


class BrowserTestCase(TestCase):
    """Verify Browser methods."""

    def setUp(self):
        super(BrowserTestCase, self).setUp()
        self.file = NamedTemporaryFile(
            mode='w+', prefix='html5browser_', suffix='.html')
        self.addCleanup(self.file.close)

    def test_init_default(self):
        browser = Browser()
        self.assertFalse(browser.show_window)
        self.assertTrue(browser.hide_console_messages)
        self.assertIsNone(browser.command)
        self.assertIsNone(browser.script)
        self.assertIsNone(browser.browser_window)
        self.assertEqual(['console-message'], list(browser.listeners))

    def test_init_show_browser(self):
        # The Browser can be set to show the window.
        browser = Browser(show_window=True)
        self.assertTrue(browser.show_window)

    def test_load_page_set_window_status_returned(self):
        # When window status is set with leading ::::, the command ends.
        self.file.write(load_page_set_window_status_returned)
        self.file.flush()
        browser = Browser()
        command = browser.load_page(self.file.name)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_SUCCESS, command.return_code)
        self.assertEqual('fnord', command.content)
        self.assertEqual('::::', Browser.STATUS_PREFIX)

    def test_load_page_set_window_status_ignored_non_commands(self):
        # Setting window status without a leading :::: is ignored.
        self.file.write(load_page_set_window_status_ignores_non_commands)
        self.file.flush()
        browser = Browser()
        command = browser.load_page(self.file.name)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_SUCCESS, command.return_code)
        self.assertEqual('pting', command.content)

    def test_load_page_initial_timeout(self):
        # If a initial_timeout is set, it can cause a timeout.
        self.file.write(timeout_page)
        self.file.flush()
        browser = Browser()
        command = browser.load_page(
            self.file.name, initial_timeout=1000, timeout=30000)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_FAIL, command.return_code)

    def test_load_page_incremental_timeout(self):
        # If an incremental_timeout is set, it can cause a timeout.
        self.file.write(timeout_page)
        self.file.flush()
        browser = Browser()
        command = browser.load_page(
            self.file.name, incremental_timeout=1000, timeout=30000)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_FAIL, command.return_code)

    def test_load_page_initial_timeout_has_precedence_first(self):
        # If both an initial_timeout and an incremental_timeout are set,
        # initial_timeout takes precedence for the first wait.
        self.file.write(initial_long_wait_page)
        self.file.flush()
        browser = Browser()
        command = browser.load_page(
            self.file.name, initial_timeout=3000,
            incremental_timeout=500, timeout=30000)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_SUCCESS, command.return_code)
        self.assertEqual('ended', command.content)

    def test_load_page_incremental_timeout_has_precedence_second(self):
        # If both an initial_timeout and an incremental_timeout are set,
        # incremental_timeout takes precedence for the second wait.
        self.file.write(initial_long_wait_page)
        self.file.flush()
        browser = Browser()
        command = browser.load_page(
            self.file.name, initial_timeout=3000,
            incremental_timeout=100, timeout=30000)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_FAIL, command.return_code)
        self.assertEqual('initial', command.content)

    def test_load_page_timeout_always_wins(self):
        # If timeout, initial_timeout, and incremental_timeout are set,
        # the main timeout will still be honored.
        self.file.write(initial_long_wait_page)
        self.file.flush()
        browser = Browser()
        command = browser.load_page(
            self.file.name, initial_timeout=3000,
            incremental_timeout=3000, timeout=100)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_FAIL, command.return_code)
        self.assertIsNone(command.content)

    def test_load_page_default_timeout_values(self):
        # Verify our expected class defaults.
        self.assertEqual(5000, Browser.TIMEOUT)
        self.assertIsNone(Browser.INITIAL_TIMEOUT)
        self.assertIsNone(Browser.INCREMENTAL_TIMEOUT)

    def test_load_page_timeout(self):
        # A page that does not set window.status in 5 seconds will timeout.
        self.file.write(timeout_page)
        self.file.flush()
        browser = Browser()
        command = browser.load_page(self.file.name, timeout=1000)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_FAIL, command.return_code)

    def test_load_page_set_window_status_incremental_timeout(self):
        # Any incremental information is returned on a timeout.
        self.file.write(incremental_timeout_page)
        self.file.flush()
        browser = Browser()
        command = browser.load_page(
            self.file.name, timeout=30000, initial_timeout=30000,
            incremental_timeout=1000)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_FAIL, command.return_code)
        self.assertEqual('shazam', command.content)

    def test_run_script_timeout(self):
        # A script that does not set window.status in 5 seconds will timeout.
        browser = Browser()
        script = "document.body.innerHTML = '<p>fnord</p>';"
        command = browser.run_script(script, timeout=1000)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_FAIL, command.return_code)

    def test_run_script_complete(self):
        # A script that sets window.status with the status prefix completes.
        browser = Browser()
        script = (
            "document.body.innerHTML = '<p>pting</p>';"
            "window.status = '::::' + document.body.innerText;")
        command = browser.run_script(script, timeout=5000)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_SUCCESS, command.return_code)
        self.assertEqual('pting', command.content)

    def test__on_console_message(self):
        # The method returns the value of hide_console_messages.
        # You should not see "** Message: console message:" on stderr
        # when running this test.
        browser = Browser(hide_console_messages=True)
        script = (
            "console.log('hello');"
            "window.status = '::::goodbye;'")
        browser.run_script(script, timeout=5000)
        self.assertTrue(
            browser._on_console_message(browser, 'message', 1, None, None))
