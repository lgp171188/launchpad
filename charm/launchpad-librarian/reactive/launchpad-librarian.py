# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os.path
import subprocess

from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import (
    config_file_path,
    configure_cron,
    configure_email,
    configure_lazr,
    get_service_config,
    lazr_config_files,
    strip_dsn_authentication,
    update_pgpass,
)
from charms.reactive import (
    endpoint_from_flag,
    helpers,
    remove_state,
    set_state,
    when,
    when_not,
)
from ols import base, postgres
from psycopg2.extensions import parse_dsn


def configure_systemd(config):
    hookenv.log("Writing systemd service.")
    templating.render(
        "launchpad-librarian.service.j2",
        "/lib/systemd/system/launchpad-librarian.service",
        config,
    )
    templating.render(
        "launchpad-librarian@.service.j2",
        "/lib/systemd/system/launchpad-librarian@.service",
        config,
    )
    templating.render(
        "launchpad-librarian-generator.j2",
        "/lib/systemd/system-generators/launchpad-librarian-generator",
        config,
        perms=0o555,
    )
    subprocess.run(["systemctl", "daemon-reload"])


def configure_logrotate(config):
    hookenv.log("Writing logrotate configuration.")
    templating.render(
        "logrotate.conf.j2",
        "/etc/logrotate.d/launchpad-librarian",
        config,
        perms=0o644,
    )


def config_files():
    files = []
    files.extend(lazr_config_files())
    files.append(config_file_path("launchpad-librarian/launchpad-lazr.conf"))
    files.append(
        config_file_path("launchpad-librarian-secrets-lazr.conf", secret=True)
    )
    return files


@when(
    "config.set.port_download_base",
    "config.set.port_restricted_download_base",
    "config.set.port_restricted_upload_base",
    "config.set.port_upload_base",
    "launchpad.base.configured",
    "session-db.master.available",
)
@when_not("service.configured")
def configure():
    session_db = endpoint_from_flag("session-db.master.available")
    config = get_service_config()
    session_db_primary, _ = postgres.get_db_uris(session_db)
    # XXX cjwatson 2022-09-23: Mangle the connection string into a form
    # Launchpad understands.  In the long term it would be better to have
    # Launchpad be able to consume unmodified connection strings.
    update_pgpass(session_db_primary)
    config["db_session"] = strip_dsn_authentication(session_db_primary)
    config["db_session_user"] = parse_dsn(session_db_primary)["user"]
    config["librarian_dir"] = os.path.join(base.base_dir(), "librarian")
    host.mkdir(
        config["librarian_dir"],
        owner=base.user(),
        group=base.user(),
        perms=0o700,
    )
    for i in range(config["workers"]):
        config["logfile"] = os.path.join(
            base.logs_dir(), f"librarian{i + 1}.log"
        )
        config["worker_download_port"] = config["port_download_base"] + i
        config["worker_restricted_download_port"] = (
            config["port_restricted_download_base"] + i
        )
        config["worker_restricted_upload_port"] = (
            config["port_restricted_upload_base"] + i
        )
        config["worker_upload_port"] = config["port_upload_base"] + i
        configure_lazr(
            config,
            "launchpad-librarian-lazr.conf",
            f"launchpad-librarian{i + 1}/launchpad-lazr.conf",
        )
        configure_email(config, f"launchpad-librarian{i + 1}")
    configure_lazr(
        config,
        "launchpad-librarian-secrets-lazr.conf",
        "launchpad-librarian-secrets-lazr.conf",
        secret=True,
    )
    configure_systemd(config)
    configure_logrotate(config)
    configure_cron(config, "crontab.j2")

    if helpers.any_file_changed(
        [
            base.version_info_path(),
            "/lib/systemd/system/launchpad-librarian.service",
            "/lib/systemd/system/launchpad-librarian@.service",
        ]
        + config_files()
    ):
        hookenv.log("Config files changed; restarting")
        # Be careful to restart instances one at a time to minimize downtime.
        # XXX cjwatson 2023-03-28: This doesn't deal with stopping instances
        # when the worker count is reduced.
        for i in range(config["workers"]):
            host.service_restart(f"launchpad-librarian@{i + 1}")
    else:
        hookenv.log("Not restarting, since no config files were changed")
    host.service_resume("launchpad-librarian.service")

    set_state("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")


@when("service.configured")
@when_not("session-db.master.available")
def deconfigure():
    remove_state("service.configured")


@when("session-db.database.changed", "service.configured")
def session_db_changed():
    remove_state("service.configured")
    remove_state("session-db.database.changed")
