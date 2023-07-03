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


def start_services():
    service = "launchpad-buildd-manager.service"
    hookenv.log(f"Starting {service}.")
    subprocess.run(["systemctl", "start", service], check=True)
    hookenv.action_set({"result": "Services started"})


def stop_services():
    service = "launchpad-buildd-manager.service"
    hookenv.log(f"Stopping {service}.")
    subprocess.run(["systemctl", "stop", service], check=True)
    hookenv.action_set({"result": "Services stopped"})


def main(argv):
    action = Path(argv[0]).name
    try:
        if action == "start-services":
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
