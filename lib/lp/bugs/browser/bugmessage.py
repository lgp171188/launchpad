# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""IBugMessage-related browser view classes."""

__all__ = [
    "BugMessageAddFormView",
]

from io import BytesIO

from zope.component import getUtility
from zope.formlib.textwidgets import TextWidget
from zope.formlib.widget import CustomWidgetFactory
from zope.formlib.widgets import TextAreaWidget

from lp.app.browser.launchpadform import LaunchpadFormView, action
from lp.bugs.browser.bugattachment import BugAttachmentContentCheck
from lp.bugs.interfaces.bugmessage import IBugMessageAddForm
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.services.webapp import canonical_url


class BugMessageAddFormView(LaunchpadFormView, BugAttachmentContentCheck):
    """Browser view class for adding a bug comment/attachment."""

    schema = IBugMessageAddForm
    next_url = None
    initial_focus_widget = None

    custom_widget_comment = CustomWidgetFactory(
        TextAreaWidget, cssClass="comment-text"
    )
    custom_widget_attachment_url = CustomWidgetFactory(
        TextWidget, displayWidth=44, displayMaxWidth=250
    )

    page_title = "Add a comment or attachment"

    @property
    def label(self):
        return "Add a comment or attachment to bug #%d" % self.context.bug.id

    @property
    def initial_values(self):
        return dict(subject=self.context.bug.followup_subject())

    @property
    def action_url(self):
        # override the default form action url to to go the addcomment
        # page for processing instead of the default which would be the
        # bug index page.
        return "%s/+addcomment" % canonical_url(self.context)

    def validate(self, data):
        # Ensure either a comment or filecontent or a URL was provided,
        # but only if no errors have already been noted.
        if len(self.errors) == 0:
            comment = data.get("comment") or ""
            filecontent = data.get("filecontent", None)
            attachment_url = data.get("attachment_url") or ""
            if (
                not comment.strip()
                and not filecontent
                and not attachment_url.strip()
            ):
                self.addError(
                    "Either a comment or attachment must be provided."
                )

    @action("Post Comment", name="save")
    def save_action(self, action, data):
        """Add the comment and/or attachment."""

        bug = self.context.bug

        # Subscribe to this bug if the checkbox exists and was selected
        if data.get("email_me"):
            bug.subscribe(self.user, self.user)

        # XXX: Bjorn Tillenius 2005-06-16:
        # Write proper FileUpload field and widget instead of this hack.
        file_ = self.request.form.get(self.widgets["filecontent"].name)

        attachment_url = data.get("attachment_url")

        message = None
        if data["comment"] or file_ or attachment_url:
            bugwatch_id = data.get("bugwatch_id")
            if bugwatch_id is not None:
                bugwatch = getUtility(IBugWatchSet).get(bugwatch_id)
            else:
                bugwatch = None
            message = bug.newMessage(
                subject=data.get("subject"),
                content=data["comment"],
                owner=self.user,
                bugwatch=bugwatch,
            )

            # A blank comment with only a subject line is always added
            # when the user attaches a file, so show the add comment
            # feedback message only when the user actually added a
            # comment.
            if data["comment"]:
                self.request.response.addNotification(
                    "Thank you for your comment."
                )

        self.next_url = canonical_url(self.context)

        attachment_description = data.get("attachment_description")

        if file_:
            # Slashes in filenames cause problems, convert them to dashes
            # instead.
            filename = file_.filename.replace("/", "-")

            # if no description was given use the converted filename
            if not attachment_description:
                attachment_description = filename

            # Process the attachment.
            # If the patch flag is not consistent with the result of
            # the guess made in attachmentTypeConsistentWithContentType(),
            # we use the guessed type and lead the user to a page
            # where they can override the flag value, if Launchpad's
            # guess is wrong.
            patch_flag_consistent = (
                self.attachmentTypeConsistentWithContentType(
                    data["patch"], filename, data["filecontent"]
                )
            )
            if not patch_flag_consistent:
                guessed_type = self.guessContentType(
                    filename, data["filecontent"]
                )
                is_patch = guessed_type == "text/x-diff"
            else:
                is_patch = data["patch"]
            attachment = bug.addAttachment(
                owner=self.user,
                data=BytesIO(data["filecontent"]),
                filename=filename,
                url=None,
                description=attachment_description,
                comment=message,
                is_patch=is_patch,
            )

            if not patch_flag_consistent:
                self.next_url = self.nextUrlForInconsistentPatchFlags(
                    attachment
                )

            self.request.response.addNotification(
                "Attachment %s added to bug." % filename
            )

        elif attachment_url:
            is_patch = data["patch"]
            bug.addAttachment(
                owner=self.user,
                data=None,
                filename=None,
                url=attachment_url,
                description=attachment_description,
                comment=message,
                is_patch=is_patch,
            )
            self.request.response.addNotification(
                "Attachment %s added to bug." % attachment_url
            )

    def shouldShowEmailMeWidget(self):
        """Should the subscribe checkbox be shown?"""
        return not self.context.bug.isSubscribed(self.user)
