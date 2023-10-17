#! /usr/bin/python3
# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import subprocess
import sys
import traceback
from pathlib import Path

sys.path.append("lib")

from charms.layer import basic  # noqa: E402

basic.bootstrap_charm_deps()
basic.init_config_states()

from charmhelpers.core import hookenv  # noqa: E402
from charms.launchpad.payload import home_dir  # noqa: E402
from ols import base  # noqa: E402


def preflight():
    hookenv.log("Running preflight checks.")
    script = Path(home_dir(), "bin", "preflight")
    if script.exists():
        subprocess.run(
            ["sudo", "-H", "-u", base.user(), script],
            check=True,
        )
        hookenv.action_set({"result": "Preflight checks passed"})
    else:
        message = "Preflight checks not available; missing pgbouncer relation?"
        hookenv.log(message)
        hookenv.action_fail(message)


def db_update():
    hookenv.log("Running database schema update.")
    script = Path(home_dir(), "bin", "db-update")
    subprocess.run(["sudo", "-H", "-u", base.user(), script], check=True)
    hookenv.action_set({"result": "Database schema update completed"})


def main(argv):
    action = Path(argv[0]).name
    try:
        if action == "preflight":
            preflight()
        elif action == "db-update":
            db_update()
        else:
            hookenv.action_fail(f"Action {action} not implemented.")
    except Exception:
        hookenv.action_fail("Unhandled exception")
        tb = traceback.format_exc()
        hookenv.action_set(dict(traceback=tb))
        hookenv.log(f"Unhandled exception in action {action}:")
        for line in tb.splitlines():
            hookenv.log(line)


if __name__ == "__main__":
    main(sys.argv)
