# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Metrics for Launchpad scripts."""

__all__ = [
    "emit_script_activity_metric",
    ]

from datetime import timedelta

from zope.component import getUtility

from lp.services.statsd.interfaces.statsd_client import IStatsdClient


def emit_script_activity_metric(name: str, duration: timedelta):
    """Inform statsd about a script completing."""
    # Don't bother with labels for hostname information, since telegraf adds
    # that sort of thing.
    getUtility(IStatsdClient).timing(
        "script_activity",
        duration.total_seconds() * 1000,
        labels={"name": name})
