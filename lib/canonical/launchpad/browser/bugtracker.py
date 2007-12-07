# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Bug tracker views."""

__metaclass__ = type

__all__ = [
    'BugTrackerSetNavigation',
    'BugTrackerContextMenu',
    'BugTrackerSetContextMenu',
    'BugTrackerView',
    'BugTrackerAddView',
    'BugTrackerEditView',
    'BugTrackerNavigation',
    'RemoteBug',
    ]

from itertools import chain

from zope.interface import implements
from zope.component import getUtility
from zope.app.form.browser import TextAreaWidget
from zope.formlib import form
from zope.schema import Choice

from canonical.launchpad import _
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.interfaces import (
    BugTrackerType, IBugTracker, IBugTrackerSet, IRemoteBug, ILaunchBag)
from canonical.launchpad.webapp import (
    ContextMenu, GetitemNavigation, LaunchpadEditFormView, LaunchpadFormView,
    LaunchpadView, Link, Navigation, action, canonical_url, custom_widget,
    redirection)
from canonical.launchpad.webapp.batching import BatchNavigator

from canonical.widgets import WhitespaceDelimitedListWidget


class BugTrackerSetNavigation(GetitemNavigation):

    usedfor = IBugTrackerSet

    def breadcrumb(self):
        return 'Remote Bug Trackers'


class BugTrackerContextMenu(ContextMenu):

    usedfor = IBugTracker

    links = ['edit']

    def edit(self):
        text = 'Change details'
        return Link('+edit', text, icon='edit')


class BugTrackerSetContextMenu(ContextMenu):

    usedfor = IBugTrackerSet

    links = ['newbugtracker']

    def newbugtracker(self):
        text = 'Register bug tracker'
        return Link('+newbugtracker', text, icon='add')


class BugTrackerAddView(LaunchpadFormView):

    schema = IBugTracker
    label = "Register an external bug tracker"
    field_names = ['name', 'bugtrackertype', 'title', 'summary',
                   'baseurl', 'contactdetails']

    def setUpWidgets(self, context=None):
        vocab_items = [
            item for item in BugTrackerType.items.items
            if item not in (BugTrackerType.DEBBUGS,
                            BugTrackerType.SOURCEFORGE)]
        fields = []
        for field_name in self.field_names:
            if field_name == 'bugtrackertype':
                fields.append(form.FormField(
                    Choice(__name__='bugtrackertype',
                           title=_('Bug Tracker Type'),
                           values=vocab_items,
                           default=BugTrackerType.BUGZILLA)))
            else:
                fields.append(self.form_fields[field_name])
        self.form_fields = form.Fields(*fields)
        super(BugTrackerAddView, self).setUpWidgets(context=context)

    @action(_('Add'), name='add')
    def add(self, action, data):
        """Create the IBugTracker."""
        btset = getUtility(IBugTrackerSet)
        bugtracker = btset.ensureBugTracker(
            name=data['name'],
            bugtrackertype=data['bugtrackertype'],
            title=data['title'],
            summary=data['summary'],
            baseurl=data['baseurl'],
            contactdetails=data['contactdetails'],
            owner=getUtility(ILaunchBag).user)
        self.next_url = canonical_url(bugtracker)

#     def create(self, name, bugtrackertype, title, summary, baseurl,
#                contactdetails):
#         """Create the IBugTracker."""
#         btset = getUtility(IBugTrackerSet)
#         bugtracker = btset.ensureBugTracker(
#             name=name,
#             bugtrackertype=bugtrackertype,
#             title=title,
#             summary=summary,
#             baseurl=baseurl,
#             contactdetails=contactdetails,
#             owner=getUtility(ILaunchBag).user)
#         # keep track of the new one
#         self._newtracker_ = bugtracker
#         return bugtracker

#     def add(self, content):
#         return content

#     def nextURL(self):
#         return canonical_url(self._newtracker_)


class BugTrackerView(LaunchpadView):

    usedfor = IBugTracker

    def initialize(self):
        self.batchnav = BatchNavigator(self.context.watches, self.request)

    @property
    def related_projects(self):
        """Return all project groups and projects.

        This property was created for the Related projects portlet in
        the bug tracker's page.
        """
        return shortlist(chain(self.context.projects,
                               self.context.products), 100)


class BugTrackerEditView(LaunchpadEditFormView):

    schema = IBugTracker
    field_names = ['name', 'title', 'bugtrackertype',
                   'summary', 'baseurl', 'aliases', 'contactdetails']

    custom_widget('summary', TextAreaWidget, width=30, height=5)
    custom_widget('aliases', WhitespaceDelimitedListWidget)

    @action('Change', name='change')
    def change_action(self, action, data):
        self.updateContextFromData(data)

    @property
    def next_url(self):
        return canonical_url(self.context)


class BugTrackerNavigation(Navigation):

    usedfor = IBugTracker

    def breadcrumb(self):
        return self.context.title

    def traverse(self, remotebug):
        bugs = self.context.getBugsWatching(remotebug)
        if len(bugs) == 0:
            # no bugs watching => not found
            return None
        elif len(bugs) == 1:
            # one bug watching => redirect to that bug
            return redirection(canonical_url(bugs[0]))
        else:
            # else list the watching bugs
            return RemoteBug(self.context, remotebug, bugs)


class RemoteBug:
    """Represents a bug in a remote bug tracker."""

    implements(IRemoteBug)

    def __init__(self, bugtracker, remotebug, bugs):
        self.bugtracker = bugtracker
        self.remotebug = remotebug
        self.bugs = bugs

    @property
    def title(self):
        return 'Remote Bug #%s in %s' % (self.remotebug,
                                         self.bugtracker.title)

