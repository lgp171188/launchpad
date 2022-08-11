# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""CI build views."""

__all__ = [
    "CIBuildContextMenu",
    "CIBuildNavigation",
    "CIBuildView",
]

from zope.interface import Interface

from lp.app.browser.launchpadform import LaunchpadFormView, action
from lp.code.interfaces.cibuild import ICIBuild
from lp.services.librarian.browser import FileNavigationMixin
from lp.services.webapp import (
    ContextMenu,
    Link,
    Navigation,
    canonical_url,
    enabled_with_permission,
)
from lp.soyuz.interfaces.binarypackagebuild import IBuildRescoreForm


class CIBuildNavigation(Navigation, FileNavigationMixin):
    usedfor = ICIBuild


class CIBuildContextMenu(ContextMenu):
    """Context menu for CI builds."""

    usedfor = ICIBuild

    facet = "overview"

    links = ("retry", "cancel", "rescore")

    @enabled_with_permission("launchpad.Edit")
    def retry(self):
        return Link(
            "+retry",
            "Retry this build",
            icon="retry",
            enabled=self.context.can_be_retried,
        )

    @enabled_with_permission("launchpad.Edit")
    def cancel(self):
        return Link(
            "+cancel",
            "Cancel build",
            icon="remove",
            enabled=self.context.can_be_cancelled,
        )

    @enabled_with_permission("launchpad.Admin")
    def rescore(self):
        return Link(
            "+rescore",
            "Rescore build",
            icon="edit",
            enabled=self.context.can_be_rescored,
        )


class CIBuildView(LaunchpadFormView):
    """Default view of a CI build."""

    class schema(Interface):
        """Schema for a build."""

    @property
    def label(self):
        return self.context.title

    page_title = label


class CIBuildRetryView(LaunchpadFormView):
    """View for retrying a CI build."""

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
                "Build cannot be retried"
            )
        else:
            self.context.retry()
            self.request.response.addInfoNotification("Build has been queued")

        self.request.response.redirect(self.next_url)


class CIBuildCancelView(LaunchpadFormView):
    """View for cancelling a CI build."""

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


class CIBuildRescoreView(LaunchpadFormView):
    """View for rescoring a CI build."""

    schema = IBuildRescoreForm

    page_title = label = "Rescore build"

    def __call__(self):
        if self.context.can_be_rescored:
            return super().__call__()
        self.request.response.addWarningNotification(
            "Cannot rescore this build because it is not queued."
        )
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
