# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import subprocess
from multiprocessing import cpu_count

import yaml
from charmhelpers.core import hookenv, host, templating
from charms.coordinator import acquire
from charms.launchpad.base import configure_email, get_service_config
from charms.launchpad.db import (
    lazr_config_files,
    strip_dsn_authentication,
    update_pgpass,
)
from charms.launchpad.payload import (
    config_file_path,
    configure_cron,
    configure_lazr,
)
from charms.reactive import (
    clear_flag,
    endpoint_from_flag,
    helpers,
    hook,
    remove_state,
    set_flag,
    set_state,
    when,
    when_none,
    when_not,
    when_not_all,
)
from ols import base, postgres
from psycopg2.extensions import parse_dsn


def reload_or_restart(service):
    subprocess.run(["systemctl", "reload-or-restart", service], check=True)


def enable_service(service):
    subprocess.run(["systemctl", "enable", service], check=True)


@host.restart_on_change(
    {
        "/etc/rsyslog.d/22-launchpad.conf": ["rsyslog"],
        "/lib/systemd/system/launchpad.service": ["launchpad"],
        config_file_path("launchpad-appserver/gunicorn.conf.py"): [
            "launchpad"
        ],
    },
    restart_functions={
        "rsyslog": reload_or_restart,
        "gunicorn": enable_service,
    },
)
def configure_gunicorn(config):
    hookenv.log("Writing gunicorn configuration.")
    config = dict(config)
    if config["wsgi_workers"] == 0:
        config["wsgi_workers"] = cpu_count() * 2 + 1
    templating.render(
        "gunicorn.conf.py.j2",
        config_file_path("launchpad-appserver/gunicorn.conf.py"),
        config,
    )
    templating.render(
        "launchpad.service.j2", "/lib/systemd/system/launchpad.service", config
    )
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    host.add_user_to_group("syslog", base.user())
    templating.render("rsyslog.j2", "/etc/rsyslog.d/22-launchpad.conf", config)


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
    files.append(config_file_path("launchpad-appserver/launchpad-lazr.conf"))
    files.append(
        config_file_path("launchpad-appserver-secrets-lazr.conf", secret=True)
    )
    return files


@when(
    "launchpad.db.configured",
    "session-db.master.available",
    "memcache.available",
)
@when_none("coordinator.requested.restart", "service.configured")
def configure():
    session_db = endpoint_from_flag("session-db.master.available")
    memcache = endpoint_from_flag("memcache.available")
    config = get_service_config()
    session_db_primary, _ = postgres.get_db_uris(session_db)
    # XXX cjwatson 2022-09-23: Mangle the connection string into a form
    # Launchpad understands.  In the long term it would be better to have
    # Launchpad be able to consume unmodified connection strings.
    update_pgpass(session_db_primary)
    config["db_session"] = strip_dsn_authentication(session_db_primary)
    config["db_session_user"] = parse_dsn(session_db_primary)["user"]
    config["memcache_servers"] = ",".join(
        sorted(
            f"({host}:{port},1)"
            for host, port in memcache.memcache_hosts_ports()
        )
    )
    configure_lazr(
        config,
        "launchpad-appserver-lazr.conf",
        "launchpad-appserver/launchpad-lazr.conf",
    )
    configure_lazr(
        config,
        "launchpad-appserver-secrets-lazr.conf",
        "launchpad-appserver-secrets-lazr.conf",
        secret=True,
    )
    configure_email(config, "launchpad-appserver")
    configure_gunicorn(config)
    configure_logrotate(config)
    configure_cron(config, "crontab.j2")

    if helpers.any_file_changed(
        [base.version_info_path(), "/lib/systemd/system/launchpad.service"]
        + config_files()
    ):
        hookenv.log("Config files changed; waiting for restart lock")
        acquire("restart")
    else:
        hookenv.log("Not restarting, since no config files were changed")
        set_state("service.configured")


@when("coordinator.granted.restart")
def restart():
    hookenv.log("Restarting application server")
    host.service_restart("launchpad.service")
    host.service_resume("launchpad.service")
    set_state("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")


@when("service.configured")
@when_not_all(
    "launchpad.db.configured",
    "session-db.master.available",
    "memcache.available",
)
def deconfigure():
    remove_state("service.configured")


@when("session-db.database.changed", "service.configured")
def session_db_changed():
    remove_state("service.configured")
    remove_state("session-db.database.changed")


@hook("{requires:memcache}-relation-{joined,changed,broken,departed}")
def memcache_relation_changed(memcache):
    remove_state("service.configured")


@when("nrpe-external-master.available", "service.configured")
@when_not("launchpad.appserver.nrpe-external-master.published")
def nrpe_available():
    nrpe = endpoint_from_flag("nrpe-external-master.available")
    config = hookenv.config()
    nrpe.add_check(
        [
            "/usr/lib/nagios/plugins/check_http",
            "-H",
            "localhost",
            "-p",
            str(config["port_main"]),
            "-u",
            "/_status/check",
        ],
        name="check_launchpad_appserver",
        description="Launchpad appserver",
        context=config["nagios_context"],
    )
    set_flag("launchpad.appserver.nrpe-external-master.published")


@when("launchpad.appserver.nrpe-external-master.published")
@when_not_all("nrpe-external-master.available", "service.configured")
def nrpe_unavailable():
    clear_flag("launchpad.appserver.nrpe-external-master.published")


@when("loadbalancer.available", "service.configured")
@when_not("launchpad.loadbalancer.configured")
def configure_loadbalancer():
    config = hookenv.config()

    try:
        service_options_main = yaml.safe_load(
            config["haproxy_service_options_main"]
        )
    except Exception:
        hookenv.log("Could not parse haproxy_service_options_main YAML")
        hookenv.status_set(
            "blocked", "Bad haproxy_service_options_main YAML configuration"
        )
        return
    try:
        service_options_xmlrpc = yaml.safe_load(
            config["haproxy_service_options_xmlrpc"]
        )
    except Exception:
        hookenv.log("Could not parse haproxy_service_options_xmlrpc YAML")
        hookenv.status_set(
            "blocked", "Bad haproxy_service_options_xmlrpc YAML configuration"
        )
        return
    server_options = config["haproxy_server_options"]

    unit_name = hookenv.local_unit().replace("/", "-")
    unit_ip = hookenv.unit_private_ip()
    services = [
        {
            "service_name": "appserver-main",
            "service_port": config["port_main"],
            "service_host": "0.0.0.0",
            "service_options": list(service_options_main),
            "servers": [
                [
                    f"main_{unit_name}",
                    unit_ip,
                    config["port_main"],
                    server_options,
                ]
            ],
        },
        {
            "service_name": "appserver-xmlrpc",
            "service_port": config["port_xmlrpc"],
            "service_host": "0.0.0.0",
            "service_options": list(service_options_xmlrpc),
            "servers": [
                [
                    f"xmlrpc_{unit_name}",
                    unit_ip,
                    config["port_xmlrpc"],
                    server_options,
                ]
            ],
        },
    ]
    services_yaml = yaml.dump(services)

    for rel in hookenv.relations_of_type("loadbalancer"):
        hookenv.relation_set(rel["__relid__"], services=services_yaml)

    set_state("launchpad.loadbalancer.configured")


@when("launchpad.loadbalancer.configured")
@when_not_all("loadbalancer.available", "service.configured")
def deconfigure_loadbalancer():
    remove_state("launchpad.loadbalancer.configured")
