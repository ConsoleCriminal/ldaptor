# Twisted, the Framework of Your Internet
# Copyright (C) 2001 Matthew W. Lefkowitz
# 
# This library is free software; you can redistribute it and/or
# modify it under the terms of version 2.1 of the GNU Lesser General Public
# License as published by the Free Software Foundation.
# 
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""LDAP protocol client"""

from ldaptor.protocols import pureldap, pureber
from ldaptor.protocols.ldap import ldaperrors

from twisted.python import mutablestring, log
from twisted.python.failure import Failure
from twisted.internet import protocol, defer
from ldaptor.samba import smbpassword

class LDAPClientConnectionLostException(ldaperrors.LDAPException):
    pass

class LDAPClient(protocol.Protocol):
    """An LDAP client"""

    def __init__(self):
        self.onwire = {}
        self.buffer = mutablestring.MutableString()
        self.connected = None

    berdecoder = pureldap.LDAPBERDecoderContext_LDAPMessage(
        inherit=pureldap.LDAPBERDecoderContext(
        fallback=pureber.BERDecoderContext()))

    def dataReceived(self, recd):
        self.buffer.append(recd)
        while 1:
            try:
                o=pureber.ber2object(self.berdecoder, self.buffer)
            except pureldap.BERExceptionInsufficientData:
                o=None
            if not o:
                break
            self.handle(o)

    def connectionMade(self):
        """TCP connection has opened"""
        self.connected = 1

    def connectionLost(self, reason):
        """Called when TCP connection has been lost"""
        self.connected = 0

    def queue(self, op, handler=None):
        if not self.connected:
            raise "Not connected (TODO)" #TODO make this a real object
        msg=pureldap.LDAPMessage(op)
        #log.msg('-> %s' % repr(msg))
        assert not self.onwire.has_key(msg.id)
        assert op.needs_answer or not handler
        if op.needs_answer:
            self.onwire[msg.id]=handler
        self.transport.write(str(msg))

    def unsolicitedNotification(self, msg):
        log.msg("Got unsolicited notification: %s" % repr(msg))

    def handle(self, msg):
        assert isinstance(msg.value, pureldap.LDAPProtocolResponse)
        #log.msg('<- %s' % repr(msg))

        if msg.id==0:
            self.unsolicitedNotification(msg.value)
        else:
            handler = self.onwire[msg.id]
            
            # Return true to mark request as fully handled
            if handler==None or handler(msg.value):
                del self.onwire[msg.id]


    ##Bind
    def bind(self, dn='', auth=''):
        d=defer.Deferred()
        if not self.connected:
            d.errback(Failure(
                ldaperrors.LDAPClientConnectionLostException()))
        else:
            r=pureldap.LDAPBindRequest(dn=dn, auth=auth)
            self.queue(r, d.callback) #TODO queue needs info back from callback!!!
            d.addCallback(self._handle_bind_msg)
        return d

    def _handle_bind_msg(self, resp):
        assert isinstance(resp, pureldap.LDAPBindResponse)
        assert resp.referral==None #TODO
        if resp.resultCode==0:
            return (resp.matchedDN, resp.serverSaslCreds)
        else:
            raise Failure(
                ldaperrors.get(resp.resultCode, resp.errorMessage))

    ##Unbind
    def unbind(self):
        if not self.connected:
            raise "Not connected (TODO)" #TODO make this a real object
        r=pureldap.LDAPUnbindRequest()
        self.queue(r)
        self.transport.loseConnection()


    ##Search is externalized into class LDAPSearch
        

class LDAPOperation:
    def __init__(self, client):
        self.client=client

class LDAPSearch(LDAPOperation):
    def __init__(self,
                 deferred,
                 client,
                 baseObject='',
                 scope=pureldap.LDAP_SCOPE_wholeSubtree,
                 derefAliases=pureldap.LDAP_DEREF_neverDerefAliases,
                 sizeLimit=0,
                 timeLimit=0,
                 typesOnly=0,
                 filter=pureldap.LDAPFilterMatchAll,
                 attributes=[],
                 ):
        LDAPOperation.__init__(self, client)
        self.deferred=deferred
        r=pureldap.LDAPSearchRequest(baseObject=baseObject,
                                     scope=scope,
                                     derefAliases=derefAliases,
                                     sizeLimit=sizeLimit,
                                     timeLimit=timeLimit,
                                     typesOnly=typesOnly,
                                     filter=filter,
                                     attributes=attributes)
        self.client.queue(r, self.handle_msg)

    def handle_msg(self, msg):
        if isinstance(msg, pureldap.LDAPSearchResultDone):
            assert msg.referral==None #TODO
            if msg.resultCode==0: #TODO ldap.errors.success
                assert msg.matchedDN==''
                self.deferred.callback(self)
            else:
                self.deferred.errback(Failure(
                    ldaperrors.get(msg.resultCode, msg.errorMessage)))
            return 1
        else:
            assert isinstance(msg, pureldap.LDAPSearchResultEntry)
            self.handle_entry(msg.objectName, msg.attributes)
            return 0
            
    def handle_entry(self, objectName, attributes):
        pass

class LDAPModifyAttributes(LDAPOperation):
    def __init__(self,
                 client,
                 object,
                 modification):
        """
        Request modification of LDAP attributes.

        object is a string representation of the object DN.

        modification is a list of LDAPModifications
        """

        LDAPOperation.__init__(self, client)
        r=pureldap.LDAPModifyRequest(object=object,
                                     modification=modification)
        self.client.queue(r, self.handle_msg)

    def handle_msg(self, msg):
        assert isinstance(msg, pureldap.LDAPModifyResponse)
        assert msg.referral==None #TODO
        if msg.resultCode==0: #TODO ldap.errors.success
            assert msg.matchedDN==''
            self.handle_success()
            return 1
        else:
            self.handle_fail(Failure(
                ldaperrors.get(msg.resultCode, msg.errorMessage)))
            return 1
            
    def handle_success(self):
        pass

    def handle_fail(self, fail):
        pass


class LDAPDeleteAttributes(LDAPModifyAttributes):
    def __init__(self,
                 client,
                 object,
                 vals):
        """
        Request deletion of LDAP attributes.

        object is a string representation of the object DN.

        vals is a list of (type, vals) pairs, where

        type is a string

        vals is a list of values to remove. Additionally, vals can be
        an empty list or can be left out in order to remove all
        values. """

        mod = pureldap.LDAPModification_delete(vals=vals)
        LDAPModifyAttributes.__init__(self, client,
                                      object, [mod])


class LDAPAddEntry(LDAPOperation):
    def __init__(self,
                 client,
                 object,
                 attributes):
        """
        Request addition of LDAP entry.

        object is a string representation of the object DN.

        attributes is a list of LDAPAttributeDescription,
        BERSet(LDAPAttributeValue, ..) pairs.

        """

        LDAPOperation.__init__(self, client)
        r=pureldap.LDAPAddRequest(entry=object,
                                  attributes=attributes)
        self.client.queue(r, self.handle_msg)

    def handle_msg(self, msg):
        assert isinstance(msg, pureldap.LDAPAddResponse)
        assert msg.referral==None #TODO
        if msg.resultCode==0: #TODO ldap.errors.success
            assert msg.matchedDN==''
            self.handle_success()
            return 1
        else:
            self.handle_fail(Failure(
                ldaperrors.get(msg.resultCode, msg.errorMessage)))
            return 1
            
    def handle_success(self):
        pass

    def handle_fail(self, fail):
        pass


class LDAPDelEntry(LDAPOperation):
    def __init__(self,
                 client,
                 object):
        """
        Request deleteition of LDAP entry.

        object is a string representation of the object DN.
        """

        LDAPOperation.__init__(self, client)
        r=pureldap.LDAPDelRequest(entry=object)
        self.client.queue(r, self.handle_msg)

    def handle_msg(self, msg):
        assert isinstance(msg, pureldap.LDAPDelResponse)
        assert msg.referral==None #TODO
        if msg.resultCode==0: #TODO ldap.errors.success
            assert msg.matchedDN==''
            self.handle_success()
            return 1
        else:
            self.handle_fail(Failure(
                ldaperrors.get(msg.resultCode, msg.errorMessage)))
            return 1
            
    def handle_success(self):
        pass

    def handle_fail(self, fail):
        pass

class LDAPModifyPassword(LDAPOperation):
    def __init__(self,
                 deferred,
                 client,
                 userIdentity=None,
                 oldPasswd=None,
                 newPasswd=None):
        LDAPOperation.__init__(self, client)
        r=pureldap.LDAPPasswordModifyRequest(userIdentity=userIdentity,
                                             oldPasswd=oldPasswd,
                                             newPasswd=newPasswd)
        self.client.queue(r, self.handle_msg)
        self.deferred=deferred

    def handle_msg(self, msg):
        assert isinstance(msg, pureldap.LDAPExtendedResponse)
        assert msg.referral==None #TODO
        if msg.resultCode==0: #TODO ldap.errors.success
            assert msg.matchedDN==''
            self.deferred.callback(self)
            return 1
        else:
            self.deferred.errback(Failure(
                ldaperrors.get(msg.resultCode, msg.errorMessage)))
            return 1

class LDAPModifySambaPassword(LDAPModifyAttributes):
    def __init__(self,
                 deferred,
                 client,
                 object,
                 newPassword):
        """
        Request modification of LDAP attributes.

        object is a string representation of the object DN.

        newPassword is plaintext version of new password.
        """

        nthash=smbpassword.nthash(newPassword)
        lmhash=smbpassword.lmhash(newPassword)

        self.deferred=deferred
        self.object=object

        LDAPModifyAttributes.__init__(
            self, client, object,
            modification=pureldap.LDAPModification_replace(vals=(
            ('ntPassword', (nthash,)),
            ('lmPassword', (lmhash,)))))

    def handle_success(self):
        self.deferred.callback(self.object)
    def handle_fail(self, fail):
        self.deferred.errback(fail)
