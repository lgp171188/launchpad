# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from charmhelpers.core import hookenv
from charms.reactive import set_state, when, when_not


@when("ols.configured")
@when_not("service.configured")
def configure():
    hookenv.log("Hello world!")
    set_state("service.configured")


@when("service.configured")
def check_is_running():
    hookenv.status_set("active", "Ready")
