# lib/lp/crafts/subscribers/craftrecipebuild.py

"""Event subscribers for craft recipe builds."""

from configparser import NoSectionError

from zope.component import getUtility

from lp.buildmaster.enums import BuildStatus
from lp.crafts.interfaces.craftrecipebuild import ICraftRecipeBuild
from lp.crafts.interfaces.craftrecipejob import ICraftPublishingJobSource
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.services.config import config
from lp.services.scripts import log
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.payload import compose_webhook_payload


def _trigger_craft_build_webhook(build, action):
    """Trigger a webhook for a craft recipe build event."""
    payload = {
        "craft_build": canonical_url(build, force_local_path=True),
        "action": action,
    }
    payload.update(
        compose_webhook_payload(
            ICraftRecipeBuild,
            build,
            ["recipe", "build_request", "status"],
        )
    )
    getUtility(IWebhookSet).trigger(
        build.recipe, "craft-recipe:build:0.1", payload
    )


def craft_build_status_changed(build, event):
    """Trigger events when craft recipe build statuses change."""
    _trigger_craft_build_webhook(build, "status-changed")

    if build.status == BuildStatus.FULLYBUILT:
        # Check if this build is from a configured distribution
        should_publish = False
        if (
            build.recipe.git_repository is not None
            and IDistributionSourcePackage.providedBy(
                build.recipe.git_repository.target
            )
        ):
            distribution_name = (
                build.recipe.git_repository.target.distribution.name
            )
            try:
                # Check if there are any config variables for this distribution
                config["craftbuild." + distribution_name]
                should_publish = True
            except NoSectionError:
                # If no section is found, we shouldn't publish
                should_publish = False
                log.debug(
                    "No configuration found for distribution %s, "
                    "skipping upload" % distribution_name
                )

        # Only schedule uploads for configured distribution builds
        if should_publish and build.recipe.store_upload:
            log.info("Scheduling publishing of artifacts from %r" % build)
            getUtility(ICraftPublishingJobSource).create(build)
