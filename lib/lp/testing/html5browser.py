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

"""A Web browser that can be driven by an application."""

__metaclass__ = type
__all__ = [
    'Browser',
    'Command',
    ]

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('WebKit', '3.0')

from gi.repository import ( # noqa: E402
    GLib,
    Gtk,
    WebKit,
    )


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

    def __init__(self, show_window=False, hide_console_messages=True):
        super(Browser, self).__init__()
        self.show_window = show_window
        self.hide_console_messages = hide_console_messages
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

    def _setup_listening_operation(self, timeout, initial_timeout,
                                   incremental_timeout):
        """Setup a one-time listening operation for command's completion."""
        self._create_window()
        self.command = Command()
        self._last_status = None
        self._incremental_timeout = incremental_timeout
        self._connect(
            'status-bar-text-changed', self._on_status_bar_text_changed)
        self._timeout_source = GLib.timeout_add(timeout, self._on_timeout)
        if initial_timeout is None:
            initial_timeout = incremental_timeout
        if initial_timeout is not None:
            self._incremental_timeout_source = GLib.timeout_add(
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
                self._incremental_timeout_source = GLib.timeout_add(
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
            GLib.source_remove(self._incremental_timeout_source)
            self._incremental_timeout_source = None

    def _clear_timeout(self):
        if self._timeout_source is not None:
            GLib.source_remove(self._timeout_source)
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
            signals = list(self.listeners.keys())
        elif isinstance(signal, str):
            signals = [signal]
        for key in signals:
            self.disconnect(self.listeners[key])
            del self.listeners[key]
