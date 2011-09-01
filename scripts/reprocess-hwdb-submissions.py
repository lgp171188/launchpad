#!/usr/bin/python -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0403

"""
Cron job that parses pending HWDB submissions.


Options:
    -m, --max-submissions: (optional) The maximum number of submissions
        which will be processed.

This script iterates over the HWDB submissions with the status
SUBMITTED, beginning with the oldest submissions, populate the
HWDB tables with the data from these submissions.

Properly processed submissions are set to the status PROCESSED;
submissions that cannot be processed are set to the status INVALID.
"""

import _pythonpath

from lp.services.scripts.base import LaunchpadScript
from lp.hardwaredb.scripts.hwdbsubmissions import (
    reprocess_invalid_submissions)


class HWDBSubmissionProcessor(LaunchpadScript):

    def add_my_options(self):
        """See `LaunchpadScript`."""
        self.parser.add_option(
            '-m', '--max-submissions',
            help='Limit the number of submissions which will be processed.')
        self.parser.add_option(
            '-w', '--warnings', action="store_true", default=False,
            help='Include warnings.')
        self.parser.add_option(
            '-s', '--start',
            help=('Process HWSubmission records having an id greater or '
                  'equal than this value.'))

    def main(self):
        max_submissions = self.options.max_submissions
        if max_submissions is not None:
            try:
                max_submissions = int(self.options.max_submissions)
            except ValueError:
                self.logger.error(
                    'Invalid value for --max_submissions specified: %r.'
                    % max_submissions)
                return
            if max_submissions <= 0:
                self.logger.error(
                    '--max_submissions must be a positive integer.')
                return
        if self.options.start is None:
            self.logger.error('Option --start not specified.')
            return
        try:
            start = int(self.options.start)
        except ValueError:
            self.logger.error('Option --start must have an integer value.')

        reprocess_invalid_submissions(
            self.txn, self.logger, max_submissions, self.warnings)

if __name__ == '__main__':
    script = HWDBSubmissionProcessor(
        'hwdbsubmissions', dbuser='hwdb-submission-processor')
    script.lock_and_run()
