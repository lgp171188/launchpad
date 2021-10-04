# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Bazaar plugin to run the smart server on Launchpad.

Cribbed from bzrlib.builtins.cmd_serve from Bazaar 0.16.
"""

__all__ = [
    'cmd_launchpad_server',
    ]


import resource

from breezy import (
    lockdir,
    ui,
    )
from breezy.commands import (
    Command,
    register_command,
    )
from breezy.option import (
    Option,
    RegistryOption,
    )
from breezy.transport import (
    get_transport,
    transport_server_registry,
    )
import six


class cmd_launchpad_server(Command):
    """Run a Bazaar server that maps Launchpad branch URLs to the internal
    file-system format.
    """

    aliases = ['lp-serve']

    takes_options = [
        Option(
            'inet',
            help="serve on stdin/out for use from inetd or sshd"),
        Option(
            'port',
            help=(
                "listen for connections on nominated port of the form "
                "[hostname:]portnumber. Passing 0 as the port number will "
                "result in a dynamically allocated port. Default port is "
                " 4155."),
            type=str),
        Option(
            'upload-directory',
            help=(
                "upload branches to this directory. Defaults to "
                "config.codehosting.hosted_branches_root."),
            type=six.text_type),
        Option(
            'mirror-directory',
            help=(
                "serve branches from this directory. Defaults to "
                "config.codehosting.mirrored_branches_root.")),
        Option(
            'codehosting-endpoint',
            help=(
                "the url of the internal XML-RPC server. Defaults to "
                "config.codehosting.codehosting_endpoint."),
            type=six.text_type),
        RegistryOption(
            'protocol', help="Protocol to serve.",
            lazy_registry=('breezy.transport', 'transport_server_registry'),
            value_switches=True),
        ]

    takes_args = ['user_id']

    def run_server(self, smart_server):
        """Run the given smart server."""
        # for the duration of this server, no UI output is permitted.
        # note that this may cause problems with blackbox tests. This should
        # be changed with care though, as we dont want to use bandwidth
        # sending progress over stderr to smart server clients!
        old_factory = ui.ui_factory
        try:
            ui.ui_factory = ui.SilentUIFactory()
            smart_server.serve()
        finally:
            ui.ui_factory = old_factory

    def get_host_and_port(self, port):
        """Return the host and port to run the smart server on.

        If 'port' is None, None will be returned for the host and port.

        If 'port' has a colon in it, the string before the colon will be
        interpreted as the host.

        :param port: A string of the port to run the server on.
        :return: A tuple of (host, port), where 'host' is a host name or IP,
            and port is an integer TCP/IP port.
        """
        host = None
        if port is not None:
            if ':' in port:
                host, port = port.split(':')
            port = int(port)
        return host, port

    def run(self, user_id, port=None, branch_directory=None,
            codehosting_endpoint_url=None, inet=False, protocol=None):
        from lp.codehosting.bzrutils import install_oops_handler
        from lp.codehosting.vfs import (
            get_lp_server,
            hooks,
            )
        install_oops_handler(user_id)
        four_gig = int(4e9)
        resource.setrlimit(resource.RLIMIT_AS, (four_gig, four_gig))
        seen_new_branch = hooks.SetProcTitleHook()
        if protocol is None:
            protocol = transport_server_registry.get()
        lp_server = get_lp_server(
            int(user_id), codehosting_endpoint_url, branch_directory,
            seen_new_branch.seen)
        lp_server.start_server()
        try:
            old_lockdir_timeout = lockdir._DEFAULT_TIMEOUT_SECONDS
            lp_transport = get_transport(lp_server.get_url())
            host, port = self.get_host_and_port(port)
            lockdir._DEFAULT_TIMEOUT_SECONDS = 0
            try:
                protocol(lp_transport, host, port, inet)
            finally:
                lockdir._DEFAULT_TIMEOUT_SECONDS = old_lockdir_timeout
        finally:
            lp_server.stop_server()


register_command(cmd_launchpad_server)


def load_tests(standard_tests, module, loader):
    standard_tests.addTests(loader.loadTestsFromModuleNames(
        [__name__ + '.' + x for x in [
            'test_lpserve',
        ]]))
    return standard_tests
