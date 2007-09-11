# Copyright 2006-2007 Canonical Ltd., all rights reserved.

"""XML-RPC API to the application roots."""

__metaclass__ = type

__all__ = [
    'IRosettaSelfTest',
    'ISelfTest',
    'PrivateApplication',
    'PrivateApplicationNavigation',
    'RosettaSelfTest',
    'SelfTest',
    ]

import xmlrpclib

from zope.component import getUtility
from zope.interface import Interface, implements

from canonical.launchpad.interfaces import (
    ILaunchBag, IMailingListApplication,
    IPrivateApplication, IPrivateXMLRPCEndPoint)
from canonical.launchpad.webapp import LaunchpadXMLRPCView, Navigation


class PrivateApplication:
    implements(IPrivateApplication, IPrivateXMLRPCEndPoint)

    @property
    def mailinglists(self):
        return getUtility(IMailingListApplication)


class PrivateApplicationNavigation(Navigation):
    usedfor = IPrivateApplication

    def traverse(self, name):
        # Raise a 404 on an invalid private application end point.
        missing = object()
        end_point = getattr(self.context, name, missing)
        if end_point is missing:
            raise NotFoundError(name)
        return end_point


class ISelfTest(Interface):
    """XMLRPC external interface for testing the XMLRPC external interface."""

    def make_fault():
        """Returns an xmlrpc fault."""

    def concatenate(string1, string2):
        """Return the concatenation of the two given strings."""

    def hello():
        """Return a greeting to the one calling the method."""

    def raise_exception():
        """Raise an exception."""


class SelfTest(LaunchpadXMLRPCView):

    implements(ISelfTest)

    def make_fault(self):
        """Returns an xmlrpc fault."""
        return xmlrpclib.Fault(666, "Yoghurt and spanners.")

    def concatenate(self, string1, string2):
        """Return the concatenation of the two given strings."""
        return u'%s %s' % (string1, string2)

    def hello(self):
        """Return a greeting to the logged in user."""
        caller = getUtility(ILaunchBag).user
        if caller is not None:
            caller_name = caller.displayname
        else:
            caller_name = "Anonymous"
        return "Hello %s." % caller_name

    def raise_exception(self):
        raise RuntimeError("selftest exception")


class IRosettaSelfTest(Interface):

    def run_test():
        return "OK"


class RosettaSelfTest(LaunchpadXMLRPCView):

    implements(IRosettaSelfTest)

    def run_test(self):
        return "OK"

