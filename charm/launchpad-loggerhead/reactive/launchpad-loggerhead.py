# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import base64
import os.path
import subprocess

import yaml
from charmhelpers.core import hookenv, host, templating
from charms.coordinator import acquire
from charms.launchpad.base import (
    get_service_config,
    lazr_config_files,
    secrets_dir,
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
    set_flag,
    when,
    when_none,
    when_not,
    when_not_all,
)
from ols import base


@host.restart_on_change(
    {
        "/lib/systemd/system/launchpad-loggerhead.service": [
            "launchpad-loggerhead.service"
        ],
    },
)
def configure_systemd(config):
    hookenv.log("Writing systemd service.")
    templating.render(
        "launchpad-loggerhead.service.j2",
        "/lib/systemd/system/launchpad-loggerhead.service",
        config,
    )
    subprocess.run(["systemctl", "daemon-reload"], check=True)


def configure_logrotate(config):
    hookenv.log("Writing logrotate configuration.")
    templating.render(
        "logrotate.conf.j2",
        "/etc/logrotate.d/loggerhead",
        config,
        perms=0o644,
    )


def session_secret_path():
    return os.path.join(secrets_dir(), "cookies.hmac")


def configure_session_secret(config):
    session_secret = base64.b64decode(config["session_secret"].encode())
    host.write_file(
        session_secret_path(), session_secret, group=base.user(), perms=0o440
    )


def config_files():
    files = []
    files.extend(lazr_config_files())
    files.append(config_file_path("launchpad-loggerhead/launchpad-lazr.conf"))
    files.append(session_secret_path())
    return files


@when(
    "config.set.domain_bzr",
    "config.set.session_secret",
    "launchpad.base.configured",
)
@when_none("coordinator.requested.restart", "service.configured")
def configure():
    config = get_service_config()
    config["cache_dir"] = os.path.join(base.base_dir(), "cache")
    host.mkdir(
        config["cache_dir"], owner=base.user(), group=base.user(), perms=0o700
    )
    configure_lazr(
        config,
        "launchpad-loggerhead-lazr.conf",
        "launchpad-loggerhead/launchpad-lazr.conf",
    )
    configure_systemd(config)
    configure_logrotate(config)
    configure_cron(config, "crontab.j2")
    configure_session_secret(config)

    if helpers.any_file_changed(
        [
            base.version_info_path(),
            "/lib/systemd/system/launchpad-loggerhead.service",
        ]
        + config_files()
    ):
        hookenv.log("Config files changed; waiting for restart lock")
        acquire("restart")
    else:
        hookenv.log("Not restarting, since no config files were changed")
        set_flag("service.configured")


@when("coordinator.granted.restart")
def restart():
    hookenv.log("Restarting application server")
    host.service_restart("launchpad-loggerhead.service")
    host.service_resume("launchpad-loggerhead.service")
    set_flag("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")


@when("service.configured")
@when_not_all(
    "config.set.domain_bzr",
    "config.set.session_secret",
    "launchpad.base.configured",
)
def deconfigure():
    clear_flag("service.configured")


@when("nrpe-external-master.available", "service.configured")
@when_not("launchpad.loggerhead.nrpe-external-master.published")
def nrpe_available():
    nrpe = endpoint_from_flag("nrpe-external-master.available")
    config = hookenv.config()
    if config["nagios_check_branch"]:
        nrpe.add_check(
            [
                "/usr/lib/nagios/plugins/check_http",
                "-H",
                "localhost",
                "-p",
                str(config["port_loggerhead"]),
                "-u",
                f"{config['nagios_check_branch']}/files",
            ],
            name="check_launchpad_loggerhead",
            description="Launchpad loggerhead",
            context=config["nagios_context"],
        )
    set_flag("launchpad.loggerhead.nrpe-external-master.published")


@when("launchpad.loggerhead.nrpe-external-master.published")
@when_not("nrpe-external-master.available")
def nrpe_unavailable():
    clear_flag("launchpad.loggerhead.nrpe-external-master.published")


@when("loadbalancer.available", "service.configured")
@when_not("launchpad.loadbalancer.configured")
def configure_loadbalancer():
    config = hookenv.config()

    try:
        service_options = yaml.safe_load(config["haproxy_service_options"])
    except yaml.YAMLError:
        hookenv.log("Could not parse haproxy_service_options YAML")
        hookenv.status_set(
            "blocked", "Bad haproxy_service_options YAML configuration"
        )
        return
    server_options = config["haproxy_server_options"]

    unit_name = hookenv.local_unit().replace("/", "-")
    unit_ip = hookenv.unit_private_ip()
    services = [
        {
            "service_name": "launchpad-loggerhead",
            "service_port": config["port_loggerhead"],
            "service_host": "0.0.0.0",
            "service_options": list(service_options),
            "servers": [
                [
                    f"public_{unit_name}",
                    unit_ip,
                    config["port_loggerhead"],
                    server_options,
                ]
            ],
        },
        {
            "service_name": "launchpad-loggerhead-api",
            "service_port": config["port_loggerhead_api"],
            "service_host": "0.0.0.0",
            "service_options": list(service_options),
            "servers": [
                [
                    f"public_{unit_name}",
                    unit_ip,
                    config["port_loggerhead_api"],
                    server_options,
                ]
            ],
        },
    ]
    services_yaml = yaml.dump(services)

    for rel in hookenv.relations_of_type("loadbalancer"):
        hookenv.relation_set(rel["__relid__"], services=services_yaml)

    set_flag("launchpad.loadbalancer.configured")
