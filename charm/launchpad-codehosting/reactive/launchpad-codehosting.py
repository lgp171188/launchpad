# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import base64
import os
import subprocess

import yaml
from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import configure_email, get_service_config
from charms.launchpad.db import lazr_config_files
from charms.launchpad.payload import (
    config_file_path,
    configure_cron,
    configure_lazr,
)
from charms.reactive import (
    clear_flag,
    endpoint_from_flag,
    helpers,
    remove_state,
    set_flag,
    set_state,
    when,
    when_not,
    when_not_all,
)
from ols import base


def base64_decode(value):
    return base64.b64decode(value.encode("ASCII"))


def configure_logrotate(config):
    hookenv.log("Writing logrotate configuration.")
    templating.render(
        "logrotate.conf.j2",
        "/etc/logrotate.d/launchpad",
        config,
        perms=0o644,
    )


def configure_systemd(config):
    hookenv.log("Writing launchpad-bzr-sftp systemd service.")
    templating.render(
        "launchpad-bzr-sftp.service.j2",
        "/lib/systemd/system/launchpad-bzr-sftp.service",
        config,
    )
    templating.render(
        "launchpad-bzr-sftp@.service.j2",
        "/lib/systemd/system/launchpad-bzr-sftp@.service",
        config,
    )
    templating.render(
        "launchpad-bzr-sftp-generator.j2",
        "/lib/systemd/system-generators/launchpad-bzr-sftp-generator",
        config,
        perms=0o555,
    )
    subprocess.run(["systemctl", "daemon-reload"])


def config_files():
    files = []
    files.extend(lazr_config_files())
    config = get_service_config()
    files.append(config_file_path("launchpad-codehosting/launchpad-lazr.conf"))
    for i in range(config["workers"]):
        files.append(
            config_file_path(
                f"launchpad-codehosting{i + 1}/launchpad-lazr.conf"
            )
        )
    return files


def configure_scripts(config):
    hookenv.log(
        f"Creating {config['scripts_dir']}, if it doesn't exist already."
    )
    host.mkdir(
        config["scripts_dir"],
        owner=config["user"],
        group=config["user"],
        perms=0o755,
        force=True,
    )
    hookenv.log("Writing the cleanlogs script.")
    templating.render(
        "cleanlogs.j2",
        f"{config['scripts_dir']}/cleanlogs",
        config,
        perms=0o755,
    )
    host.mkdir(
        f"{config['logs_dir']}/sftp-logs",
        owner=config["user"],
        group=config["user"],
        perms=0o755,
        force=True,
    )
    hookenv.log("Writing the branch rewrite wrapper script.")
    templating.render(
        "rewrite_wrapper.sh.j2",
        f"{config['scripts_dir']}/rewrite_wrapper.sh",
        config,
        owner=config["user"],
        group=config["user"],
        perms=0o755,
    )


def configure_ssh_keys(config):
    host_key_pair_path = f"{config['base_dir']}/keys"
    hookenv.log(f"Creating {host_key_pair_path} to store the SSH host keys.")
    user = config["user"]
    host.mkdir(
        host_key_pair_path,
        owner=user,
        group=user,
        perms=0o755,
        force=True,
    )
    ssh_private_key_file = f"{host_key_pair_path}/ssh_host_key_rsa"
    ssh_public_key_file = f"{ssh_private_key_file}.pub"
    if (
        config["codehosting_private_ssh_key"]
        and config["codehosting_public_ssh_key"]
    ):
        hookenv.log("Writing the SSH host key pair.")
        host.write_file(
            ssh_private_key_file,
            base64_decode(config["codehosting_private_ssh_key"]),
            owner=user,
            group=user,
            perms=0o600,
        )
        host.write_file(
            ssh_public_key_file,
            base64_decode(config["codehosting_public_ssh_key"]),
            owner=user,
            group=user,
            perms=0o644,
        )
    else:
        hookenv.log(
            "SSH key pair not configured. Deleting existing keys, if present."
        )
        for path in (ssh_private_key_file, ssh_public_key_file):
            if os.path.exists(path):
                os.unlink(path)


def configure_codehosting_lazr_config(config):
    hookenv.log("Writing lazr configuration.")
    # XXX lgp171188: 2023-10-26: This template recreates the value of
    # config["bzr_repositories_root"] since it can't use it directly
    # due to it being in a separate handler that is executed much later.
    # Fix this to unify the definition and usage of this configuration
    # value.
    configure_lazr(
        config,
        "launchpad-codehosting-lazr-common.conf.j2",
        "launchpad-codehosting/launchpad-lazr.conf",
    )
    for i in range(config["workers"]):
        config["service_access_log_file"] = f"codehosting-{i + 1}-access.log"
        config["service_sftp_port"] = config["port_bzr_sftp_base"] + i
        config["service_web_status_port"] = config["port_web_status_base"] + i
        config["service_oops_prefix"] = f"{config['oops_prefix']}{i + 1}"
        configure_lazr(
            config,
            "launchpad-codehosting-sftp-lazr.conf.j2",
            f"launchpad-codehosting{i + 1}/launchpad-lazr.conf",
        )


@when("launchpad.db.configured")
@when_not("service.configured")
def configure():
    config = get_service_config()
    configure_codehosting_lazr_config(config)
    configure_email(config, "launchpad-codehosting")
    configure_logrotate(config)
    configure_cron(config, "crontab.j2")
    configure_scripts(config)
    configure_ssh_keys(config)
    configure_systemd(config)
    if config["active"]:
        if helpers.any_file_changed(
            [
                base.version_info_path(),
                "/lib/systemd/system/launchpad-bzr-sftp.service",
                "/lib/systemd/system/launchpad-bzr-sftp@.service",
                "/lib/systemd/system-generators/launchpad-bzr-sftp-generator",
            ]
            + config_files()
        ):
            hookenv.log(
                "Config files changed; restarting"
                " the launchpad-bzr-sftp service."
            )
            for i in range(config["workers"]):
                host.service_restart(f"launchpad-bzr-sftp@{i + 1}")
        else:
            hookenv.log("Not restarting since no config files were changed.")
        host.service_resume("launchpad-bzr-sftp.service")

    set_state("service.configured")


def get_vhost_config(config):
    hookenv.log("Rendering the virtual hosts configuration.")
    return "\n".join(
        [
            templating.render("vhosts/common.conf", None, config),
            templating.render("vhosts/bazaar_http.conf.j2", None, config),
            templating.render("vhosts/bazaar_https.conf.j2", None, config),
            templating.render(
                "vhosts/bazaar_internal_branch_by_id.conf.j2", None, config
            ),
        ]
    )


def configure_document_root(config):
    hookenv.log("Configuring the document root.")
    user = config["user"]
    document_root = f"{config['base_dir']}/www"
    hookenv.log(f"Creating the document root directory {document_root}.")
    host.mkdir(
        document_root,
        owner=user,
        group=user,
        perms=0o755,
        force=True,
    )
    data_dir = f"{config['base_dir']}/data"
    hookenv.log(f"Creating the data directory {data_dir}")
    host.mkdir(data_dir, owner=user, group=user, perms=0o755, force=True)
    config["bzr_repositories_root"] = f"{data_dir}/mirrors"
    host.mkdir(
        config["bzr_repositories_root"],
        owner=user,
        group=user,
        perms=0o755,
        force=True,
    )
    code_dir = config["code_dir"]
    site_packages_dir = (
        subprocess.check_output(
            [
                f"{code_dir}/env/bin/python",
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ]
        )
        .strip()
        .decode("utf-8")
    )
    assert site_packages_dir.startswith(f"{code_dir}/env")
    config["loggerhead_static_dir"] = f"{site_packages_dir}/loggerhead/static"


@when(
    "service.configured",
    "config.set.domain_bzr",
    "config.set.domain_bzr_internal",
    "apache-website.available",
)
@when_not("service.apache-website.configured")
def configure_apache_website():
    apache_website = endpoint_from_flag("apache-website.available")
    config = get_service_config()
    configure_document_root(config)
    apache_website.set_remote(
        domain=config["domain_bzr"],
        enabled="true",
        ports=f"80 8080 {config['port_bzr_internal']}",
        site_config=get_vhost_config(config),
        site_modules="headers proxy proxy_http rewrite",
    )
    hookenv.status_set("active", "Ready")
    set_flag("service.apache-website.configured")


@when("service.apache-website.configured")
@when_not_all("service.configured", "apache-website.available")
def apache_deconfigured():
    hookenv.status_set("blocked", "Website not yet configured")
    clear_flag("service.apache-website.configured")


@when("service.configured")
@when_not("launchpad.db.configured")
def deconfigure():
    remove_state("service.configured")


@when("frontend-loadbalancer.available", "service.configured")
@when_not("launchpad-codehosting.frontend-loadbalancer.configured")
def configure_frontend_loadbalancer():
    config = hookenv.config()
    try:
        service_options_http = yaml.safe_load(
            config["haproxy_service_options_http"]
        )
    except yaml.YAMLError:
        hookenv.log("Could not parse haproxy_service_options_http yaml.")
        hookenv.status_set("blocked", "Bad haproxy_service_options_http value")
        return
    try:
        service_options_https = yaml.safe_load(
            config["haproxy_service_options_https"]
        )
    except yaml.YAMLError:
        hookenv.log("Could not parse haproxy_service_options_https yaml.")
        hookenv.status_set(
            "blocked", "Bad haproxy_service_options_https value"
        )
        return
    try:
        service_options_ssh = yaml.safe_load(
            config["haproxy_service_options_ssh"]
        )
    except yaml.YAMLError:
        hookenv.log("Could not parse haproxy_service_options_ssh yaml.")
        hookenv.status_set(
            "blocked", "Bad codehosting_lb_service_options_ssh value"
        )
        return

    server_options = config["haproxy_fe_server_options"]
    ssh_server_options = config["haproxy_fe_server_options_ssh"]

    unit_name = hookenv.local_unit().replace("/", "-")
    unit_ip = hookenv.unit_private_ip()
    services = [
        {
            "service_name": "launchpad-codehosting-http",
            "service_port": 80,
            "service_host": "0.0.0.0",
            "service_options": list(service_options_http),
            "servers": [
                [
                    f"http_{unit_name}",
                    unit_ip,
                    80,
                    server_options,
                ],
            ],
        },
        {
            "service_name": "launchpad-codehosting-https",
            "service_port": 443,
            "service_host": "0.0.0.0",
            "service_options": [
                'http-request set-header X-Forwarded-Scheme "https"'
            ]
            + list(service_options_https),
            "servers": [
                [
                    f"https_{unit_name}",
                    unit_ip,
                    8080,
                    server_options,
                ],
            ],
            "crts": ["DEFAULT"],
        },
        {
            "service_name": "launchpad-codehosting-ssh",
            "service_port": config["port_lb_bzr_sftp"],
            "service_host": "0.0.0.0",
            "service_options": list(service_options_ssh),
            "servers": [
                [
                    f"ssh_{unit_name}_{i + 1}",
                    unit_ip,
                    config["port_bzr_sftp_base"] + i,
                    f"port {config['port_web_status_base'] + i} "
                    + ssh_server_options,
                ]
                for i in range(config["workers"])
            ],
        },
    ]
    services_yaml = yaml.dump(services)
    for rel in hookenv.relations_of_type("frontend-loadbalancer"):
        hookenv.relation_set(rel["__relid__"], services=services_yaml)

    set_state("launchpad-codehosting.frontend-loadbalancer.configured")


@when("loadbalancer.available", "service.configured")
@when_not("launchpad-codehosting.loadbalancer.configured")
def configure_loadbalancer():
    config = hookenv.config()
    try:
        service_options = yaml.safe_load(
            config["haproxy_service_options_internal_branch_by_id"]
        )
    except yaml.YAMLError:
        hookenv.log(
            "Could not parse "
            "haproxy_service_options_internal_branch_by_id yaml."
        )
        hookenv.status_set(
            "blocked",
            "Bad haproxy_service_options_internal_branch_by_id value",
        )
        return
    server_options = config["haproxy_server_options"]
    unit_name = hookenv.local_unit().replace("/", "-")
    unit_ip = hookenv.unit_private_ip()
    services = [
        {
            "service_name": "launchpad-codehosting-internal-branch-by-id",
            "service_port": config["port_bzr_internal"],
            "service_host": "0.0.0.0",
            "service_options": list(service_options),
            "servers": [
                [
                    f"http_{unit_name}",
                    unit_ip,
                    config["port_bzr_internal"],
                    server_options,
                ],
            ],
        },
    ]
    services_yaml = yaml.dump(services)
    for rel in hookenv.relations_of_type("loadbalancer"):
        hookenv.relation_set(rel["__relid__"], services=services_yaml)

    set_state("launchpad-codehosting.loadbalancer.configured")
