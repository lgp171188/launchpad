# Copyright 2009-202 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# Twisted Application Configuration file.
# Use with "twistd2.4 -y <file.tac>", e.g. "twistd -noy server.tac"


from twisted.application import service
from twisted.scripts.twistd import ServerOptions

from lp.services.daemons import readyservice
from lp.services.scripts import execute_zcml_for_scripts
from lp.services.statsd.numbercruncher import NumberCruncher
from lp.services.twistedsupport.features import setup_feature_controller
from lp.services.twistedsupport.loggingsupport import RotatableFileLogObserver

execute_zcml_for_scripts()

# Allow use of feature flags.  Do this before setting up the Twisted
# application, in order to ensure that we switch to the correct database
# role before starting any threads.
setup_feature_controller("number-cruncher")

options = ServerOptions()
options.parseOptions()

application = service.Application("BuilddManager")
application.addComponent(
    RotatableFileLogObserver(options.get("logfile")), ignoreClass=1
)

# Service that announces when the daemon is ready.
readyservice.ReadyService().setServiceParent(application)


# Service for updating statsd receivers.
service = NumberCruncher()
service.setServiceParent(application)
