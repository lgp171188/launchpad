# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Featured Project views."""

__metaclass__ = type

__all__ = [
    'FeaturedProjectsView',
    ]

from zope.interface import Interface
from zope.component import getUtility
from zope.schema import Choice, Set

from canonical.launchpad.interfaces import IPillarNameSet

from canonical.launchpad import _

from canonical.launchpad.webapp import (
    action, canonical_url, custom_widget, LaunchpadFormView, 
    )

from canonical.widgets import FeaturedProjectsWidget


class FeaturedProjectForm(Interface):
    """Form that requires the user to choose a pillar to feature."""

    add = Choice(
        title=_("Add project"),
        description=_(
            "Choose a project to feature on the Launchpad home page."),
        required=False, vocabulary='DistributionOrProductOrProject')

    remove = Set(
        title=u'Remove projects',
        description=_(
            'Select projects that you would like to remove from the list'),
        required=False,
        value_type=Choice(vocabulary="FeaturedProject"))


class FeaturedProjectsView(LaunchpadFormView):
    """A view for adding and removing featured projects."""

    schema = FeaturedProjectForm
    custom_widget('remove', FeaturedProjectsWidget)

    @action(_('Update featured project list'), name='update')
    def update_action(self, action, data):
        """Add and remove featured projects."""

        add = data.get('add')
        if add is not None:
            getUtility(IPillarNameSet).add_featured_project(add)

        remove = data.get('remove')
        if remove is not None:
            for project in remove:
                getUtility(IPillarNameSet).remove_featured_project(project)

        self.next_url = canonical_url(self.context)

    @action(_("Cancel"), name="cancel", validator='validate_cancel')
    def action_cancel(self, action, data):
        self.next_url = canonical_url(self.context)

    @property
    def action_url(self):
        return "/+featuredprojects"


