# Copyright 2004 Canonical Ltd.  All rights reserved.

from twisted.application import service, internet
from twisted.web import server
from twisted.enterprise.adbapi import ConnectionPool

from canonical.authserver.xmlrpc import UserDetailsResource
from canonical.authserver.database import DatabaseUserDetailsStorage
import canonical.lp


application = service.Application("authserver_test")
dbpool = ConnectionPool('psycopg', 'dbname=%s' % canonical.lp.dbname)
storage = DatabaseUserDetailsStorage(dbpool)
site = server.Site(UserDetailsResource(storage))
internet.TCPServer(9666, site).setServiceParent(application)

