#!/usr/bin/python3
#
# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lp.services.scripts.base import LaunchpadCronScript


class HtaccessTokenGenerator(LaunchpadCronScript):
    """Expire archive subscriptions and deactivate invalid tokens."""

    # XXX cjwatson 2021-05-06: This script does nothing.  We no longer
    # generate .htaccess or .htpasswd files, but instead check archive
    # authentication dynamically; and garbo now handles expiring
    # subscriptions and deactivating tokens.  We can remove this script once
    # after `launchpad-ppa-publisher` charm is deployed to production

    def add_my_options(self):
        """Add script command line options."""
        self.parser.add_option(
            "-n",
            "--dry-run",
            action="store_true",
            dest="dryrun",
            default=False,
            help="If set, no files are changed and no tokens are "
            "deactivated.",
        )
        self.parser.add_option(
            "-d",
            "--no-deactivation",
            action="store_true",
            dest="no_deactivation",
            default=False,
            help="If set, tokens are not deactivated.",
        )

    def main(self):
        """Script entry point."""
        pass
