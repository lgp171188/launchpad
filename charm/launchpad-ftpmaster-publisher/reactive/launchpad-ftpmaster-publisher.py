# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from charmhelpers.core import hookenv, templating
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


def configure_logrotate(config):
    hookenv.log("Writing logrotate configuration.")
    templating.render(
        "logrotate.conf.j2",
        "/etc/logrotate.d/launchpad",
        config,
        perms=0o644,
    )


@when(
    "launchpad.db.configured",
    "launchpad.publisher-parts.configured",
)
@when_not("service.configured")
def configure():
    hookenv.log("Configuring ftpmaster publisher")
    config = get_service_config()
    config["run_parts_location"] = publisher_parts_dir()

    configure_lazr(
        config,
        "launchpad-ftpmaster-publisher-lazr.conf.j2",
        "launchpad-ftpmaster-publisher/launchpad-lazr.conf",
    )
    configure_lazr(
        config,
        "launchpad-ftpmaster-publisher-secrets-lazr.conf.j2",
        "launchpad-ftpmaster-publisher-secrets-lazr.conf",
        secret=True,
    )
    configure_email(config, "launchpad-ftpmaster-publisher")
    configure_logrotate(config)
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
