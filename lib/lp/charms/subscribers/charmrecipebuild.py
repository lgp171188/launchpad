# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Event subscribers for charm recipe builds."""

from zope.component import getUtility

from lp.buildmaster.enums import BuildStatus
from lp.charms.interfaces.charmrecipe import CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG
from lp.charms.interfaces.charmrecipebuild import ICharmRecipeBuild
from lp.charms.interfaces.charmrecipebuildjob import ICharmhubUploadJobSource
from lp.services.features import getFeatureFlag
from lp.services.scripts import log
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.payload import compose_webhook_payload


def _trigger_charm_recipe_build_webhook(build, action):
    if getFeatureFlag(CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG):
        payload = {
            "recipe_build": canonical_url(build, force_local_path=True),
            "action": action,
        }
        payload.update(
            compose_webhook_payload(
                ICharmRecipeBuild,
                build,
                ["recipe", "build_request", "status", "store_upload_status"],
            )
        )
        getUtility(IWebhookSet).trigger(
            build.recipe, "charm-recipe:build:0.1", payload
        )


def charm_recipe_build_created(build, event):
    """Trigger events when a new charm recipe build is created."""
    _trigger_charm_recipe_build_webhook(build, "created")


def charm_recipe_build_modified(build, event):
    """Trigger events when a charm recipe build is modified."""
    if event.edited_fields is not None:
        status_changed = "status" in event.edited_fields
        store_upload_status_changed = (
            "store_upload_status" in event.edited_fields
        )
        if status_changed or store_upload_status_changed:
            _trigger_charm_recipe_build_webhook(build, "status-changed")
        if status_changed:
            if build.status == BuildStatus.FULLYBUILT:
                if (
                    build.recipe.can_upload_to_store
                    and build.recipe.store_upload
                ):
                    log.info("Scheduling upload of %r to the store." % build)
                    getUtility(ICharmhubUploadJobSource).create(build)
                else:
                    log.info(
                        "%r is not configured for upload to the store."
                        % build.recipe
                    )
