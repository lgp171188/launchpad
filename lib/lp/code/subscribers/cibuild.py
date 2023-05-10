# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Event subscribers for CI builds."""

from zope.component import getUtility

from lp.code.interfaces.cibuild import CI_WEBHOOKS_FEATURE_FLAG, ICIBuild
from lp.services.features import getFeatureFlag
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.payload import compose_webhook_payload


def _trigger_ci_build_webhook(build, action):
    if getFeatureFlag(CI_WEBHOOKS_FEATURE_FLAG):
        payload = {
            "build": canonical_url(build, force_local_path=True),
            "action": action,
        }
        payload.update(
            compose_webhook_payload(
                ICIBuild, build, ["git_repository", "commit_sha1", "status"]
            )
        )
        getUtility(IWebhookSet).trigger(
            build.git_repository, "ci:build:0.1", payload
        )


def ci_build_created(build, event):
    """Trigger events when a new CI build is created."""
    _trigger_ci_build_webhook(build, "created")


def ci_build_modified(build, event):
    """Trigger events when a CI build is modified."""
    if event.edited_fields is not None:
        if "status" in event.edited_fields:
            _trigger_ci_build_webhook(build, "status-changed")
