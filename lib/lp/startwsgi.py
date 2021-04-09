# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""WSGI script to start web server."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = []

from zope.app.publication.httpfactory import HTTPPublicationRequestFactory
from zope.app.wsgi import getWSGIApplication
from zope.event import notify
import zope.processlifetime

from lp.services.config import config


application = getWSGIApplication(
    config.zope_config_file,
    requestFactory=HTTPPublicationRequestFactory
)

notify(zope.processlifetime.ProcessStarting())
