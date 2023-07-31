# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import subprocess

from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import configure_email, get_service_config
from charms.launchpad.db import lazr_config_files
from charms.launchpad.payload import (
    config_file_path,
    configure_cron,
    configure_lazr,
)
from charms.reactive import (
    endpoint_from_flag,
    helpers,
    remove_state,
    set_state,
    when,
    when_not,
    when_not_all,
)
from ols import base

CHARM_CELERY_SERVICES = [
    "celerybeat-bzrsyncd",
    "celeryd_bzrsyncd_job",
    "celeryd_bzrsyncd_job_slow",
]


def configure_logrotate(config):
    hookenv.log("Writing logrotate configuration.")
    templating.render(
        "logrotate.conf.j2",
        "/etc/logrotate.d/launchpad",
        config,
        perms=0o644,
    )


def config_files():
    files = []
    files.extend(lazr_config_files())
    files.append(
        config_file_path("launchpad-scripts-bzrsyncd/launchpad-lazr.conf")
    )
    files.append(
        config_file_path(
            "launchpad-scripts-bzrsyncd-secrets-lazr.conf", secret=True
        )
    )
    return files


@host.restart_on_change(
    {
        "/lib/systemd/system/celerybeat-bzrsyncd.service": [
            "celerybeat-bzrsyncd",
        ],
        "/lib/systemd/system/celeryd_bzrsyncd_job.service": [
            "celeryd_bzrsyncd_job",
        ],
        "/lib/systemd/system/celeryd_bzrsyncd_job_slow.service": [
            "celeryd_bzrsyncd_job_slow",
        ],
    }
)
def configure_celery(config):
    hookenv.log("Writing celery systemd service files.")
    destination_dir = "/lib/systemd/system"
    for service in CHARM_CELERY_SERVICES:
        templating.render(
            f"{service}.service.j2",
            f"{destination_dir}/{service}.service",
            config,
        )
    subprocess.check_call(["systemctl", "daemon-reload"])


def perform_action_on_services(services, action):
    for service in services:
        action(service)


@when(
    "launchpad.db.configured",
    "memcache.available",
)
@when_not("service.configured")
def configure():
    config = get_service_config()
    memcache = endpoint_from_flag("memcache.available")
    config["memcache_servers"] = ",".join(
        sorted(
            f"({host}:{port},1)"
            for host, port in memcache.memcache_hosts_ports()
        )
    )
    configure_lazr(
        config,
        "launchpad-scripts-bzrsyncd-lazr.conf.j2",
        "launchpad-scripts-bzrsyncd/launchpad-lazr.conf",
    )
    configure_email(config, "launchpad-scripts")
    configure_logrotate(config)
    configure_cron(config, "crontab.j2")
    configure_celery(config)

    if config["active"]:
        if helpers.any_file_changed(
            [
                base.version_info_path(),
            ]
            + config_files()
        ):
            hookenv.log("Config files or payload changed; restarting services")
            perform_action_on_services(
                CHARM_CELERY_SERVICES, host.service_restart
            )
        perform_action_on_services(CHARM_CELERY_SERVICES, host.service_resume)
    else:
        perform_action_on_services(CHARM_CELERY_SERVICES, host.service_pause)

    set_state("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")


@when("service.configured")
@when_not_all(
    "launchpad.db.configured",
    "memcache.available",
)
def deconfigure():
    remove_state("service.configured")
