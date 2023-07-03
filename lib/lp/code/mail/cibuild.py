#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "CIBuildMailer",
]

from lp.app.browser.tales import DurationFormatterAPI
from lp.code.model.cibuild import CIBuild
from lp.registry.model.person import Person
from lp.services.config import config
from lp.services.mail.basemailer import BaseMailer, RecipientReason
from lp.services.webapp import canonical_url


class CIBuildRecipientReason(RecipientReason):
    @classmethod
    def forRepositoryOwner(cls, owner: Person) -> "CIBuildRecipientReason":
        header = cls.makeRationale("Owner", owner)
        reason = (
            "You are receiving this email because %(lc_entity_is)s the owner "
            "of this repository."
        )
        return cls(owner, owner, header, reason)


class CIBuildMailer(BaseMailer):
    app = "code"

    @classmethod
    def forStatus(cls, build: CIBuild):
        """Create a mailer for notifying about CI build status.

        :param build: The relevant build.
        """
        repository_owner = build.git_repository.owner
        recipients = {
            repository_owner: CIBuildRecipientReason.forRepositoryOwner(
                repository_owner
            )
        }
        return cls(
            build=build,
            subject="[CI build #%(build_id)d] %(build_title)s",
            template_name="cibuild-notification.txt",
            recipients=recipients,
            from_address=config.canonical.noreply_from_address,
            notification_type="ci-build-status",
        )

    def __init__(self, build: CIBuild, *args, **kwargs):
        self.build = build
        super().__init__(*args, **kwargs)

    def _getHeaders(self, email, recipient):
        """See `BaseMailer`."""
        headers = super()._getHeaders(email, recipient)
        headers["X-Launchpad-Build-State"] = self.build.status.name
        return headers

    def _getTemplateParams(self, email, recipient):
        """See `BaseMailer`."""
        build = self.build
        params = super()._getTemplateParams(email, recipient)
        params.update(
            {
                "build_id": build.id,
                "build_title": build.title,
                "git_repository": build.git_repository.unique_name,
                "commit_sha1": build.commit_sha1,
                "distroseries": build.distro_series,
                "architecturetag": build.arch_tag,
                "build_state": build.status.title,
                "build_duration": "",
                "log_url": "",
                "upload_log_url": "",
                "builder_url": "",
                "build_url": canonical_url(build),
            }
        )
        if build.duration is not None:
            duration_formatter = DurationFormatterAPI(build.duration)
            params["build_duration"] = duration_formatter.approximateduration()
        if build.log is not None:
            params["log_url"] = build.log_url
        if build.upload_log is not None:
            params["upload_log_url"] = build.upload_log_url
        if build.builder is not None:
            params["builder_url"] = canonical_url(build.builder)
        return params

    def _getFooter(self, email, recipient, params):
        """See `BaseMailer`."""
        return "{build_url}\n{reason}\n".format(**params)
