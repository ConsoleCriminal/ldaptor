from twisted.web import widgets
from twisted.internet import defer, protocol
from twisted.python.failure import Failure
from ldaptor.protocols.ldap import ldapclient, ldapfilter
from ldaptor.protocols import pureber, pureldap
from twisted.internet import reactor
from ldaptor.apps.webui.htmlify import htmlify_attributes
import string, urllib

import template

class LDAPSearchEntry(ldapclient.LDAPSearch):

    # I ended up separating the deferred that signifies when the
    # search is complete and whether it failed from the deferred that
    # generates web content. Maybe they should be combined some day.

    def __init__(self,
                 deferred,
                 contentDeferred,
                 client,
                 baseObject,
                 filter=pureldap.LDAPFilterMatchAll):
        ldapclient.LDAPSearch.__init__(self, deferred, client,
                                       baseObject=baseObject,
                                       filter=filter,
                                       sizeLimit=20,
                                       )
        self.contentDeferred=contentDeferred
        self.result=""
        self.count=0
        deferred.addCallbacks(self._ok, errback=self._fail)

    def _ok(self, dummy):
        self.contentDeferred.callback(
            ["<p>%d entries matched."%self.count])
        return dummy

    def _fail(self, fail):
        self.contentDeferred.callback(["fail: %s"%fail.getErrorMessage()])
        return fail

    def handle_entry(self, objectName, attributes):
        l=[]
        l.append('<a href="edit/%s">edit</a>\n'%urllib.quote(objectName))
        l.append('<a href="delete/%s">delete</a>\n'%urllib.quote(objectName))
        l.append('<a href="change_password/%s">change password</a>\n'%urllib.quote(objectName))
        result = ('<p>%s\n'%objectName
                  + '[' + '|'.join(l) + ']'
                  + htmlify_attributes(attributes)
                  )


        d=defer.Deferred()
        self.contentDeferred.callback([result, d])
        self.contentDeferred=d
        self.count=self.count+1

class DoSearch(ldapclient.LDAPClient):
    factory = None

    def __init__(self):
        ldapclient.LDAPClient.__init__(self)

    def connectionMade(self):
        d=self.bind()
        d.addCallbacks(self._handle_bind_success,
                       self._handle_bind_fail)

    def _handle_bind_fail(self, fail):
        self.unbind()
        self.factory.deferred.errback(fail)
        raise fail

    def _handle_bind_success(self, x):
        matchedDN, serverSaslCreds = x
        LDAPSearchEntry(self.factory.deferred,
                        self.factory.contentDeferred,
                        self,
                        baseObject=self.factory.baseObject,
                        filter=self.factory.ldapFilter)
        self.factory.deferred.addCallbacks(self._unbind, lambda x:x)

    def _unbind(self, dummy):
        self.unbind()
        return None # if we return self or x here, self is never deleted

class DoSearchFactory(protocol.ClientFactory):
    protocol=DoSearch

    def __init__(self, deferred, contentDeferred, baseObject, ldapFilter=None):
        self.deferred=deferred
        self.contentDeferred=contentDeferred
        self.baseObject=baseObject
        self.ldapFilter=ldapFilter

    def clientConnectionFailed(self, connector, reason):
        self.deferred.errback(reason)

    def clientConnectionLost(self, connector, reason):
        if not self.deferred.called:
            self.deferred.errback(reason)

class SearchForm(widgets.Form):
    formFields = [
        ('string', 'Advanced', 'ldapfilter', ''),
        ]

    def __init__(self, baseObject, ldaphost, ldapport,
                 searchFields=(),
                 ):
        self.baseObject = baseObject
        self.ldaphost = ldaphost
        self.ldapport = ldapport
        self.searchFields = searchFields

    def getFormFields(self, request, kws=None):
        #TODO widgets.Form.getFormFields would be nicer
        # if it tried to get values from request; but that
        # parsing happens elsewhere, need to share code
        # and preferably results too.
        if kws==None:
            kws={}
        r=[]

        for (displayName, filter) in self.searchFields:
            inputType='string'
            inputName='search_'+displayName
            if kws.has_key(inputName):
                inputValue=kws[inputName]
            else:
                inputValue=''
            r.append((inputType, displayName, inputName, inputValue))

        for (inputType, displayName, inputName, inputValue) in self.formFields:
            if kws.has_key(inputName):
                inputValue=kws[inputName]
            r.append((inputType, displayName, inputName, inputValue))

        return r

    def process(self, write, request, submit, **kw):
        from cStringIO import StringIO
        io=StringIO()
        self.format(self.getFormFields(request, kw), io.write, request)
        filt=[]
        for k,v in kw.items():
            if k[:len("search_")]=="search_":
                k=k[len("search_"):]
                v=string.strip(v)
                if v=='':
                    continue

                filter = None
                for (displayName, searchFilter) in self.searchFields:
                    if k == displayName:
                        filter = searchFilter
                # TODO handle not filter right (old form open in browser etc)
                assert filter
                # TODO escape ) in v
                filt.append(ldapfilter.parseFilter(filter % {'input': v}))
            elif k=='ldapfilter' and v:
                filt.append(ldapfilter.parseFilter(v))
        if filt:
            if len(filt)==1:
                filt=filt[0]
            else:
                filt=pureldap.LDAPFilter_and(filt)
        else:
            filt=pureldap.LDAPFilterMatchAll
        deferred=defer.Deferred()
        contentDeferred=defer.Deferred()
        reactor.connectTCP(self.ldaphost, self.ldapport,
                           DoSearchFactory(deferred,
                                           contentDeferred,
                                           baseObject=self.baseObject,
                                           ldapFilter=filt))
        filtText=filt.asText()
        return [io.getvalue(),
                contentDeferred,
                '<P>Used filter %s' % filtText,
                '<P><a href="mass_change_password/%s">Mass change passwords</a>\n'%urllib.quote(filtText)
                ]

class SearchPage(template.BasicPage):
    title = "Ldaptor Search Page"
    isLeaf = 1

    def __init__(self, baseObject, ldaphost, ldapport,
                 searchFields=(),
                 ):
        template.BasicPage.__init__(self)
        self.baseObject = baseObject
        self.ldaphost = ldaphost
        self.ldapport = ldapport
        self.searchFields = searchFields

    def _header(self, request):
        l=[]
        l.append('<a href="%s">Search</a>'%request.sibLink("search"))
        l.append('<a href="%s">add new entry</a>'%request.sibLink("add"))
        
        return '[' + '|'.join(l) + ']'

    def getContent(self, request):
        return [self._header(request)] \
               + SearchForm(baseObject=self.baseObject,
                            ldaphost=self.ldaphost,
                            ldapport=self.ldapport,
                            searchFields=self.searchFields).display(request)
