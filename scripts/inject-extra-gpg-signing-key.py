#!/usr/bin/python3 -S
# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to inject an extra archive GPG signing key into signing service."""

import _pythonpath  # noqa: F401

from lp.archivepublisher.scripts.inject_extra_gpg_signing_key import (
    InjectExtraGPGSigningKeyScript,
)
from lp.services.config import config

if __name__ == "__main__":
    script = InjectExtraGPGSigningKeyScript(
        "inject-extra-gpg-signing-key", dbuser=config.archivepublisher.dbuser
    )
    script.lock_and_run()
