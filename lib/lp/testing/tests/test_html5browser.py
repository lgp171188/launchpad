# Copyright (C) 2011 - Curtis Hovey <sinzui.is at verizon.net>
# This software is licensed under the MIT license (see the file COPYING).

from tempfile import NamedTemporaryFile
import unittest

from lp.testing import html5browser
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


class BrowserTestCase(unittest.TestCase):
    """Verify Browser methods."""

    def setUp(self):
        self.file = NamedTemporaryFile(prefix='html5browser_', suffix='.html')
        self.default_requires_external = html5browser.REQUIRES_EXTERNAL

    def tearDown(self):
        self.file.close()
        html5browser.REQUIRES_EXTERNAL = self.default_requires_external

    def test_init_default(self):
        browser = Browser()
        self.assertEqual(False, browser.show_window)
        self.assertEqual(True, browser.hide_console_messages)
        self.assertEqual(None, browser.command)
        self.assertEqual(None, browser.script)
        self.assertEqual(None, browser.browser_window)
        self.assertEqual(['console-message'], browser.listeners.keys())

    def test_init_show_browser(self):
        # The Browser can be set to show the window.
        browser = Browser(show_window=True)
        self.assertEqual(True, browser.show_window)

    def test_escape_script(self):
        # backslashes, newlines, and quotes are escaped for interpolation.
        self.assertEqual(
            r'backslash: \\', Browser.escape_script('backslash: \\'))
        self.assertEqual(
            r'newline: \n', Browser.escape_script('newline: \n'))
        self.assertEqual(
            r'double: \"', Browser.escape_script('double: "'))
        self.assertEqual(
            r"single: \'", Browser.escape_script("single: '"))

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
        self.assertEqual(None, command.content)

    def test_load_page_default_timeout_values(self):
        # Verify our expected class defaults.
        self.assertEqual(5000, Browser.TIMEOUT)
        self.assertEqual(None, Browser.INITIAL_TIMEOUT)
        self.assertEqual(None, Browser.INCREMENTAL_TIMEOUT)

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
        command = browser.load_page(self.file.name, timeout=1000)
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
        # A script that does sets window.status with a the prefix completes.
        browser = Browser()
        script = (
            "document.body.innerHTML = '<p>pting</p>';"
            "window.status = '::::' + document.body.innerText;")
        command = browser.run_script(script, timeout=1000)
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_SUCCESS, command.return_code)
        self.assertEqual('pting', command.content)

    def test_run_external_browser_set_window_status_returned(self):
        # When window status is set with leading ::::, the command ends.
        self.file.write(load_page_set_window_status_returned)
        self.file.flush()
        browser = Browser()
        browser.run_external_browser(self.file.name, Browser.TIMEOUT)
        command = browser.command
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_SUCCESS, command.return_code)
        self.assertEqual('fnord', command.content)

    def test_run_external_browser_set_window_status_ignored_non_command(self):
        # Setting window status without a leading :::: is ignored.
        self.file.write(load_page_set_window_status_ignores_non_commands)
        self.file.flush()
        browser = Browser()
        browser.run_external_browser(self.file.name, Browser.TIMEOUT)
        command = browser.command
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_SUCCESS, command.return_code)
        self.assertEqual('pting', command.content)

    def test_run_external_browser_timeout(self):
        # A page that does not set window.status in 5 seconds will timeout.
        self.file.write(timeout_page)
        browser = Browser()
        browser.run_external_browser(self.file.name, 1000)
        command = browser.command
        self.assertEqual(Command.STATUS_COMPLETE, command.status)
        self.assertEqual(Command.CODE_FAIL, command.return_code)
        self.assertEqual(5000, Browser.TIMEOUT)

    def test__on_console_message(self):
        # The method return the value of hide_console_messages.
        # You should not see "** Message: console message:" on stderr
        # when running this test.
        browser = Browser(hide_console_messages=True)
        script = (
            "console.log('hello');"
            "window.status = '::::goodbye;'")
        browser.run_script(script, timeout=1000)
        self.assertEqual(
            True,
            browser._on_console_message(browser, 'message', 1, None, None))

    def test_default_encoding(self):
        # The default enconding is ascii, which is corrupted by the import
        # for gtk from pygtk. There is a hack in place to ensure the default
        # encoding is ascii.
        test_data = ["100", "A-101", u'La Pe\xf1a']
        test_string = ','.join(test_data)
        self.assertRaises(UnicodeEncodeError, test_string.encode)

    def test_requires_external_process(self):
        html5browser.requires_external_process(True)
        self.assertEqual(True, html5browser.REQUIRES_EXTERNAL)
        html5browser.requires_external_process(False)
        self.assertEqual(False, html5browser.REQUIRES_EXTERNAL)
