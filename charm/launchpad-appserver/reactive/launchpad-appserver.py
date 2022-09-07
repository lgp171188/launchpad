# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import subprocess
from multiprocessing import cpu_count

from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import (
    config_file_path,
    configure_lazr,
    get_service_config,
    lazr_config_files,
)
from charms.reactive import helpers, set_state, when, when_not
from ols import base


def reload_or_restart(service):
    subprocess.run(["systemctl", "reload-or-restart", service], check=True)


def enable_service(service):
    subprocess.run(["systemctl", "enable", service], check=True)


@host.restart_on_change(
    {
        "/etc/rsyslog.d/22-launchpad.conf": ["rsyslog"],
        "/lib/systemd/system/launchpad.service": ["launchpad"],
        config_file_path("gunicorn.conf.py"): ["launchpad"],
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
        "gunicorn.conf.py.j2", config_file_path("gunicorn.conf.j2"), config
    )
    templating.render(
        "launchpad.service.j2", "/lib/systemd/system/launchpad.service", config
    )
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


def restart(soft=False):
    if soft:
        reload_or_restart("launchpad")
    else:
        host.service_restart("launchpad")


def config_files():
    files = []
    files.extend(lazr_config_files())
    files.append(config_file_path("launchpad-appserver/launchpad-lazr.conf"))
    return files


@when("launchpad.base.configured")
@when_not("service.configured")
def configure():
    config = get_service_config()
    # XXX cjwatson 2022-09-07: Some config items have no reasonable default.
    # We should set the workload status to blocked in that case.
    configure_lazr(
        config,
        "launchpad-appserver-lazr.conf",
        "launchpad-appserver/launchpad-lazr.conf",
    )
    configure_gunicorn(config)
    configure_logrotate(config)

    restart_type = None
    if helpers.any_file_changed(
        [base.version_info_path(), "/lib/systemd/system/launchpad.service"]
    ):
        restart_type = "hard"
    elif helpers.any_file_changed(config_files()):
        restart_type = "soft"
    if restart_type is None:
        hookenv.log("Not restarting, since no config files were changed")
    else:
        hookenv.log(f"Config files changed; performing {restart_type} restart")
        restart(soft=(restart_type == "soft"))

    set_state("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")
