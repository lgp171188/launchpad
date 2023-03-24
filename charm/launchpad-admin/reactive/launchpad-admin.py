# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os.path

from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import (
    configure_lazr,
    get_service_config,
    home_dir,
    strip_dsn_authentication,
    update_pgpass,
)
from charms.reactive import endpoint_from_flag, set_state, when, when_not
from ols import base, postgres
from psycopg2.extensions import make_dsn, parse_dsn


def any_dbname(dsn):
    parsed_dsn = parse_dsn(dsn)
    parsed_dsn["dbname"] = "*"
    return make_dsn(**parsed_dsn)


def strip_password(dsn):
    parsed_dsn = parse_dsn(dsn)
    parsed_dsn.pop("password", None)
    return make_dsn(**parsed_dsn)


@when(
    "launchpad.base.configured",
    "db.master.available",
    "db-admin.master.available",
    "session-db.master.available",
)
@when_not("service_configured")
def configure():
    db = endpoint_from_flag("db.master.available")
    db_admin = endpoint_from_flag("db-admin.master.available")
    session_db = endpoint_from_flag("session-db.master.available")
    config = get_service_config()
    db_primary, _ = postgres.get_db_uris(db)
    db_admin_primary, db_admin_standby = postgres.get_db_uris(db_admin)
    session_db_primary, _ = postgres.get_db_uris(session_db)
    # We assume that this admin user works for any database on this host,
    # which seems to be true in practice.
    for dsn in [db_admin_primary] + db_admin_standby:
        update_pgpass(any_dbname(dsn))
    update_pgpass(session_db_primary)
    config["db_primary"] = strip_password(db_primary)
    config["db_admin_primary"] = strip_password(db_admin_primary)
    config["db_admin_standby"] = ",".join(
        strip_password(dsn) for dsn in db_admin_standby
    )
    config["db_session_primary"] = strip_password(session_db_primary)
    config["db_session"] = strip_dsn_authentication(session_db_primary)
    config["db_session_user"] = parse_dsn(session_db_primary)["user"]
    configure_lazr(
        config,
        "launchpad-admin-lazr.conf",
        "launchpad-admin/launchpad-lazr.conf",
    )
    templating.render(
        "bash_aliases.j2",
        os.path.join(home_dir(), ".bash_aliases"),
        config,
        owner=base.user(),
        group=base.user(),
        perms=0o644,
    )
    bin_dir = os.path.join(home_dir(), "bin")
    host.mkdir(bin_dir, owner=base.user(), group=base.user(), perms=0o755)
    for script in ("db", "db-admin", "db-session"):
        script_path = os.path.join(bin_dir, script)
        templating.render(
            f"{script}.j2",
            script_path,
            config,
            owner=base.user(),
            group=base.user(),
            perms=0o755,
        )

    set_state("service.configured")
    hookenv.status_set("active", "Ready")
