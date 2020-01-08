#!/usr/bin/python -S
#
# Copyright 2009, 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lp.services.job.scripts import ProcessJobSource


if __name__ == '__main__':
    script = ProcessJobSource()
    script.lock_and_run()
