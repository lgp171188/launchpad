#!/usr/bin/python3 -S
#
# Copyright 2009, 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
import _pythonpath  # noqa: F401

from lp.services.job.scripts.process_job_source import ProcessJobSource

if __name__ == "__main__":
    script = ProcessJobSource()
    # ProcessJobSource handles its own locking.
    script.run()
