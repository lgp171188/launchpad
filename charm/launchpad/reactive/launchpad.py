# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import subprocess

from charmhelpers.core import hookenv
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
@when_not("service.configured")
def configure():
    hookenv.log("Hello world!")
    set_state("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")


@when("config.changed.build_label")
def build_label_changed():
    remove_state("ols.service.installed")
    remove_state("ols.configured")
    remove_state("service.configured")


@when("config.changed")
def config_changed():
    remove_state("service.configured")
