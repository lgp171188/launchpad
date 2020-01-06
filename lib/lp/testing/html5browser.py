#!/usr/bin/python
"""A Web browser that can be driven by an application."""

__metaclass__ = type
__all__ = [
    'Browser',
    'Command',
    ]

import platform
import os
import subprocess
import sys

arch = platform.architecture()[0]
dist = platform.linux_distribution()[2]

# Suppress accessibility warning because the test runner does not have UI.
os.environ['GTK_MODULES'] = ''
use_pygkt = (
    dist == 'lucid' or os.environ.get('HTML5BROWSER_USE_PYGTK') == 'true')

if not use_pygkt:
    from gi.repository import GObject
    from gi.repository  import Gtk
    from gi.repository import WebKit
    # Hush lint
    GObject, Gtk, WebKit
else:
    # Support for lucid.
    import pygtk
    pygtk.require("2.0")
    import glib as GObject
    import gtk as Gtk
    import webkit as WebKit
    # XXX sinzui 2011-06-16 LP:27112:
    # This evil encoding fix undoes the evil done by import gtk.
    reload(sys)
    sys.setdefaultencoding('ascii')

HERE = __file__
REQUIRES_EXTERNAL = False
if arch == '64bit' and dist in ('natty', 'oneiric'):
    REQUIRES_EXTERNAL = True


def requires_external_process(requires_external):
    """Run the browser in an external process.

    Some 64bit architecture experience segfaults when a process uses
    multiple browsers. Set this to true to run each browser in a stable
    subprocess. See LP:800741.
    """
    global REQUIRES_EXTERNAL
    REQUIRES_EXTERNAL = requires_external


class Command:
    """A representation of the status and result of a command."""
    STATUS_RUNNING = object()
    STATUS_COMPLETE = object()

    CODE_UNKNOWN = -1
    CODE_SUCCESS = 0
    CODE_FAIL = 1

    def __init__(self, status=STATUS_RUNNING, return_code=CODE_UNKNOWN,
                 content=None):
        self.status = status
        self.return_code = return_code
        self.content = content


class Browser(WebKit.WebView):
    """A browser that can be driven by an application."""

    STATUS_PREFIX = '::::'
    TIMEOUT = 5000
    INCREMENTAL_PREFIX = '>>>>'
    INITIAL_TIMEOUT = None
    INCREMENTAL_TIMEOUT = None

    def __init__(self, show_window=False, hide_console_messages=True,
                 force_internal=False):
        super(Browser, self).__init__()
        self.show_window = show_window
        self.hide_console_messages = hide_console_messages
        self.force_internal = force_internal
        self.browser_window = None
        self.script = None
        self.command = None
        self.listeners = {}
        self._connect('console-message', self._on_console_message, False)

    def load_page(self, uri,
                  timeout=TIMEOUT,
                  initial_timeout=INITIAL_TIMEOUT,
                  incremental_timeout=INCREMENTAL_TIMEOUT):
        """Load a page and return the content."""
        if REQUIRES_EXTERNAL and not self.force_internal:
            self.run_external_browser(
                uri, timeout, initial_timeout, incremental_timeout)
        else:
            self._setup_listening_operation(
                timeout, initial_timeout, incremental_timeout)
            if uri.startswith('/'):
                uri = 'file://' + uri
            self.load_uri(uri)
            Gtk.main()
        return self.command

    def run_script(self, script,
                   timeout=TIMEOUT,
                   initial_timeout=INITIAL_TIMEOUT,
                   incremental_timeout=INCREMENTAL_TIMEOUT):
        """Run a script and return the result."""
        self._setup_listening_operation(
            timeout, initial_timeout, incremental_timeout)
        self.script = script
        self._connect('notify::load-status', self._on_script_load_finished)
        self.load_string(
            '<html><head></head><body></body></html>',
            'text/html', 'UTF-8', 'file:///')
        Gtk.main()
        return self.command

    def run_external_browser(self, uri, timeout,
                             initial_timeout=None, incremental_timeout=None):
        """Load the page and run the script in an external process."""
        self.command = Command()
        command_line = ['python', HERE, '-t', str(timeout)]
        if initial_timeout is not None:
            command_line.extend(['-i', str(initial_timeout)])
        if incremental_timeout is not None:
            command_line.extend(['-s', str(incremental_timeout)])
        command_line.append(uri)
        browser = subprocess.Popen(
            command_line, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        content, ignore = browser.communicate()
        self.command.status = Command.STATUS_COMPLETE
        self.command.content = content.strip()
        if browser.returncode == 1:
            self.command.return_code = Command.CODE_FAIL
        else:
            self.command.return_code = Command.CODE_SUCCESS

    @staticmethod
    def escape_script(text):
        """Escape the text so that it can be interpolated in to JS."""
        return text.replace(
            '\\', '\\\\').replace('"', '\\"').replace("'", "\\'").replace(
            '\n', '\\n')

    def _setup_listening_operation(self, timeout, initial_timeout,
                                   incremental_timeout):
        """Setup a one-time listening operation for command's completion."""
        self._create_window()
        self.command = Command()
        self._last_status = None
        self._incremental_timeout = incremental_timeout
        self._connect(
            'status-bar-text-changed', self._on_status_bar_text_changed)
        self._timeout_source = GObject.timeout_add(timeout, self._on_timeout)
        if initial_timeout is None:
            initial_timeout = incremental_timeout
        if initial_timeout is not None:
            self._incremental_timeout_source = GObject.timeout_add(
                initial_timeout, self._on_timeout)
        else:
            self._incremental_timeout_source = None

    def _create_window(self):
        """Create a window needed to render pages."""
        if self.browser_window is not None:
            return
        self.browser_window = Gtk.Window()
        self.browser_window.set_default_size(800, 600)
        self.browser_window.connect("destroy", self._on_quit)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self)
        self.browser_window.add(scrolled)
        if self.show_window:
            self.browser_window.show_all()

    def _on_quit(self, widget=None):
        Gtk.main_quit()

    def _clear_status(self):
            self.execute_script('window.status = "";')

    def _on_status_bar_text_changed(self, view, text):
        if text.startswith(self.INCREMENTAL_PREFIX):
            self._clear_incremental_timeout()
            self._clear_status()
            self._last_status = text[4:]
            if self._incremental_timeout:
                self._incremental_timeout_source = GObject.timeout_add(
                    self._incremental_timeout, self._on_timeout)
        elif text.startswith(self.STATUS_PREFIX):
            self._clear_timeout()
            self._clear_incremental_timeout()
            self._disconnect('status-bar-text-changed')
            self._clear_status()
            self.command.status = Command.STATUS_COMPLETE
            self.command.return_code = Command.CODE_SUCCESS
            self.command.content = text[4:]
            self._on_quit()

    def _on_script_load_finished(self, view, load_status):
        # pywebkit does not have WebKit.LoadStatus.FINISHED.
        statuses = ('WEBKIT_LOAD_FINISHED', 'WEBKIT_LOAD_FAILED')
        if self.props.load_status.value_name not in statuses:
            return
        self._disconnect('notify::load-status')
        self.execute_script(self.script)
        self.script = None

    def _clear_incremental_timeout(self):
        if self._incremental_timeout_source is not None:
            GObject.source_remove(self._incremental_timeout_source)
            self._incremental_timeout_source = None

    def _clear_timeout(self):
        if self._timeout_source is not None:
            GObject.source_remove(self._timeout_source)
            self._timeout_source = None

    def _on_timeout(self):
        self._clear_timeout()
        self._clear_incremental_timeout()
        if self.command.status is not Command.STATUS_COMPLETE:
            self._disconnect()
            self.command.status = Command.STATUS_COMPLETE
            self.command.return_code = Command.CODE_FAIL
            self.command.content = self._last_status
            self._on_quit()
        return False

    def _on_console_message(self, view, message, line_no, source_id, data):
        return self.hide_console_messages

    def _connect(self, signal, callback, *args):
        self.listeners[signal] = self.connect(signal, callback, *args)

    def _disconnect(self, signal=None):
        if signal is None:
            signals = self.listeners.keys()
        elif isinstance(signal, basestring):
            signals = [signal]
        for key in signals:
            self.disconnect(self.listeners[key])
            del self.listeners[key]


from optparse import OptionParser


def main(argv=None):
    """Load a page an return the result set by a page script."""
    if argv is None:
        argv = sys.argv
    (options, uri) = parser_options(args=argv[1:])
    client = Browser(force_internal=True)
    page = client.load_page(uri, timeout=options.timeout,
                            initial_timeout=options.initial_timeout,
                            incremental_timeout=options.incremental_timeout)
    has_page_content = page.content is not None and page.content.strip() != ''
    if has_page_content:
        print page.content
    if page.return_code == page.CODE_FAIL:
        sys.exit(1)
    elif not has_page_content:
        sys.exit(2)
    else:
        sys.exit(0)


def parser_options(args):
    """Return the option parser for this program."""
    usage = "usage: %prog [options] uri"
    epilog = (
        'Return codes: 0 Success, '
        '1 Script failed to execute, '
        '2 Script returned nothing.')
    parser = OptionParser(usage=usage, epilog=epilog)
    parser.add_option(
        "-t", "--timeout", type="int", dest="timeout")
    parser.add_option(
        "-i", "--initial-timeout", type="int", dest="initial_timeout")
    parser.add_option(
        "-s", "--test-timeout", type="int", dest="incremental_timeout")
    parser.set_defaults(timeout=Browser.TIMEOUT)
    (options, uris) = parser.parse_args(args)
    if len(uris) != 1:
        parser.error("Expected a uri.")
    return options, uris[0]


if __name__ == '__main__':
    main()
