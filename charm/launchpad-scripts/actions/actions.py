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
from ols import base  # noqa: E402

services = (
    "celerybeat_launchpad.service",
    "celeryd_launchpad_job.service",
    "celeryd_launchpad_job_slow.service",
    "number-cruncher.service",
)


def bugsummary_rebuild():
    hookenv.log("Rebuilding CombinedBugSummary table.")
    script = Path(base.code_dir(), "scripts", "bugsummary-rebuild.py")
    subprocess.run(
        [
            "sudo",
            "-H",
            "-u",
            base.user(),
            "LPCONFIG=launchpad-scripts",
            script,
        ],
        check=True,
    )
    hookenv.action_set({"result": "Rebuild complete"})


def start_services():
    for service in services:
        hookenv.log(f"Starting {service}.")
        subprocess.run(["systemctl", "start", service], check=True)
    hookenv.action_set({"result": "Services started"})


def stop_services():
    for service in services:
        hookenv.log(f"Stopping {service}.")
        subprocess.run(["systemctl", "stop", service], check=True)
    hookenv.action_set({"result": "Services stopped"})


def main(argv):
    action = Path(argv[0]).name
    try:
        if action == "bugsummary-rebuild":
            bugsummary_rebuild()
        elif action == "start-services":
            start_services()
        elif action == "stop-services":
            stop_services()
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
