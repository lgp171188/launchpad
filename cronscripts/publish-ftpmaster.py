#!/usr/bin/python3 -S
#
# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Master distro publishing script."""

import _pythonpath  # noqa: F401

from lp.archivepublisher.scripts.publish_ftpmaster import PublishFTPMaster


if __name__ == '__main__':
    script = PublishFTPMaster(
        "publish-ftpmaster", 'publish_ftpmaster')
    script.lock_and_run()
