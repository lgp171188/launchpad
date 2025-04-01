# lib/lp/crafts/subscribers/craftrecipebuild.py

"""Event subscribers for craft recipe builds."""

import lzma
from configparser import NoSectionError
from tarfile import TarFile

from zope.component import getUtility

from lp.buildmaster.enums import BuildStatus
from lp.crafts.interfaces.craftrecipebuild import ICraftRecipeBuild
from lp.crafts.interfaces.craftrecipejob import (
    IMavenArtifactUploadJobSource,
    IRustCrateUploadJobSource,
)
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
                pass

        # Only schedule uploads for configured distribution builds
        if should_publish and build.recipe.store_upload:
            # Get the archive file and check its contents
            for _, lfa, _ in build.getFiles():
                if lfa.filename.endswith(".tar.xz"):
                    has_crate, has_jar = check_archive_contents(lfa)

                    if has_crate:
                        log.info(
                            "Scheduling upload of Rust crate from %r" % build
                        )
                        getUtility(IRustCrateUploadJobSource).create(build)

                    if has_jar:
                        log.info(
                            "Scheduling upload of Maven artifact from %r"
                            % build
                        )
                        getUtility(IMavenArtifactUploadJobSource).create(build)

                    break


def check_archive_contents(lfa):
    """Check archive for crates and jars.

    Returns a tuple of (has_crate, has_jar)
    """
    has_crate = False
    has_jar = False

    with lzma.open(lfa.open()) as xz:
        with TarFile.open(fileobj=xz) as tar:
            for member in tar.getmembers():
                if member.name.endswith(".crate"):
                    has_crate = True
                    break
                elif member.name.endswith(".jar"):
                    has_jar = True
                    break
    return has_crate, has_jar
