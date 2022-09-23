# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import subprocess

from charms.launchpad.base import (
    configure_lazr,
    configure_rsync,
    ensure_lp_directories,
    get_service_config,
    strip_dsn_authentication,
    update_pgpass,
)
from charms.reactive import hook, remove_state, set_state, when, when_not
from ols import base, postgres
from psycopg2.extensions import parse_dsn


# Monkey-patch layer:ols.
def create_virtualenv(wheels_dir, codedir, python_exe):
    subprocess.run(
        ["make", "compile", "PYTHON={}".format(python_exe)],
        cwd=codedir,
        check=True,
    )


base.create_virtualenv = create_virtualenv


@when("ols.configured", "db.master.available")
@when_not("launchpad.base.configured")
def configure(db):
    ensure_lp_directories()
    config = get_service_config()
    db_primary, db_standby = postgres.get_db_uris(db)
    # XXX cjwatson 2022-09-23: Mangle the connection strings into forms
    # Launchpad understands.  In the long term it would be better to have
    # Launchpad be able to consume unmodified connection strings.
    for dsn in [db_primary] + db_standby:
        update_pgpass(dsn)
    config["db_primary"] = strip_dsn_authentication(db_primary)
    config["db_standby"] = ",".join(
        strip_dsn_authentication(dsn) for dsn in db_standby
    )
    # XXX cjwatson 2022-09-23: This is a layering violation, since it's
    # specific to the appserver.  We need to teach Launchpad to be able to
    # log in as one role and then switch to another.
    config["db_user"] = parse_dsn(db_primary)["user"]
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


@hook("upgrade-charm")
def upgrade_charm():
    # The ols layer takes care of removing the ols.service.installed,
    # ols.configured, and service.configured states.  Remove
    # launchpad.base.configured as well so that we have an opportunity to
    # rewrite base configuration files.
    remove_state("launchpad.base.configured")


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
