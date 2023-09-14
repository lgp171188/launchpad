# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# Twisted Application Configuration file.
# Use with "twistd2.4 -y <file.tac>", e.g. "twistd -noy server.tac"

from twisted.application import service
from twisted.scripts.twistd import ServerOptions

from lp.buildmaster.manager import BuilddManager
from lp.services.config import dbconfig
from lp.services.daemons import readyservice
from lp.services.mail.sendmail import set_immediate_mail_delivery
from lp.services.scripts import execute_zcml_for_scripts
from lp.services.twistedsupport.features import setup_feature_controller
from lp.services.twistedsupport.loggingsupport import RotatableFileLogObserver

execute_zcml_for_scripts()
dbconfig.override(dbuser="buildd_manager", isolation_level="read_committed")
# XXX wgrant 2011-09-24 bug=29744: initZopeless used to do this.
# Should be removed from callsites verified to not need it.
set_immediate_mail_delivery(True)

# Allow use of feature flags.  Do this before setting up the Twisted
# application, in order to ensure that we switch to the correct database
# role before starting any threads.
setup_feature_controller("buildd-manager")

options = ServerOptions()
options.parseOptions()

application = service.Application("BuilddManager")
application.addComponent(
    RotatableFileLogObserver(options.get("logfile")), ignoreClass=1
)

# Service that announces when the daemon is ready.
readyservice.ReadyService().setServiceParent(application)

# Service for scanning buildd workers.
service = BuilddManager()
service.setServiceParent(application)
