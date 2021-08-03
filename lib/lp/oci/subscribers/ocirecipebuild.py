# Copyright 2016-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Event subscribers for OCI recipe builds."""

__metaclass__ = type

from zope.component import getUtility

from lp.buildmaster.enums import BuildStatus
from lp.oci.interfaces.ocirecipe import OCI_RECIPE_WEBHOOKS_FEATURE_FLAG
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild
from lp.oci.interfaces.ocirecipebuildjob import IOCIRegistryUploadJobSource
from lp.services.features import getFeatureFlag
from lp.services.scripts import log
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.payload import compose_webhook_payload


def _trigger_oci_recipe_build_webhook(build, action):
    if getFeatureFlag(OCI_RECIPE_WEBHOOKS_FEATURE_FLAG):
        payload = {
            "recipe_build": canonical_url(build, force_local_path=True),
            "action": action,
            }
        payload.update(compose_webhook_payload(
            IOCIRecipeBuild, build,
            ["recipe", "build_request", "status", "registry_upload_status"]))
        getUtility(IWebhookSet).trigger(
            build.recipe, "oci-recipe:build:0.1", payload)


def oci_recipe_build_created(build, event):
    """Trigger events when a new OCI recipe build is created."""
    _trigger_oci_recipe_build_webhook(build, "created")


def oci_recipe_build_modified(build, event):
    """Trigger events when OCI recipe build statuses change."""
    if event.edited_fields is not None:
        status_changed = "status" in event.edited_fields
        registry_changed = "registry_upload_status" in event.edited_fields
        if status_changed or registry_changed:
            _trigger_oci_recipe_build_webhook(build, "status-changed")
        if status_changed:
            if (build.recipe.can_upload_to_registry and
                    build.status == BuildStatus.FULLYBUILT):
                log.info("Scheduling upload of %r to registries." % build)
                getUtility(IOCIRegistryUploadJobSource).create(build)
            else:
                log.info(
                    "%r is not configured for upload to registries." %
                    build.recipe)
