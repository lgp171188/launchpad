# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import base64
import os.path
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict

from charmhelpers.core import hookenv, host, templating
from charms.reactive import (
    clear_flag,
    endpoint_from_flag,
    hook,
    set_flag,
    when,
    when_not,
    when_not_all,
)
from psycopg2.extensions import make_dsn


def install_scripts(config):
    hookenv.log("Installing scripts.")
    host.mkdir(config["scripts_dir"], perms=0o755)
    shutil.copy2(
        "files/push-backups", Path(config["scripts_dir"], "push-backups")
    )
    if config["push_backups_private_ssh_key"]:
        postgres_ssh = Path(os.path.expanduser("~postgres"), ".ssh")
        host.mkdir(
            postgres_ssh, owner="postgres", group="postgres", perms=0o700
        )
        config["push_backups_private_ssh_key_path"] = str(
            postgres_ssh / "id-launchpad-postgresql-extras"
        )
        host.write_file(
            config["push_backups_private_ssh_key_path"],
            base64.b64decode(config["push_backups_private_ssh_key"]),
            owner="postgres",
            group="postgres",
            perms=0o600,
        )


def reload_or_restart_pgbouncer(service):
    subprocess.run(
        ["systemctl", "reload-or-restart", "pgbouncer.service"], check=True
    )


pgbouncer_config = Path("/etc/pgbouncer/pgbouncer.ini")
pgbouncer_databases = Path("/etc/pgbouncer/databases.ini")
pgbouncer_extra_config = Path("/etc/pgbouncer/extra_config.txt")
pgbouncer_userlist = Path("/etc/pgbouncer/userlist.txt")
pgbouncer_override = Path(
    "/etc/systemd/system/pgbouncer.service.d/override.conf"
)


@host.restart_on_change(
    {
        str(pgbouncer_config): ["reload-pgbouncer"],
        str(pgbouncer_databases): ["reload-pgbouncer"],
        str(pgbouncer_extra_config): ["reload-pgbouncer"],
        str(pgbouncer_userlist): ["reload-pgbouncer"],
        str(pgbouncer_override): ["pgbouncer.service"],
    },
    restart_functions={"reload-pgbouncer": reload_or_restart_pgbouncer},
)
def configure_pgbouncer(config):
    hookenv.log("Configuring pgbouncer.")
    templating.render(
        "pgbouncer.ini.j2",
        pgbouncer_config,
        config,
        owner="postgres",
        group="postgres",
        perms=0o644,
    )
    host.write_file(
        pgbouncer_databases,
        config["pgbouncer_db_config"],
        owner="postgres",
        group="postgres",
        perms=0o644,
    )
    host.write_file(
        pgbouncer_extra_config,
        config["pgbouncer_extra_config"],
        owner="postgres",
        group="postgres",
        perms=0o644,
    )
    host.write_file(
        pgbouncer_userlist,
        config["pgbouncer_userlist"],
        owner="postgres",
        group="postgres",
        perms=0o640,
    )
    host.mkdir(pgbouncer_override.parent, perms=0o755)
    shutil.copy2("files/pgbouncer_override.conf", pgbouncer_override)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    hookenv.open_port(config["pgbouncer_port"])


def configure_cron(config):
    hookenv.log("Writing crontab.")
    templating.render(
        "crontab.j2",
        "/etc/cron.d/launchpad-postgresql-extras",
        config,
        perms=0o644,
    )


@when_not("apt.queued_installs", "service.configured")
def configure():
    config = dict(hookenv.config())

    config["scripts_dir"] = "/srv/launchpad/scripts"
    install_scripts(config)

    configure_pgbouncer(config)
    host.service_resume("pgbouncer.service")
    configure_cron(config)

    set_flag("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")


@hook("upgrade-charm")
def upgrade_charm():
    clear_flag("service.configured")


@when("config.changed")
def config_changed():
    clear_flag("service.configured")


def parse_userlist(userlist: str) -> Dict[str, str]:
    """Parse a pgbouncer userlist file.

    This is a deliberately forgiving parser; we only need enough to extract
    the telegraf_stats user's password.  See the pgbouncer(5) manual page
    for the format.
    """
    credentials = {}
    for line in userlist.splitlines():
        m = re.match(r'"([^"]*)" "([^"]*)".*', line)
        if m is not None:
            credentials[m.group(1)] = m.group(2)
    return credentials


@when("service.configured", "telegraf-stats.connected")
@when_not("service.telegraf-stats.configured")
def configure_telegraf_stats():
    config = hookenv.config()
    pgsql = endpoint_from_flag("telegraf-stats.connected")
    credentials = parse_userlist(config["pgbouncer_userlist"])
    telegraf_stats_password = credentials.get("telegraf_stats")
    if not telegraf_stats_password:
        hookenv.status_set(
            "blocked", "No telegraf_stats password in pgbouncer_userlist"
        )
        return
    for relation in pgsql.relations:
        relation.to_publish_raw.update(
            {
                "allowed-subnets": ",".join(
                    sorted(
                        {
                            subnet: True
                            for subnet in hookenv.egress_subnets(
                                relation.relation_id, hookenv.local_unit()
                            )
                        }
                    )
                ),
                "master": make_dsn(
                    database="pgbouncer",
                    host=hookenv.ingress_address(
                        relation.relation_id, hookenv.local_unit()
                    ),
                    password=telegraf_stats_password,
                    port=config["pgbouncer_port"],
                    user="telegraf_stats",
                ),
            }
        )
    set_flag("service.telegraf-stats.configured")


@when("service.telegraf-stats.configured")
@when_not_all("service.configured", "telegraf-stats.connected")
def deconfigure_telegraf_stats():
    clear_flag("service.telegraf-stats.configured")
