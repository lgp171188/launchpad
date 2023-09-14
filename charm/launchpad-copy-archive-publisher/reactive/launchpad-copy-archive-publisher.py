# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os

from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import configure_email, get_service_config
from charms.launchpad.payload import configure_cron, configure_lazr
from charms.launchpad.publisher_parts import publisher_parts_dir
from charms.reactive import (
    remove_state,
    set_state,
    when,
    when_not,
    when_not_all,
)
from ols import base


def configure_logrotate(config):
    hookenv.log("Writing logrotate configuration.")
    templating.render(
        source="logrotate.conf.j2",
        target="/etc/logrotate.d/launchpad",
        context=config,
        perms=0o644,
    )


def configure_copy_publish_archives_cronjob(config):
    hookenv.log("Setting up launchpad-copy-archives cronjob")
    templating.render(
        source="cron.launchpad-copy-archives.sh.j2",
        target=os.path.join(
            base.base_dir(), "bin", "cron.publish-copy-archives.sh"
        ),
        context=config,
        perms=0o755,
    )
    host.mkdir(
        f"{base.base_dir()}/rebuild-test", group=base.user(), perms=0o775
    )


@when(
    "launchpad.db.configured",
    "launchpad.publisher-parts.configured",
)
@when_not("service.configured")
def configure():
    hookenv.log("Configuring copy-archive-publisher")
    config = get_service_config()
    config["run_parts_location"] = publisher_parts_dir()

    configure_lazr(
        config,
        template="launchpad-copy-archive-publisher-lazr.conf.j2",
        name="launchpad-copy-archive-publisher/launchpad-lazr.conf",
    )
    configure_lazr(
        config,
        template="launchpad-copy-archive-publisher-secrets-lazr.conf.j2",
        name="launchpad-copy-archive-publisher-secrets-lazr.conf",
        secret=True,
    )
    configure_email(config, "launchpad-copy-archive-publisher")
    configure_logrotate(config)
    configure_copy_publish_archives_cronjob(config)
    configure_cron(config, "crontab.j2")
    set_state("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")


@when("service.configured")
@when_not_all(
    "launchpad.db.configured",
    "launchpad.publisher-parts.configured",
)
def deconfigure():
    remove_state("service.configured")
