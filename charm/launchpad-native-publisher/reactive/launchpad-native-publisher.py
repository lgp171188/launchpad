# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import json
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


def check_binaries_exist():
    """Check if required binaries exist and are executable."""
    required_binaries = ["java", "mvn", "rustc", "cargo"]
    missing = []

    for binary in required_binaries:
        try:
            subprocess.check_call(
                ["which", binary],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            missing.append(binary)
            hookenv.log(f"{binary} is missing")

    return missing


def apt_install(*packages):
    """Install packages via apt."""
    subprocess.check_call(["apt-get", "install", "-y"] + list(packages))


def update_alternatives(name, path, priority="100"):
    """Set up update-alternatives for a binary."""
    subprocess.check_call(
        [
            "update-alternatives",
            "--install",
            f"/usr/bin/{name}",
            name,
            path,
            priority,
        ]
    )


def install_dependencies():
    """Install Java and Rust dependencies."""
    config = hookenv.config()
    java_version = config.get("java_version")
    rust_version = config.get("rust_version")

    missing = check_binaries_exist()
    missing_java = any(binary in missing for binary in ["java", "mvn"])
    missing_rust = any(binary in missing for binary in ["rustc", "cargo"])

    try:
        # Install Java and Maven only if needed
        if missing_java:
            subprocess.check_call(["apt-get", "update"])
            hookenv.log("Installing Java packages...")
            apt_install(
                f"openjdk-{java_version}-jdk",
                "maven",
                "libmaven-deploy-plugin-java",
            )

        # Install Rust and Cargo only if needed
        if missing_rust:
            subprocess.check_call(["apt-get", "update"])
            hookenv.log("Installing Rust packages...")
            apt_install(f"rustc-{rust_version}", f"cargo-{rust_version}")

            # Use update-alternatives to create generic command names
            hookenv.log("Setting up alternatives for Rust and Cargo...")
            update_alternatives("rustc", f"/usr/bin/rustc-{rust_version}")
            update_alternatives("cargo", f"/usr/bin/cargo-{rust_version}")

        # Verify installations
        hookenv.log("Verifying installations...")
        missing = check_binaries_exist()
        if missing:
            raise RuntimeError(
                f"Still missing binaries after installation: {missing}"
            )

        hookenv.log("All dependencies successfully installed and verified")

    except subprocess.CalledProcessError as e:
        hookenv.log(f"Failed to install dependencies: {e}", level="ERROR")
        raise
    except RuntimeError as e:
        hookenv.log(str(e), level="ERROR")
        raise


def ensure_dependencies():
    """Ensure required dependencies are installed."""
    hookenv.log("Checking if binaries are already installed...")
    missing = check_binaries_exist()
    if missing:
        install_dependencies()
    else:
        hookenv.log("All required binaries are available")


@when(
    "launchpad.db.configured",
)
@when_not("service.configured")
def configure():
    """Configure the native publisher service."""
    ensure_dependencies()

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

    # Make json module available in templates
    config["json"] = json

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
