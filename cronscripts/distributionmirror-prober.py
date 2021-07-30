#!/usr/bin/python3 -S
#
# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to probe distribution mirrors and check how up-to-date they are."""

import _pythonpath  # noqa: F401

from lp.registry.interfaces.distributionmirror import MirrorContent
from lp.registry.scripts.distributionmirror_prober import DistroMirrorProber
from lp.services.config import config
from lp.services.scripts.base import (
    LaunchpadCronScript,
    LaunchpadScriptFailure,
    )
from lp.services.timeout import set_default_timeout_function


class DistroMirrorProberScript(LaunchpadCronScript):
    usage = ('%prog --content-type=(archive|cdimage) [--force] '
             '[--no-owner-notification] [--max-mirrors=N]')

    def add_my_options(self):
        self.parser.add_option('--content-type',
            dest='content_type', default=None, action='store',
            help='Probe only mirrors of the given type')
        self.parser.add_option('--force',
            dest='force', default=False, action='store_true',
            help='Force the probing of mirrors that were probed recently')
        self.parser.add_option('--no-owner-notification',
            dest='no_owner_notification', default=False, action='store_true',
            help='Do not send failure notification to mirror owners.')
        self.parser.add_option('--no-remote-hosts',
            dest='no_remote_hosts', default=False, action='store_true',
            help='Do not try to connect to any host other than localhost.')
        self.parser.add_option('--max-mirrors',
            dest='max_mirrors', default=None, action='store', type="int",
            help='Only probe N mirrors.')

        # IMPORTANT: Don't change this unless you really know what you're
        # doing. Using a too big value can cause spurious failures on lots of
        # mirrors and a too small one can cause the prober to run for hours.
        self.parser.add_option('--max-parallel-per-host',
            dest='max_parallel_per_host', default=2,
            action='store', type="int",
            help='Keep maximum N parallel requests per host at a time.'
                 ' (default=2)')

        # We limit the overall number of simultaneous requests as well to
        # prevent them from stalling and timing out before they even get a
        # chance to start connecting.
        self.parser.add_option('--max-parallel',
            dest='max_parallel', default=100,
            action='store', type="int",
            help='Keep maximum N parallel requests at a time (default=100).')

    def main(self):
        if self.options.content_type == 'archive':
            content_type = MirrorContent.ARCHIVE
        elif self.options.content_type == 'cdimage':
            content_type = MirrorContent.RELEASE
        else:
            raise LaunchpadScriptFailure(
                'Wrong value for argument --content-type: %s'
                % self.options.content_type)

        set_default_timeout_function(
            lambda: config.distributionmirrorprober.timeout)
        DistroMirrorProber(self.txn, self.logger).probe(
            content_type, self.options.no_remote_hosts, self.options.force,
            self.options.max_mirrors, not self.options.no_owner_notification,
            self.options.max_parallel, self.options.max_parallel_per_host)


if __name__ == '__main__':
    script = DistroMirrorProberScript(
        'distributionmirror-prober',
        dbuser=config.distributionmirrorprober.dbuser)
    script.lock_and_run(isolation='autocommit')
