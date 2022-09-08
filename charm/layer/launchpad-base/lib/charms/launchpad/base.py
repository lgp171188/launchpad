# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os.path

from charmhelpers.core import hookenv, host, templating
from ols import base


def home_dir():
    return os.path.join("/home", base.user())


def oopses_dir():
    return os.path.join(base.base_dir(), "oopses")


def secrets_dir():
    return os.path.join(base.base_dir(), "secrets")


def var_dir():
    return os.path.join(base.base_dir(), "var")


def ensure_lp_directories():
    for dirpath in oopses_dir(), var_dir():
        host.mkdir(dirpath, group=base.user(), perms=0o775)
    host.mkdir(secrets_dir(), group=base.user(), perms=0o750)
    host.mkdir(home_dir(), owner=base.user(), group=base.user(), perms=0o755)


def get_service_config():
    config = dict(hookenv.config())
    config.update(
        {
            "base_dir": base.base_dir(),
            "code_dir": base.code_dir(),
            "logs_dir": base.logs_dir(),
            "oopses_dir": oopses_dir(),
            "secrets_dir": secrets_dir(),
            "user": base.user(),
            "var_dir": var_dir(),
        }
    )
    return config


def config_file_path(name, secret=False):
    if secret:
        config_dir = os.path.join(base.base_dir(), "secrets")
    else:
        config_dir = os.path.join(base.code_dir(), "production-configs")
    return os.path.join(config_dir, name)


def configure_lazr(config, template, name, secret=False):
    hookenv.log("Writing service configuration.")
    templating.render(
        template,
        config_file_path(name, secret=secret),
        config,
        owner="root",
        group=base.user(),
        perms=0o440 if secret else 0o444,
    )


def lazr_config_files():
    return [
        config_file_path("launchpad-base-lazr.conf"),
        config_file_path("launchpad-base-secrets-lazr.conf", secret=True),
    ]


def configure_rsync(config, template, name):
    hookenv.log("Writing rsync configuration.")
    rsync_path = os.path.join("/etc/rsync-juju.d", name)
    if config["log_hosts_allow"]:
        templating.render(template, rsync_path, config, perms=0o644)
    elif os.path.exists(rsync_path):
        os.unlink(rsync_path)
