import os
from twisted.internet import reactor
from twisted.cred import portal, checkers
from nevow import rend, appserver, inevow, compy, \
     stan, guard, loaders
from formless import annotate, webform

from ldaptor.protocols.ldap import ldapclient, ldapsyntax, ldapconnector, \
     distinguishedname
from ldaptor import ldapfilter
from ldaptor.protocols import pureldap

class ILDAPConfig(compy.Interface):
    """Addressbook configuration retrieval."""

    def getBaseDN(self):
        """Get the LDAP base DN, as a DistinguishedName."""

    def getServiceLocationOverrides(self):
        """
        Get the LDAP service location overrides, as a mapping of
        DistinguishedName to (host, port) tuples.
        """

class LDAPConfig(object):
    __implements__ = ILDAPConfig

    def __init__(self,
                 baseDN,
                 serviceLocationOverrides=None):
        self.baseDN = distinguishedname.DistinguishedName(baseDN)
        self.serviceLocationOverrides = {}
        if serviceLocationOverrides is not None:
            for k,v in serviceLocationOverrides.items():
                dn = distinguishedname.DistinguishedName(k)
                self.serviceLocationOverrides[dn]=v

    def getBaseDN(self):
        return self.baseDN

    def getServiceLocationOverrides(self):
        return self.serviceLocationOverrides

class LDAPSearchFilter(annotate.String):
    def coerce(self, *a, **kw):
        val = super(LDAPSearchFilter, self).coerce(*a, **kw)
        try:
            f = ldapfilter.parseFilter(val)
        except ldapfilter.InvalidLDAPFilter, e:
            raise annotate.InputError, \
                  "%r is not a valid LDAP search filter: %s" % (val, e)
        return f

class IAddressBookSearch(annotate.TypedInterface):
    search = LDAPSearchFilter(label="Search filter")

class CurrentSearch(object):
    __implements__ = IAddressBookSearch, inevow.IContainer
    search = None

    def child(self, context, name):
        if name == 'searchFilter':
            return self.search
        if name != 'results':
            return None
        config = context.locate(ILDAPConfig)

        c=ldapconnector.LDAPClientCreator(reactor, ldapclient.LDAPClient)
        d=c.connectAnonymously(config.getBaseDN(),
                               config.getServiceLocationOverrides())

        def _search(proto, base, searchFilter):
            baseEntry = ldapsyntax.LDAPEntry(client=proto, dn=base)
            d=baseEntry.search(filterObject=searchFilter)
            return d

        d.addCallback(_search, config.getBaseDN(), self.search)
        return d

def LDAPFilterSerializer(original, context):
    return original.asText()

# TODO need to make this pretty some day.
for c in [
    pureldap.LDAPFilter_and,
    pureldap.LDAPFilter_or,
    pureldap.LDAPFilter_not,
    pureldap.LDAPFilter_substrings,
    pureldap.LDAPFilter_equalityMatch,
    pureldap.LDAPFilter_greaterOrEqual,
    pureldap.LDAPFilter_lessOrEqual,
    pureldap.LDAPFilter_approxMatch,
    pureldap.LDAPFilter_present,
    pureldap.LDAPFilter_extensibleMatch,
    ]:
    compy.registerAdapter(LDAPFilterSerializer,
                          c,
                          inevow.ISerializable)

class AddressBookResource(rend.Page):
    docFactory = loaders.xmlfile(
        'searchform.xhtml',
        templateDir=os.path.split(os.path.abspath(__file__))[0])

    def configurable_(self, context):
        request = context.locate(inevow.IRequest)
        i = request.session.getComponent(IAddressBookSearch)
        if i is None:
            i = CurrentSearch()
            request.session.setComponent(IAddressBookSearch, i)
        return i

    def data_search(self, context, data):
        configurable = self.locateConfigurable(context, '')
        cur = configurable.original
        return cur

    def child_form_css(self, request):
        return webform.defaultCSS

    def render_input(self, context, data):
        return webform.renderForms()

    def render_haveSearch(self, context, data):
        r=context.allPatterns(str(data.search is not None))
        return context.tag.clear()[r]

    def render_searchFilter(self, context, data):
        return data.asText()

    def render_iterateMapping(self, context, data):
        headers = context.allPatterns('header')
        keyPattern = context.patternGenerator('key')
        valuePattern = context.patternGenerator('value')
        divider = context.patternGenerator('divider', default=stan.invisible)
        content = [(keyPattern(data=key),
                    valuePattern(data=value),
                    divider())
                   for key, value in data.items()]
        if not content:
            content = context.allPatterns('empty')
        else:
            # No divider after the last thing.
            content[-1] = content[-1][:-1]
        footers = context.allPatterns('footer')

        return context.tag.clear()[ headers, content, footers ]

class AddressBookRealm:
    __implements__ = portal.IRealm,

    def __init__(self, resource):
        self.resource = resource

    def requestAvatar(self, avatarId, mind, *interfaces):
        if inevow.IResource not in interfaces:
            raise NotImplementedError, "no interface"
        return (inevow.IResource,
                self.resource,
                lambda: None)

def getSite(config):
    form = AddressBookResource()
    form.remember(config, ILDAPConfig)
    realm = AddressBookRealm(form)
    site = appserver.NevowSite(
        guard.SessionWrapper(
        portal.Portal(realm, [checkers.AllowAnonymousAccess()])))
    return site
