# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import grp
import os.path
import pwd
import re
from dataclasses import dataclass
from email.utils import parseaddr

from charmhelpers.core import hookenv, host, templating
from ols import base
from psycopg2.extensions import make_dsn, parse_dsn


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
            # Used by some templates.
            "parseaddr": parseaddr,
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


@dataclass
class PgPassLine:
    hostname: str
    port: str
    database: str
    username: str
    password: str


def update_pgpass(dsn):
    # See https://www.postgresql.org/docs/current/libpq-pgpass.html.

    def unescape(entry):
        return re.sub(r"\\(.)", r"\1", entry)

    def escape(entry):
        return re.sub(r"([:\\])", r"\\\1", entry)

    parsed_dsn = parse_dsn(dsn)
    pgpass_path = os.path.join(home_dir(), ".pgpass")
    pgpass = []
    try:
        with open(pgpass_path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                match = re.match(
                    r"""
                        ^
                        (?P<hostname>(?:[^:\\]|\\.)*):
                        (?P<port>(?:[^:\\]|\\.)*):
                        (?P<database>(?:[^:\\]|\\.)*):
                        (?P<username>(?:[^:\\]|\\.)*):
                        (?P<password>(?:[^:\\]|\\.)*)
                        $
                    """,
                    line.rstrip("\n"),
                    flags=re.X,
                )
                if match is None:
                    continue
                pgpass.append(
                    PgPassLine(
                        hostname=unescape(match.group("hostname")),
                        port=unescape(match.group("port")),
                        database=unescape(match.group("database")),
                        username=unescape(match.group("username")),
                        password=unescape(match.group("password")),
                    )
                )
    except OSError:
        pass

    modified = False
    for line in pgpass:
        if (
            line.hostname in ("*", parsed_dsn["host"])
            and line.port in ("*", parsed_dsn["port"])
            and line.database in ("*", parsed_dsn["dbname"])
            and line.username in ("*", parsed_dsn["user"])
        ):
            if line.password != parsed_dsn["password"]:
                line.password = parsed_dsn["password"]
                modified = True
            break
    else:
        pgpass.append(
            PgPassLine(
                hostname=parsed_dsn["host"],
                port=parsed_dsn["port"],
                database=parsed_dsn["dbname"],
                username=parsed_dsn["user"],
                password=parsed_dsn["password"],
            )
        )
        modified = True

    if modified:
        uid = pwd.getpwnam(base.user()).pw_uid
        gid = grp.getgrnam(base.user()).gr_gid
        with open(pgpass_path, "w") as f:
            for line in pgpass:
                print(
                    ":".join(
                        [
                            escape(line.hostname),
                            escape(line.port),
                            escape(line.database),
                            escape(line.username),
                            escape(line.password),
                        ]
                    ),
                    file=f,
                )
            os.fchown(f.fileno(), uid, gid)
            os.fchmod(f.fileno(), 0o600)


def strip_dsn_authentication(dsn):
    parsed_dsn = parse_dsn(dsn)
    parsed_dsn.pop("user", None)
    parsed_dsn.pop("password", None)
    return make_dsn(**parsed_dsn)
