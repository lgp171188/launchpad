# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Main Launchpad WSGI application."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    "get_wsgi_application",
    ]

import logging

from zope.app.appsetup import appsetup
from zope.app.wsgi import WSGIPublisherApplication
from zope.event import notify
from zope.processlifetime import DatabaseOpened

from lp.services.config import config


def get_wsgi_application():
    features = []
    if config.launchpad.devmode:
        features.append("devmode")
        logging.warning(
            "Developer mode is enabled: this is a security risk and should "
            "NOT be enabled on production servers. Developer mode can be "
            "turned off in launchpad-lazr.conf.")
    appsetup.config("zcml/webapp.zcml", features=features)

    # We don't use ZODB, but the webapp subscribes to IDatabaseOpened to
    # perform some post-configuration tasks, so emit that event manually.
    notify(DatabaseOpened(None))

    return WSGIPublisherApplication()
