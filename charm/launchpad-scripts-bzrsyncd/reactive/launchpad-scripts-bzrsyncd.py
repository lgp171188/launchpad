# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import subprocess

from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import configure_email, get_service_config
from charms.launchpad.payload import configure_cron, configure_lazr
from charms.reactive import (
    endpoint_from_flag,
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
    service_files = (
        "celerybeat_bzrsyncd.service",
        "celeryd_bzrsyncd_job.service",
        "celeryd_bzrsyncd_job_slow.service",
    )
    for service_file in service_files:
        templating.render(
            f"{service_file}.j2",
            f"{destination_dir}/{service_file}",
            config,
        )
    subprocess.check_call(["systemctl", "daemon-reload"])
    for service_file in service_files:
        subprocess.check_call(["systemctl", "enable", service_file])


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
