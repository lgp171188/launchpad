# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os.path
from configparser import ConfigParser

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


def www_dir():
    return "/srv/launchpad/www"


@when_not("service.configured")
def configure():
    host.mkdir(www_dir())
    config_path = os.path.join(www_dir(), "cron.ini")
    if not os.path.exists(config_path):
        with open(config_path, "w") as f:
            ConfigParser({"enabled": "True"}).write(f)
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


@when("apache-website.available", "service.configured")
@when_not("service.apache-website.configured")
def configure_apache_website():
    apache_website = endpoint_from_flag("apache-website.available")
    config = dict(hookenv.config())
    config["www_dir"] = www_dir()
    apache_website.set_remote(
        domain=config["domain_cron_control"],
        enabled="true",
        ports="80",
        site_config=templating.render(
            "vhosts/cron-http.conf.j2", None, config
        ),
    )
    set_flag("service.apache-website.configured")


@when("service.apache-website.configured")
@when_not_all("apache-website.available", "service.configured")
def deconfigure_apache_website():
    clear_flag("service.apache-website.configured")
