"""Utilities for writing Twistedy unit tests and debugging."""

from twisted.internet import reactor

def calltrace():
    """Print out all function calls. For debug use only."""
    def printfuncnames(frame, event, arg):
        print "|%s: %s:%d:%s" % (event,
                                 frame.f_code.co_filename,
                                 frame.f_code.co_firstlineno,
                                 frame.f_code.co_name)
    import sys
    sys.setprofile(printfuncnames)

class LDAPClientTestDriver:
    """

    A test driver that looks somewhat like a real LDAPClient.

    Pass in a list of lists of LDAPProtocolResponses. For each sent
    LDAP message, the first item of said list is iterated through, and
    all the items are sent as responses to the callback. The sent LDAP
    messages are stored in self.sent, so you can assert that the sent
    messages are what they are supposed to be.

    """
    def __init__(self, *responses):
        self.sent=[]
        self.responses=list(responses)
    def queue(self, x, callback):
        self.sent.append(x)
        assert self.responses, 'Ran out of responses at %r' % x
        responses = self.responses.pop(0)
        while responses:
            r = responses.pop(0)
            ret = callback(r)
            if responses:
                assert ret==0
            else:
                assert ret==1

    def assertNothingSent(self):
        # just a bit more explicit
        self.assertSent()

    def assertSent(self, *shouldBeSent):
        shouldBeSent = list(shouldBeSent)
        assert self.sent == shouldBeSent, \
               '%s expected to send %r but sent %r' % (
            self.__class__.__name__,
            shouldBeSent,
            self.sent)
        sentStr = ''.join([str(x) for x in self.sent])
	shouldBeSentStr = ''.join([str(x) for x in shouldBeSent])
	assert sentStr == shouldBeSentStr, \
               '%s expected to send data %r but sent %r' % (
            self.__class__.__name__,
            shouldBeSentStr,
            sentStr)
