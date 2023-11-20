# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""CONNECT proxy to help on HTTPS connections when using twisted.

See https://twistedmatrix.com/trac/ticket/8806 (and reference
implementation at https://github.com/scrapy/scrapy/pull/397/files)."""

__all__ = [
    "TunnelError",
    "TunnelingAgent",
]

import re

from twisted.internet import defer
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.web.client import Agent


class TunnelError(Exception):
    """An HTTP CONNECT tunnel could not be established by the proxy."""


class TunnelingTCP4ClientEndpoint(TCP4ClientEndpoint):
    """An endpoint that tunnels through proxies to allow HTTPS requests.

    To accomplish that, this endpoint sends an HTTP CONNECT to the proxy.
    """

    _responseMatcher = re.compile(rb"HTTP/1\.. 200")

    def __init__(
        self,
        reactor,
        host,
        port,
        proxyConf,
        contextFactory,
        timeout=30,
        bindAddress=None,
    ):
        proxyHost, proxyPort, self._proxyAuthHeader = proxyConf
        super().__init__(reactor, proxyHost, proxyPort, timeout, bindAddress)
        self._tunneledHost = host
        self._tunneledPort = port
        self._contextFactory = contextFactory
        self._tunnelReadyDeferred = defer.Deferred()
        self._connectDeferred = None
        self._protocol = None

    def requestTunnel(self, protocol):
        """Asks the proxy to open a tunnel."""
        tunnelReq = b"CONNECT %s:%d HTTP/1.1\n" % (
            self._tunneledHost,
            self._tunneledPort,
        )
        if self._proxyAuthHeader:
            tunnelReq += b"Proxy-Authorization: %s\n" % self._proxyAuthHeader
        tunnelReq += b"\n"
        protocol.transport.write(tunnelReq)
        self._protocolDataReceived = protocol.dataReceived
        protocol.dataReceived = self.processProxyResponse
        self._protocol = protocol
        return protocol

    def processProxyResponse(self, bytes):
        """Processes the response from the proxy. If the tunnel is successfully
        created, notifies the client that we are ready to send requests. If not
        raises a TunnelError.
        """
        self._protocol.dataReceived = self._protocolDataReceived
        if TunnelingTCP4ClientEndpoint._responseMatcher.match(bytes):
            self._protocol.transport.startTLS(
                self._contextFactory, self._protocolFactory
            )
            self._tunnelReadyDeferred.callback(self._protocol)
        else:
            self._tunnelReadyDeferred.errback(
                TunnelError("Could not open CONNECT tunnel.")
            )

    def connectFailed(self, reason):
        """Propagates the errback to the appropriate deferred."""
        self._tunnelReadyDeferred.errback(reason)

    def connect(self, protocolFactory):
        self._protocolFactory = protocolFactory
        self._connectDeferred = super().connect(protocolFactory)
        self._connectDeferred.addCallback(self.requestTunnel)
        self._connectDeferred.addErrback(self.connectFailed)
        return self._tunnelReadyDeferred


class TunnelingAgent(Agent):
    """An agent that uses a L{TunnelingTCP4ClientEndpoint} to make HTTPS
    requests.
    """

    def __init__(
        self,
        reactor,
        proxyConf,
        contextFactory=None,
        connectTimeout=None,
        bindAddress=None,
        pool=None,
    ):
        super().__init__(
            reactor, contextFactory, connectTimeout, bindAddress, pool
        )
        self._contextFactory = contextFactory
        self._connectTimeout = connectTimeout
        self._bindAddress = bindAddress
        self._proxyConf = proxyConf

    def _getEndpoint(self, url):
        return TunnelingTCP4ClientEndpoint(
            self._reactor,
            url.host,
            url.port,
            self._proxyConf,
            self._contextFactory,
            self._connectTimeout,
            self._bindAddress,
        )
