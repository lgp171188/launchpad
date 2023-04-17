# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os.path
import subprocess

from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import (
    configure_lazr,
    get_service_config,
    home_dir,
    strip_dsn_authentication,
    update_pgpass,
)
from charms.reactive import (
    endpoint_from_flag,
    remove_state,
    set_state,
    when,
    when_not,
    when_not_all,
)
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


def database_is_initialized() -> bool:
    """Has the database been initialized?

    The launchpad-admin charm is itself used to initialize the database, so
    we can't assume that that's been done yet at the time our `configure`
    handler runs.  The `LaunchpadDatabaseRevision` table is used to track
    schema migrations, so its presence is a good indicator of whether we
    have a useful database.
    """
    return (
        subprocess.run(
            [
                "sudo",
                "-H",
                "-u",
                base.user(),
                os.path.join(home_dir(), "bin", "db"),
                "-c",
                r"\d LaunchpadDatabaseRevision",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def update_database_permissions():
    subprocess.run(
        [
            "sudo",
            "-H",
            "-u",
            base.user(),
            "LPCONFIG=launchpad-admin",
            os.path.join(base.code_dir(), "database", "schema", "security.py"),
            "--no-revoke",
        ],
        check=True,
    )


@when(
    "launchpad.base.configured",
    "db.master.available",
    "db-admin.master.available",
    "session-db.master.available",
)
@when_not("service.configured")
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

    if database_is_initialized():
        hookenv.log("Updating database permissions.")
        update_database_permissions()
    else:
        hookenv.log("Database has not been initialized yet.")

    set_state("service.configured")
    hookenv.status_set("active", "Ready")


@when("service.configured")
@when_not_all("db-admin.master.available", "session-db.master.available")
def deconfigure():
    remove_state("service.configured")


@when("db-admin.database.changed", "service.configured")
def db_admin_changed():
    remove_state("service.configured")
    remove_state("db-admin.database.changed")


@when("session-db.database.changed", "service.configured")
def session_db_changed():
    remove_state("service.configured")
    remove_state("session-db.database.changed")
