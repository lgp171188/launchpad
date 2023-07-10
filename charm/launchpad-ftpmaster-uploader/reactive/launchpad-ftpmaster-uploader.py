# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os.path

from charmhelpers.core import hookenv, host, templating
from charms.launchpad.base import configure_email, get_service_config
from charms.launchpad.payload import configure_cron, configure_lazr
from charms.reactive import (
    clear_flag,
    endpoint_from_flag,
    remove_state,
    set_flag,
    set_state,
    when,
    when_not,
    when_not_all,
)
from ols import base


def configure_logrotate(config):
    hookenv.log("Writing logrotate configuration.")
    templating.render(
        "logrotate.conf.j2",
        "/etc/logrotate.d/launchpad",
        config,
        perms=0o644,
    )


@when(
    "launchpad.db.configured",
)
@when_not("service.configured")
def configure():
    hookenv.log("Configuring ftpmaster uploader")
    config = get_service_config()
    config["ubuntu_queue_dir"] = os.path.join(base.base_dir(), "ubuntu-queue")
    host.mkdir(config["ubuntu_queue_dir"], perms=0o755)

    configure_lazr(
        config,
        "launchpad-ftpmaster-uploader-lazr.conf.j2",
        "launchpad-ftpmaster-uploader/launchpad-lazr.conf",
    )
    configure_email(config, "launchpad-ftpmaster-uploader")
    configure_logrotate(config)
    configure_cron(config, "crontab.j2")
    set_state("service.configured")


@when("service.configured", "upload-queue-processor.available")
@when_not("service.txpkgupload-configured")
def configure_txpkgupload():
    fsroot = os.path.join(base.base_dir(), "incoming")
    txpkgupload = endpoint_from_flag("upload-queue-processor.available")
    txpkgupload.set_config(
        fsroot=fsroot,
    )
    set_flag("service.txpkgupload-configured")


@when("service.txpkgupload-configured")
@when_not_all("service.configured", "upload-queue-processor.available")
def txpkgupload_deconfigured():
    hookenv.status_set("blocked", "Txpkgupload not yet configured")
    clear_flag("service.txpkgupload-configured")


@when("service.configured", "service.txpkgupload-configured")
def check_is_running():
    hookenv.status_set("active", "Ready")


@when("service.configured")
@when_not("launchpad.db.configured")
def deconfigure():
    remove_state("service.configured")
