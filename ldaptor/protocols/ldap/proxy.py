"""LDAP protocol proxy server"""

from twisted.internet import reactor, defer
from ldaptor.protocols.ldap import ldapserver, ldapconnector, ldapclient
from ldaptor.protocols import pureldap

class Proxy(ldapserver.BaseLDAPServer):
    protocol = ldapclient.LDAPClient

    client = None
    waitingConnect = []

    def __init__(self, overrides):
        ldapserver.BaseLDAPServer.__init__(self)
        self.overrides=overrides

    def _cbConnectionMade(self, proto):
        self.client = proto
        while self.waitingConnect:
            request, controls, reply = self.waitingConnect.pop(0)
            self._clientQueue(request, controls, reply)

    def _clientQueue(self, request, controls, reply):
        # TODO controls
        if request.needs_answer:
            self.client.queue(request, self._gotResponse, reply)
        else:
            self.client.queue(request)

    def _gotResponse(self, response, reply):
        reply(response)
        return isinstance(response, (
            pureldap.LDAPSearchResultDone,
            pureldap.LDAPBindResponse,
            ))

    def _failConnection(self, reason):
        #TODO self.loseConnection()
        return reason # TODO

    def connectionMade(self):
        clientCreator = ldapconnector.LDAPClientCreator(
            reactor, self.protocol)
        d = clientCreator.connect(dn='', overrides=self.overrides)
        d.addCallback(self._cbConnectionMade)
        d.addErrback(self._failConnection)

        ldapserver.BaseLDAPServer.connectionMade(self)

    def connectionLost(self, reason):
        assert self.client is not None
        if self.client.connected:
            self.client.unbind()
        self.client = None
        ldapserver.BaseLDAPServer.connectionLost(self, reason)

    def _handleUnknown(self, request, controls, reply):
        if self.client is None:
            self.waitingConnect.append((request, controls, reply))
        else:
            self._clientQueue(request, controls, reply)
        return None

    def handleUnknown(self, request, controls, reply):
        d = defer.succeed(request)
        d.addCallback(self._handleUnknown, controls, reply)
        return d


if __name__ == '__main__':
    """
    Demonstration LDAP proxy; passes all requests to localhost:389.
    """
    from twisted.internet import reactor, protocol
    from twisted.python import log
    import sys
    log.startLogging(sys.stderr)

    factory = protocol.ServerFactory()
    factory.protocol = lambda : Proxy(overrides={
        '': ('localhost', 389),
        })
    reactor.listenTCP(10389, factory)
    reactor.run()
