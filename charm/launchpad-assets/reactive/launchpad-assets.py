# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os.path
import subprocess
from pathlib import Path

from charmhelpers.core import hookenv, host, templating
from charms.reactive import (
    clear_flag,
    endpoint_from_flag,
    set_flag,
    when,
    when_all,
    when_not,
    when_not_all,
)
from ols import base


@host.restart_on_change(
    {
        "/lib/systemd/system/convoy.service": ["convoy.service"],
        "/lib/systemd/system/convoy.socket": ["convoy.socket"],
    }
)
def configure_convoy(config):
    hookenv.log("Writing convoy configuration.")

    # Update convoy symlinks.
    build_label = config["build_label"]
    convoy_path = Path(base.base_dir()) / "convoy"
    convoy_path.mkdir(parents=True, exist_ok=True)
    link_path = convoy_path / f"rev{build_label}"
    if not link_path.is_symlink():
        link_path.symlink_to(Path(base.code_dir()) / "build" / "js")
    for link_path in convoy_path.iterdir():
        if link_path.name.startswith("rev") and link_path.is_symlink():
            if not link_path.exists():
                link_path.unlink()

    templating.render(
        "convoy.service.j2", "/lib/systemd/system/convoy.service", config
    )
    templating.render(
        "convoy.socket.j2", "/lib/systemd/system/convoy.socket", config
    )
    subprocess.run(["systemctl", "daemon-reload"])


def get_service_config():
    config = hookenv.config()
    config.update(
        {
            "base_dir": base.base_dir(),
            "code_dir": base.code_dir(),
            "logs_dir": base.logs_dir(),
            "payloads_dir": base.payloads_dir(),
        }
    )
    return config


def config_file_path(name):
    return os.path.join(base.code_dir(), "production-configs", name)


@when("ols.configured")
@when_not("service.configured")
def configure():
    config = get_service_config()
    hookenv.log("Writing launchpad-assets/launchpad-lazr.conf.")
    templating.render(
        "launchpad-assets-lazr.conf",
        config_file_path("launchpad-assets/launchpad-lazr.conf"),
        config,
        owner="root",
        group=base.user(),
        perms=0o444,
    )
    configure_convoy(config)
    set_flag("service.configured")


@when_all("service.configured", "apache-website.available")
@when_not("service.apache-configured")
def send_apache_website():
    apache = endpoint_from_flag("apache-website.available")
    config = get_service_config()
    apache.send_domain(f"assets.{config['domain']}")
    apache.send_site_config(templating.render("vhost.conf.j2", None, config))
    # interface-apache incorrectly sets `modules`, not `site_modules`.  Work
    # around this.
    apache.set_remote(site_modules="headers proxy proxy_http")
    apache.send_ports([config["port_assets"]])
    apache.send_enabled()
    hookenv.status_set("active", "Ready")
    set_flag("service.apache-configured")


@when("service.apache-configured")
@when_not_all("service.configured", "apache-website.available")
def apache_deconfigured():
    hookenv.status_set("blocked", "Website not yet configured")
    clear_flag("service.apache-configured")
