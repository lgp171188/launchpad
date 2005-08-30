#!/usr/bin/env python
""" Copyright Canonical Limited 2005
 Author: Daniel Silverstone <daniel.silverstone@canonical.com>
         Celso Providelo <celso.providelo@canonical.com>

Buildd-Slave monitor, support multiple slaves and requires LPDB access.
"""
from string import join
from sqlobject import SQLObjectNotFound

from canonical.lp import initZopeless
from canonical.launchpad.database import Builder

from twisted.internet import stdio
from twisted.protocols import basic
from twisted.internet import reactor, defer
from twisted.web.xmlrpc import Proxy

class BuilddSlaveMonitorApp:
    """Simple application class to expose some special methods and
    wrap to the RPC server.
    """
    def __init__(self, write):
        self.write = write

    def requestReceived(self, line):
        """Process requests typed in."""
        # identify empty ones
        if line.strip() == '':
            self.prompt()
            return
        request = line.strip().split()

        # select between local or remote method
        cmd = 'cmd_' + request[0]

        if hasattr(self, cmd):
            args = join(request[1:])
            meth = getattr(self, cmd)
            d = defer.maybeDeferred(meth, args)
            d.addCallbacks(self._printResult).addErrback(self._printError)
            return
        
        elif len(request) > 1:
            try:
                builder_id = request.pop(1)
                bid = int(builder_id)
                builder = Builder.get(bid)
            except ValueError:
                self.write('Wrong builder ID: %s' % builder_id)
            except SQLObjectNotFound:
                self.write('Builder Not Found: %s' % bid)
            else:
                slave = Proxy(builder.url.encode('ascii'))
                d = slave.callRemote(*request)
                d.addCallbacks(self._printResult).addErrback(self._printError)
                return
        else:
            self.write('Syntax Error: %s' % request)

        self.prompt()
        return
    
    def prompt(self):
        """Simple display a prompt according with current state."""
        self.write('\nbuildd-monitor>>> ')
            
    def cmd_quit(self, data=None):
        """Ohh my ! stops the reactor, i.e., QUIT, if requested.""" 
        reactor.stop()

    def cmd_builders(self, data=None):
        """Read access through initZopeless."""
        builders = Builder.select(orderBy='id')
        blist = 'List of Builders\n'
        for builder in builders:
            name = builder.name.encode('ascii')
            url = builder.url.encode('ascii')
            blist += '%s - %s - %s\n' % (builder.id, name, url)
        return blist
        
    def cmd_help(self, data=None):
        return ('Command Help\n'
                'builders - list available builders\n'
                'quit - exit the program\n'
                'Usage: <CMD> <BUILDERID> <ARGS>\n')
            
    def _printResult(self, result):
        """Callback for connections."""
        if result is None:
            return
        self.write('Got: %s' % str(result).strip())
        self.prompt()
            
    def _printError(self, error):
        """ErrBack for normal RPC transactions."""
        self.write('Error: ' + repr(error))
        self.prompt()

class BuilddSlaveMonitorProtocol(basic.LineReceiver):
    """Terminal Style Protocol"""
    # set local line delimiter
    from os import linesep as delimiter

    def connectionMade(self):
        """Setup the backend application and send welcome message."""
        self.app = BuilddSlaveMonitorApp(self.transport.write)
        self.transport.write('Welcome Buildd Slave Monitor\n>>> ')

    def lineReceived(self, line):
        """Use the Backend App to process each request."""
        self.app.requestReceived(line)

def main():
    """Setup the interactive interface with the respective protocol,
    and start the reactor.
    """
    stdio.StandardIO(BuilddSlaveMonitorProtocol())
    reactor.run()
    
if __name__ == '__main__':
    # for main, the only think to setup is the initZopeless
    # environment and the application wrapper. 
    initZopeless()
    main()
