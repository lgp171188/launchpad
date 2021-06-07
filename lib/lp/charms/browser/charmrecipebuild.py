# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe build views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    "CharmRecipeBuildContextMenu",
    "CharmRecipeBuildNavigation",
    "CharmRecipeBuildView",
    ]

from zope.interface import Interface

from lp.app.browser.launchpadform import (
    action,
    LaunchpadFormView,
    )
from lp.charms.interfaces.charmrecipebuild import ICharmRecipeBuild
from lp.services.librarian.browser import (
    FileNavigationMixin,
    ProxiedLibraryFileAlias,
    )
from lp.services.propertycache import cachedproperty
from lp.services.webapp import (
    canonical_url,
    ContextMenu,
    enabled_with_permission,
    LaunchpadView,
    Link,
    Navigation,
    )
from lp.soyuz.interfaces.binarypackagebuild import IBuildRescoreForm


class CharmRecipeBuildNavigation(Navigation, FileNavigationMixin):
    usedfor = ICharmRecipeBuild


class CharmRecipeBuildContextMenu(ContextMenu):
    """Context menu for charm recipe builds."""

    usedfor = ICharmRecipeBuild

    facet = "overview"

    links = ("retry", "cancel", "rescore")

    @enabled_with_permission("launchpad.Edit")
    def retry(self):
        return Link(
            "+retry", "Retry this build", icon="retry",
            enabled=self.context.can_be_retried)

    @enabled_with_permission("launchpad.Edit")
    def cancel(self):
        return Link(
            "+cancel", "Cancel build", icon="remove",
            enabled=self.context.can_be_cancelled)

    @enabled_with_permission("launchpad.Admin")
    def rescore(self):
        return Link(
            "+rescore", "Rescore build", icon="edit",
            enabled=self.context.can_be_rescored)


class CharmRecipeBuildView(LaunchpadView):
    """Default view of a charm recipe build."""

    @property
    def label(self):
        return self.context.title

    page_title = label

    @cachedproperty
    def files(self):
        """Return `LibraryFileAlias`es for files produced by this build."""
        if not self.context.was_built:
            return None

        return [
            ProxiedLibraryFileAlias(alias, self.context)
            for _, alias, _ in self.context.getFiles() if not alias.deleted]

    @cachedproperty
    def has_files(self):
        return bool(self.files)

    @property
    def next_url(self):
        return canonical_url(self.context)


class CharmRecipeBuildRetryView(LaunchpadFormView):
    """View for retrying a charm recipe build."""

    class schema(Interface):
        """Schema for retrying a build."""

    page_title = label = "Retry build"

    @property
    def cancel_url(self):
        return canonical_url(self.context)
    next_url = cancel_url

    @action("Retry build", name="retry")
    def request_action(self, action, data):
        """Retry the build."""
        if not self.context.can_be_retried:
            self.request.response.addErrorNotification(
                "Build cannot be retried")
        else:
            self.context.retry()
            self.request.response.addInfoNotification("Build has been queued")

        self.request.response.redirect(self.next_url)


class CharmRecipeBuildCancelView(LaunchpadFormView):
    """View for cancelling a charm recipe build."""

    class schema(Interface):
        """Schema for cancelling a build."""

    page_title = label = "Cancel build"

    @property
    def cancel_url(self):
        return canonical_url(self.context)
    next_url = cancel_url

    @action("Cancel build", name="cancel")
    def request_action(self, action, data):
        """Cancel the build."""
        self.context.cancel()


class CharmRecipeBuildRescoreView(LaunchpadFormView):
    """View for rescoring a charm recipe build."""

    schema = IBuildRescoreForm

    page_title = label = "Rescore build"

    def __call__(self):
        if self.context.can_be_rescored:
            return super(CharmRecipeBuildRescoreView, self).__call__()
        self.request.response.addWarningNotification(
            "Cannot rescore this build because it is not queued.")
        self.request.response.redirect(canonical_url(self.context))

    @property
    def cancel_url(self):
        return canonical_url(self.context)
    next_url = cancel_url

    @action("Rescore build", name="rescore")
    def request_action(self, action, data):
        """Rescore the build."""
        score = data.get("priority")
        self.context.rescore(score)
        self.request.response.addNotification("Build rescored to %s." % score)

    @property
    def initial_values(self):
        return {"score": str(self.context.buildqueue_record.lastscore)}
