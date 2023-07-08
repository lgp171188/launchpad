# Copyright 2010-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "NameBlocklistAddView",
    "NameBlocklistEditView",
    "NameBlocklistNavigationMenu",
    "NameBlocklistSetNavigationMenu",
    "NameBlocklistSetView",
]

import re

from zope.component import adapter, getUtility
from zope.formlib.widget import CustomWidgetFactory
from zope.formlib.widgets import TextWidget
from zope.interface import implementer

from lp.app.browser.launchpadform import LaunchpadFormView, action
from lp.registry.browser import RegistryEditFormView
from lp.registry.interfaces.nameblocklist import (
    INameBlocklist,
    INameBlocklistSet,
)
from lp.services.webapp.breadcrumb import Breadcrumb
from lp.services.webapp.interfaces import IBreadcrumb
from lp.services.webapp.menu import (
    ApplicationMenu,
    Link,
    NavigationMenu,
    enabled_with_permission,
)
from lp.services.webapp.publisher import (
    LaunchpadView,
    Navigation,
    canonical_url,
)


class NameBlocklistValidationMixin:
    """Validate regular expression when adding or editing."""

    def validate(self, data):
        """Validate regular expression."""
        regexp = data["regexp"]
        try:
            re.compile(regexp)
            name_blocklist_set = getUtility(INameBlocklistSet)
            if (
                INameBlocklistSet.providedBy(self.context)
                or self.context.regexp != regexp
            ):
                # Check if the regular expression already exists if a
                # new expression is being created or if an existing
                # regular expression has been modified.
                if name_blocklist_set.getByRegExp(regexp) is not None:
                    self.setFieldError(
                        "regexp", "This regular expression already exists."
                    )
        except re.error as e:
            self.setFieldError("regexp", "Invalid regular expression: %s" % e)


class NameBlocklistEditView(
    NameBlocklistValidationMixin, RegistryEditFormView
):
    """View for editing a blocklist expression."""

    schema = INameBlocklist
    field_names = ["regexp", "admin", "comment"]
    label = "Edit a blocklist expression"
    page_title = label

    @property
    def cancel_url(self):
        return canonical_url(getUtility(INameBlocklistSet))

    next_url = cancel_url


class NameBlocklistAddView(NameBlocklistValidationMixin, LaunchpadFormView):
    """View for adding a blocklist expression."""

    schema = INameBlocklist
    field_names = ["regexp", "admin", "comment"]
    label = "Add a new blocklist expression"
    page_title = label

    custom_widget_regexp = CustomWidgetFactory(TextWidget, displayWidth=60)

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    next_url = cancel_url

    @action("Add to blocklist", name="add")
    def add_action(self, action, data):
        name_blocklist_set = getUtility(INameBlocklistSet)
        name_blocklist_set.create(
            regexp=data["regexp"],
            comment=data["comment"],
            admin=data["admin"],
        )
        self.request.response.addInfoNotification(
            'Regular expression "%s" has been added to the name blocklist.'
            % data["regexp"]
        )


class NameBlocklistSetView(LaunchpadView):
    """View for /+nameblocklists top level collection."""

    label = "Blocklist for names of Launchpad pillars and persons"
    page_title = label


class NameBlocklistSetNavigation(Navigation):
    usedfor = INameBlocklistSet

    def traverse(self, name):
        return self.context.get(name)


class NameBlocklistSetNavigationMenu(NavigationMenu):
    """Action menu for NameBlocklistSet."""

    usedfor = INameBlocklistSet
    facet = "overview"
    links = [
        "add_blocklist_expression",
    ]

    @enabled_with_permission("launchpad.Edit")
    def add_blocklist_expression(self):
        return Link("+add", "Add blocklist expression", icon="add")


class NameBlocklistNavigationMenu(ApplicationMenu):
    """Action menu for NameBlocklist."""

    usedfor = INameBlocklist
    facet = "overview"
    links = [
        "edit_blocklist_expression",
    ]

    @enabled_with_permission("launchpad.Edit")
    def edit_blocklist_expression(self):
        return Link("+edit", "Edit blocklist expression", icon="edit")


@adapter(INameBlocklistSet)
@implementer(IBreadcrumb)
class NameBlocklistSetBreadcrumb(Breadcrumb):
    """Return a breadcrumb for an `INameBlockListSet`."""

    text = "Name Blocklist"
