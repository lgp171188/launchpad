# Copyright 2016-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Event subscribers for livefs builds."""

__metaclass__ = type


from zope.component import getUtility

from lp.services.features import getFeatureFlag
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.payload import compose_webhook_payload
from lp.soyuz.interfaces.livefs import LIVEFS_WEBHOOKS_FEATURE_FLAG
from lp.soyuz.interfaces.livefsbuild import ILiveFSBuild


def _trigger_livefs_build_webhook(livefsbuild, action):
    if getFeatureFlag(LIVEFS_WEBHOOKS_FEATURE_FLAG):
        payload = {
            "livefs_build": canonical_url(livefsbuild, force_local_path=True),
            "action": action,
            }
        payload.update(compose_webhook_payload(
            ILiveFSBuild, livefsbuild,
            ["livefs", "status"]))
        getUtility(IWebhookSet).trigger(
            livefsbuild.livefs, "livefs:build:0.1", payload)


def livefs_build_created(livefsbuild, event):
    """Trigger events when a new livefs build is created."""
    _trigger_livefs_build_webhook(livefsbuild, "created")


def livefs_build_status_changed(livefsbuild, event):
    """Trigger events when livefs package build statuses change."""
    if event.edited_fields is not None:
        if "status" in event.edited_fields:
            _trigger_livefs_build_webhook(livefsbuild, "status-changed")
