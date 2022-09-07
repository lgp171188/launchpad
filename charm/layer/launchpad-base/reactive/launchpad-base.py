# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import subprocess

from charms.launchpad.base import (
    configure_lazr,
    configure_rsync,
    ensure_lp_directories,
    get_service_config,
)
from charms.reactive import remove_state, set_state, when, when_not
from ols import base


# Monkey-patch layer:ols.
def create_virtualenv(wheels_dir, codedir, python_exe):
    subprocess.run(
        ["make", "compile", "PYTHON={}".format(python_exe)],
        cwd=codedir,
        check=True,
    )


base.create_virtualenv = create_virtualenv


@when("ols.configured")
@when_not("launchpad.base.configured")
def configure():
    ensure_lp_directories()
    config = get_service_config()
    # XXX cjwatson 2022-09-07: Some config items have no reasonable default.
    # We should set the workload status to blocked in that case.
    configure_lazr(
        config,
        "launchpad-base-lazr.conf",
        "launchpad-base-lazr.conf",
    )
    configure_lazr(
        config,
        "launchpad-base-secrets-lazr.conf",
        "launchpad-base-secrets-lazr.conf",
        secret=True,
    )
    configure_rsync(
        config, "launchpad-base-rsync.conf", "010-launchpad-base.conf"
    )
    set_state("launchpad.base.configured")


@when("config.changed.build_label")
def build_label_changed():
    remove_state("ols.service.installed")
    remove_state("ols.configured")
    remove_state("launchpad.base.configured")
    remove_state("service.configured")


@when("config.changed")
def config_changed():
    remove_state("launchpad.base.configured")
    remove_state("service.configured")
