# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os.path

from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import get_service_config
from charms.launchpad.db import strip_dsn_authentication, update_pgpass
from charms.launchpad.payload import configure_lazr, home_dir
from charms.reactive import (
    clear_flag,
    endpoint_from_flag,
    is_flag_set,
    set_flag,
    when,
    when_any,
    when_not,
    when_not_all,
)
from ols import base, postgres
from psycopg2.extensions import make_dsn, parse_dsn


def any_dbname(dsn):
    parsed_dsn = parse_dsn(dsn)
    parsed_dsn["dbname"] = "*"
    return make_dsn(**parsed_dsn)


@when(
    "launchpad.db.configured",
    "db.master.available",
    "db-admin.master.available",
)
@when_not("service.configured")
def configure():
    config = get_service_config()

    db = endpoint_from_flag("db.master.available")
    db_primary, _ = postgres.get_db_uris(db)
    config["db_primary"] = strip_dsn_authentication(db_primary)

    db_admin = endpoint_from_flag("db-admin.master.available")
    db_admin_primary, _ = postgres.get_db_uris(db_admin)
    # We assume that this admin user works for any database on this host,
    # which seems to be true in practice.
    update_pgpass(any_dbname(db_admin_primary))
    config["db_admin_primary"] = strip_dsn_authentication(db_admin_primary)

    if is_flag_set("pgbouncer.master.available"):
        pgbouncer = endpoint_from_flag("pgbouncer.master.available")
        pgbouncer_primary, _ = postgres.get_db_uris(pgbouncer)
        update_pgpass(pgbouncer_primary)
        config["pgbouncer_primary"] = strip_dsn_authentication(
            pgbouncer_primary
        )
    else:
        pgbouncer = None

    configure_lazr(
        config,
        "launchpad-db-update-lazr.conf",
        "launchpad-db-update/launchpad-lazr.conf",
    )
    bin_dir = os.path.join(home_dir(), "bin")
    host.mkdir(bin_dir, owner=base.user(), group=base.user(), perms=0o755)
    scripts = {
        "db-update": True,
        "preflight": pgbouncer is not None,
    }
    for script, enable in scripts.items():
        script_path = os.path.join(bin_dir, script)
        if enable:
            templating.render(
                f"{script}.j2",
                script_path,
                config,
                owner=base.user(),
                group=base.user(),
                perms=0o755,
            )
        elif os.path.exists(script_path):
            os.unlink(script_path)

    set_flag("service.configured")
    if pgbouncer is not None:
        set_flag("service.pgbouncer.configured")
    hookenv.status_set("active", "Ready")


@when("service.configured")
@when_not_all(
    "launchpad.db.configured",
    "db.master.available",
    "db-admin.master.available",
)
def deconfigure():
    clear_flag("service.configured")


@when("service.pgbouncer.configured")
@when_not("service.configured")
def deconfigure_optional_services():
    clear_flag("service.pgbouncer.configured")


@when_any(
    "db-admin.database.changed",
    "pgbouncer.database.changed",
)
@when("service.configured")
def any_db_changed():
    clear_flag("service.configured")
    clear_flag("db-admin.database.changed")
    clear_flag("pgbouncer.database.changed")


@when("pgbouncer.master.available", "service.configured")
@when_not("service.pgbouncer.configured")
def pgbouncer_available():
    clear_flag("service.configured")


@when("service.pgbouncer.configured")
@when_not("pgbouncer.master.available")
def pgbouncer_unavailable():
    clear_flag("service.configured")
