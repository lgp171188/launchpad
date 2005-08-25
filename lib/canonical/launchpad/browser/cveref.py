# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""ICVERef-related view classes."""

__metaclass__ = type

__all__ = ['BugCVERefAddView']

from zope.component import getUtility
from canonical.launchpad.interfaces import ILaunchBag
from canonical.launchpad.browser.addview import SQLObjectAddView

class BugCVERefAddView(SQLObjectAddView):
    def __init__(self, context, request):
        SQLObjectAddView.__init__(self, context, request)
        self.bug = getUtility(ILaunchBag).bug
