# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""WSGI archive authorisation provider.

This is as lightweight as possible, as it runs on PPA frontends.
"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'check_password',
    ]

import crypt
from random import SystemRandom
import string
import time

import six
from six.moves.xmlrpc_client import (
    Fault,
    ServerProxy,
    )

from lp.services.config import config
from lp.services.memcache.client import memcache_client_factory


def _get_archive_reference(environ):
    # Reconstruct the relevant part of the URL.  We don't care about where
    # we're installed.
    path = six.ensure_text(environ.get("SCRIPT_NAME") or "/", "ISO-8859-1")
    path_info = six.ensure_text(environ.get("PATH_INFO", ""), "ISO-8859-1")
    path += (path_info if path else path_info[1:])
    # Extract the first three segments of the path, and rearrange them to
    # form an archive reference.
    path_parts = path.lstrip("/").split("/")
    if len(path_parts) >= 3:
        return "~%s/%s/%s" % (path_parts[0], path_parts[2], path_parts[1])


_sr = SystemRandom()


def _crypt_sha256(word):
    """crypt.crypt(word, crypt.METHOD_SHA256), backported from Python 3.5."""
    saltchars = string.ascii_letters + string.digits + "./"
    salt = "$5$" + "".join(_sr.choice(saltchars) for _ in range(16))
    return crypt.crypt(word, salt)


_memcache_client = memcache_client_factory(timeline=False)


def check_password(environ, user, password):
    # We have almost no viable ways to set the config instance name.
    # Normally it's set in LPCONFIG in the process environment, but we can't
    # control that for mod_wsgi, and Apache SetEnv directives are
    # intentionally not passed through to the WSGI environment.  However, we
    # *can* control the application group via the application-group option
    # to WSGIAuthUserScript, and overloading that as the config instance
    # name actually makes a certain amount of sense, so use that if it's
    # available.
    application_group = environ.get("mod_wsgi.application_group")
    if application_group:
        config.setInstance(application_group)

    archive_reference = _get_archive_reference(environ)
    if archive_reference is None:
        return None
    memcache_key = "archive-auth:%s:%s" % (archive_reference, user)
    crypted_password = _memcache_client.get(memcache_key)
    if (crypted_password and
            crypt.crypt(password, crypted_password) == crypted_password):
        return True
    proxy = ServerProxy(config.personalpackagearchive.archive_api_endpoint)
    try:
        proxy.checkArchiveAuthToken(archive_reference, user, password)
        # Cache positive responses for a minute to reduce database load.
        _memcache_client.set(
            memcache_key, _crypt_sha256(password), time.time() + 60)
        return True
    except Fault as e:
        if e.faultCode == 410:  # Unauthorized
            return False
        else:
            # Interpret any other fault as NotFound (320).
            return None
