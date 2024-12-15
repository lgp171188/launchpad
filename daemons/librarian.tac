# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# Twisted Application Configuration file.
# Use with "twistd2.4 -y <file.tac>", e.g. "twistd -noy server.tac"

import os

# Turn off the http_proxy environment variable if it is set. We
# don't need it, but we do need to contact Keystone & Swift directly.
# We could use no_proxy, but this requires keeping it in sync with
# reality on dev, staging & production servers.
if "http_proxy" in os.environ:
    del os.environ["http_proxy"]
if "HTTP_PROXY" in os.environ:
    del os.environ["HTTP_PROXY"]

from twisted.application import service, strports
from twisted.internet import reactor
from twisted.python import log
from twisted.scripts.twistd import ServerOptions
from twisted.web import server

from lp.services.config import config, dbconfig
from lp.services.daemons import readyservice
from lp.services.librarianserver import db, storage
from lp.services.librarianserver import web as fatweb
from lp.services.librarianserver.libraryprotocol import FileUploadFactory
from lp.services.scripts import execute_zcml_for_scripts
from lp.services.twistedsupport.features import setup_feature_controller
from lp.services.twistedsupport.loggingsupport import set_up_oops_reporting

# Connect to database
dbconfig.override(
    dbuser=config.librarian.dbuser,
    isolation_level=config.librarian.isolation_level,
)
# Note that this doesn't include *-configure-testing.zcml.  That doesn't
# matter today, but if it does at some point then we'll need to use a
# different ZCML file if config.isTestRunner() is true.
execute_zcml_for_scripts(
    scriptzcmlfilename="librarian.zcml", setup_interaction=False
)

# Allow use of feature flags.  Do this before setting up the Twisted
# application, in order to ensure that we switch to the correct database
# role before starting any threads.
setup_feature_controller("librarian")

if os.environ.get("LP_TEST_INSTANCE"):
    # Running in ephemeral mode: get the root dir from the environment and
    # dynamically allocate ports.
    path = os.environ["LP_LIBRARIAN_ROOT"]
else:
    path = config.librarian_server.root
if config.librarian_server.upstream_host:
    upstreamHost = config.librarian_server.upstream_host
    upstreamPort = config.librarian_server.upstream_port
    reactor.addSystemEventTrigger(
        "before",
        "startup",
        log.msg,
        "Using upstream librarian http://%s:%d" % (upstreamHost, upstreamPort),
    )
else:
    upstreamHost = upstreamPort = None
    reactor.addSystemEventTrigger(
        "before", "startup", log.msg, "Not using upstream librarian"
    )

application = service.Application("Librarian")
librarianService = service.IServiceCollection(application)

# Service that announces when the daemon is ready
readyservice.ReadyService().setServiceParent(librarianService)


def setUpListener(uploadPort, webPort, restricted):
    """Set up a librarian listener on the given ports.

    :param restricted: Should this be a restricted listener?  A restricted
        listener will serve only files with the 'restricted' file set and all
        files uploaded through the restricted listener will have that flag
        set.
    """
    librarian_storage = storage.LibrarianStorage(
        path, db.Library(restricted=restricted)
    )
    upload_factory = FileUploadFactory(librarian_storage)
    strports.service("tcp:%d" % uploadPort, upload_factory).setServiceParent(
        librarianService
    )
    root = fatweb.LibraryFileResource(
        librarian_storage, upstreamHost, upstreamPort
    )
    root.putChild(b"search", fatweb.DigestSearchResource(librarian_storage))
    root.putChild(b"robots.txt", fatweb.robotsTxt)
    site = server.Site(root)
    site.displayTracebacks = False
    strports.service("tcp:%d" % webPort, site).setServiceParent(
        librarianService
    )


if os.environ.get("LP_TEST_INSTANCE"):
    # Running in ephemeral mode: allocate ports on demand.
    setUpListener(0, 0, restricted=False)
    setUpListener(0, 0, restricted=True)
else:
    # Set up the public librarian.
    uploadPort = config.librarian.upload_port
    webPort = config.librarian.download_port
    setUpListener(uploadPort, webPort, restricted=False)
    # Set up the restricted librarian.
    webPort = config.librarian.restricted_download_port
    uploadPort = config.librarian.restricted_upload_port
    setUpListener(uploadPort, webPort, restricted=True)

# Log OOPS reports
options = ServerOptions()
options.parseOptions()
logfile = options.get("logfile")
observer = set_up_oops_reporting("librarian", "librarian", logfile)
application.addComponent(observer, ignoreClass=1)
