# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
#
# Portions from zope.app.wsgi, which is:
#
# Copyright (c) 2004 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.

"""Main Launchpad WSGI application."""

__all__ = [
    "get_wsgi_application",
]

import logging

from zope.app.publication.httpfactory import HTTPPublicationRequestFactory
from zope.component.hooks import setHooks
from zope.configuration import xmlconfig
from zope.configuration.config import ConfigurationMachine
from zope.event import notify
from zope.interface import implementer
from zope.processlifetime import DatabaseOpened
from zope.publisher.interfaces.logginginfo import ILoggingInfo
from zope.publisher.publish import publish
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


# Based on zope.app.wsgi.WSGIPublisherApplication, but with fewer
# dependencies.
class WSGIPublisherApplication:
    """A WSGI application implementation for the Zope publisher.

    Instances of this class can be used as a WSGI application object.

    The class relies on a properly initialized request factory.
    """

    def __init__(
        self, factory=HTTPPublicationRequestFactory, handle_errors=True
    ):
        self.requestFactory = None
        self.handleErrors = handle_errors
        # HTTPPublicationRequestFactory requires a "db" object, mainly for
        # ZODB integration.  This isn't useful in Launchpad, so just pass a
        # meaningless object.
        self.requestFactory = factory(object())

    def __call__(self, environ, start_response):
        """Called by a WSGI server.

        The ``environ`` parameter is a dictionary object, containing CGI-style
        environment variables. This object must be a builtin Python dictionary
        (not a subclass, UserDict or other dictionary emulation), and the
        application is allowed to modify the dictionary in any way it
        desires. The dictionary must also include certain WSGI-required
        variables (described in a later section), and may also include
        server-specific extension variables, named according to a convention
        that will be described below.

        The ``start_response`` parameter is a callable accepting two required
        positional arguments, and one optional argument. For the sake of
        illustration, we have named these arguments ``status``,
        ``response_headers``, and ``exc_info``, but they are not required to
        have these names, and the application must invoke the
        ``start_response`` callable using positional arguments
        (e.g. ``start_response(status, response_headers)``).
        """
        request = self.requestFactory(environ["wsgi.input"], environ)

        # Let's support post-mortem debugging
        handle_errors = environ.get("wsgi.handleErrors", self.handleErrors)

        request = publish(request, handle_errors=handle_errors)
        response = request.response
        # Get logging info from principal for log use
        logging_info = ILoggingInfo(request.principal, None)
        if logging_info is None:
            message = b"-"
        else:
            message = logging_info.getLogMessage()

        # Convert message bytes to native string
        message = message.decode("latin1")

        environ["wsgi.logging_info"] = message
        if "REMOTE_USER" not in environ:
            environ["REMOTE_USER"] = message

        # Start the WSGI server response
        start_response(response.getStatusString(), response.getHeaders())

        # Return the result body iterable.
        return response.consumeBodyIter()


def get_wsgi_application():
    # Loosely based on zope.app.appsetup.appsetup.
    features = []
    if config.launchpad.devmode:
        features.append("devmode")
        logging.warning(
            "Developer mode is enabled: this is a security risk and should "
            "NOT be enabled on production servers. Developer mode can be "
            "turned off in launchpad-lazr.conf."
        )

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
