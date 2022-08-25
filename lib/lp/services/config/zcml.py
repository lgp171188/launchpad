# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""ZCML directives relating to Launchpad configuration."""

__all__ = [
    "include_launchpad_overrides",
]

import os.path

from zope.configuration.xmlconfig import includeOverrides

from lp.services.config import config


def include_launchpad_overrides(context):
    """Include overrides depending on the Launchpad instance name."""
    includeOverrides(context, files=os.path.join(config.config_dir, "*.zcml"))
