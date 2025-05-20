# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import subprocess

import yaml
from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import get_service_config
from charms.launchpad.db import lazr_config_files
from charms.launchpad.payload import (
    config_file_path,
    configure_cron,
    configure_lazr,
)
from charms.reactive import (
    helpers,
    remove_state,
    set_state,
    when,
    when_not,
    when_not_all,
)
from ols import base
from yaml.error import YAMLError

CHARM_CELERY_SERVICES = [
    "celerybeat_native_publisher",
    "celeryd_native_publisher_job",
    "celeryd_native_publisher_job_slow",
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
        config_file_path("launchpad-native-publisher/launchpad-lazr.conf")
    )
    files.append(
        config_file_path(
            "launchpad-native-publisher-secrets-lazr.conf",
            secret=True,
        )
    )
    files.append(
        config_file_path("launchpad-base-secrets-lazr.conf", secret=True)
    )
    return files


@host.restart_on_change(
    {
        "/lib/systemd/system/celerybeat_native_publisher.service": [
            "celerybeat_native_publisher",
        ],
        "/lib/systemd/system/celeryd_native_publisher_job.service": [
            "celeryd_native_publisher_job",
        ],
        "/lib/systemd/system/celeryd_native_publisher_job_slow.service": [
            "celeryd_native_publisher_job_slow",
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
)
@when_not("service.configured")
def configure():
    """Configure the native publisher service."""
    config = get_service_config()
    try:
        if config.get("craftbuild_config"):
            config["craftbuild_config"] = yaml.safe_load(
                config["craftbuild_config"]
            )
            hookenv.log("Successfully parsed craftbuild_config")
        else:
            config["craftbuild_config"] = {}
            hookenv.log(
                "No craftbuild_config provided, using empty dictionary"
            )
    except YAMLError as e:
        config["craftbuild_config"] = {}
        hookenv.log(f"Error parsing craftbuild_config: {e}", level="ERROR")

    configure_lazr(
        config,
        "launchpad-native-publisher-lazr.conf.j2",
        "launchpad-native-publisher/launchpad-lazr.conf",
    )
    configure_lazr(
        config,
        "launchpad-native-publisher-secrets-lazr.conf.j2",
        "launchpad-native-publisher-secrets-lazr.conf",
        secret=True,
    )
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
)
def deconfigure():
    remove_state("service.configured")


@when("install")
def install_packages():
    """Install Rust, Cargo, Java and Maven dependencies."""
    hookenv.status_set("maintenance", "Installing packages")

    # Get configuration values
    config = hookenv.config()
    rust_version = config.get("rust-version")
    java_version = config.get("java-version")

    subprocess.check_call(["apt-get", "update"])

    hookenv.log(f"Installing Java {java_version} and Maven...")
    subprocess.check_call(
        [
            "apt-get",
            "install",
            "-y",
            f"openjdk-{java_version}-jdk",
            "maven",
            "libmaven-deploy-plugin-java",
        ]
    )

    hookenv.log(f"Installing Rust {rust_version} and Cargo...")
    subprocess.check_call(
        [
            "apt-get",
            "install",
            "-y",
            f"rustc-{rust_version}",
            f"cargo-{rust_version}",
        ]
    )

    # Use update-alternatives to create generic command names
    hookenv.log("Setting up alternatives for Rust and Cargo...")
    subprocess.check_call(
        [
            "update-alternatives",
            "--install",
            "/usr/bin/rustc",
            "rustc",
            f"/usr/bin/rustc-{rust_version}",
            "100",
        ]
    )
    subprocess.check_call(
        [
            "update-alternatives",
            "--install",
            "/usr/bin/cargo",
            "cargo",
            f"/usr/bin/cargo-{rust_version}",
            "100",
        ]
    )

    # Verify the installations
    hookenv.log("Verifying installations...")
    try:
        subprocess.check_call(["which", "java"])
        subprocess.check_output(["java", "-version"], stderr=subprocess.STDOUT)
        subprocess.check_call(["which", "mvn"])
        subprocess.check_output(["mvn", "--version"])
        subprocess.check_call(["which", "rustc"])
        subprocess.check_output(["rustc", "--version"])
        subprocess.check_call(["which", "cargo"])
        subprocess.check_output(["cargo", "--version"])

        hookenv.log("All packages successfully installed")
        set_state("packages.installed")
    except subprocess.CalledProcessError as e:
        hookenv.log(f"Failed to verify installations: {str(e)}", level="ERROR")
        set_state("packages.failed")
        hookenv.status_set("blocked", "Failed to install packages")
