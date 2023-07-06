# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import base64
import os.path
import subprocess

import yaml
from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import get_service_config
from charms.launchpad.db import lazr_config_files
from charms.launchpad.payload import (
    config_file_path,
    configure_cron,
    configure_lazr,
    home_dir,
)
from charms.reactive import helpers, remove_state, set_state, when, when_not
from ols import base


def base64_decode(value):
    return base64.b64decode(value.encode("ASCII"))


def configure_keys(config):
    ssh_dir = os.path.join(home_dir(), ".ssh")
    ssh_private_path = os.path.join(ssh_dir, "builder-reset")
    ssh_public_path = os.path.join(ssh_dir, "builder-reset.pub")
    if (
        config["builder_reset_private_ssh_key"]
        and config["builder_reset_public_ssh_key"]
    ):
        hookenv.log("Writing SSH keys.")
        if not os.path.exists(ssh_dir):
            host.mkdir(
                ssh_dir, owner=base.user(), group=base.user(), perms=0o700
            )
        host.write_file(
            ssh_private_path,
            base64_decode(config["builder_reset_private_ssh_key"]),
            owner=base.user(),
            group=base.user(),
            perms=0o600,
        )
        host.write_file(
            ssh_public_path,
            base64_decode(config["builder_reset_public_ssh_key"]),
            owner=base.user(),
            group=base.user(),
            perms=0o644,
        )
    else:
        for path in (ssh_private_path, ssh_public_path):
            if os.path.exists(path):
                os.unlink(path)


def configure_service(config):
    hookenv.log("Writing systemd service.")
    templating.render(
        "launchpad-buildd-manager.service.j2",
        "/lib/systemd/system/launchpad-buildd-manager.service",
        config,
    )
    subprocess.run(["systemctl", "daemon-reload"], check=True)


def configure_logrotate(config):
    hookenv.log("Writing logrotate configuration.")
    templating.render(
        "logrotate.conf.j2",
        "/etc/logrotate.d/launchpad-buildd-manager",
        config,
        perms=0o644,
    )


def config_files():
    files = []
    files.extend(lazr_config_files())
    files.append(
        config_file_path("launchpad-buildd-manager/launchpad-lazr.conf")
    )
    files.append(
        config_file_path(
            "launchpad-buildd-manager-secrets-lazr.conf", secret=True
        )
    )
    return files


@when("launchpad.db.configured")
@when_not("service.configured")
def configure():
    config = get_service_config()
    config["buildd_manager_dir"] = os.path.join(
        base.base_dir(), "buildd-manager"
    )
    config["cibuild_config"] = yaml.safe_load(config["cibuild_config"])
    host.mkdir(
        config["buildd_manager_dir"],
        owner=base.user(),
        group=base.user(),
        perms=0o755,
    )
    configure_lazr(
        config,
        "launchpad-buildd-manager-lazr.conf",
        "launchpad-buildd-manager/launchpad-lazr.conf",
    )
    configure_lazr(
        config,
        "launchpad-buildd-manager-secrets-lazr.conf",
        "launchpad-buildd-manager-secrets-lazr.conf",
        secret=True,
    )
    configure_keys(config)
    configure_service(config)
    configure_logrotate(config)
    configure_cron(config, "crontab.j2")

    if config["active"]:
        if helpers.any_file_changed(
            [
                base.version_info_path(),
                "/lib/systemd/system/launchpad-buildd-manager.service",
            ]
            + config_files()
        ):
            hookenv.log("Config files changed; restarting buildd-manager")
            host.service_restart("launchpad-buildd-manager")
        host.service_resume("launchpad-buildd-manager")
    else:
        host.service_pause("launchpad-buildd-manager")

    set_state("service.configured")


@when("service.configured")
@when_not("launchpad.db.configured")
def deconfigure():
    remove_state("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")
