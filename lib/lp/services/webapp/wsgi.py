# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Main Launchpad WSGI application."""

__all__ = [
    "get_wsgi_application",
    ]

import logging

from zope.app.wsgi import WSGIPublisherApplication
from zope.component.hooks import setHooks
from zope.configuration import xmlconfig
from zope.configuration.config import ConfigurationMachine
from zope.event import notify
from zope.interface import implementer
from zope.processlifetime import DatabaseOpened
from zope.security.interfaces import IParticipation
from zope.security.management import (
    endInteraction,
    newInteraction,
    system_user,
    )

from lp.services.config import config


@implementer(IParticipation)
class SystemConfigurationParticipation:

    principal = system_user
    interaction = None


def get_wsgi_application():
    # Loosely based on zope.app.appsetup.appsetup.
    features = []
    if config.launchpad.devmode:
        features.append("devmode")
        logging.warning(
            "Developer mode is enabled: this is a security risk and should "
            "NOT be enabled on production servers. Developer mode can be "
            "turned off in launchpad-lazr.conf.")

    # Set user to system_user, so we can do anything we want.
    newInteraction(SystemConfigurationParticipation())

    # Hook up custom component architecture calls.
    setHooks()

    # Load server-independent site config.
    context = ConfigurationMachine()
    xmlconfig.registerCommonDirectives(context)
    for feature in features:
        context.provideFeature(feature)
    context = xmlconfig.file("zcml/webapp.zcml", context=context)

    # Reset user.
    endInteraction()

    # We don't use ZODB, but the webapp subscribes to IDatabaseOpened to
    # perform some post-configuration tasks, so emit that event manually.
    notify(DatabaseOpened(None))

    return WSGIPublisherApplication()
