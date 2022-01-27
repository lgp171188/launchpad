#!/usr/bin/python3 -S
#
# Copyright 2010-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Request builds for stale daily build recipes and snap packages."""

import _pythonpath  # noqa: F401

import transaction
from zope.component import getUtility

from lp.charms.interfaces.charmrecipe import ICharmRecipeSet
from lp.code.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuildSource,
    )
from lp.services.config import config
from lp.services.scripts.base import LaunchpadCronScript
from lp.services.timeout import set_default_timeout_function
from lp.services.webapp.errorlog import globalErrorUtility
from lp.snappy.interfaces.snap import ISnapSet


class RequestDailyBuilds(LaunchpadCronScript):
    """Run create merge proposal jobs."""

    def __init__(self):
        name = 'request_daily_builds'
        dbuser = config.request_daily_builds.dbuser
        LaunchpadCronScript.__init__(self, name, dbuser)

    def main(self):
        globalErrorUtility.configure(self.name)
        set_default_timeout_function(
            lambda: config.request_daily_builds.timeout)
        source = getUtility(ISourcePackageRecipeBuildSource)
        builds = source.makeDailyBuilds(self.logger)
        self.logger.info('Requested %d daily recipe builds.' % len(builds))
        build_requests = getUtility(ISnapSet).makeAutoBuilds(self.logger)
        self.logger.info(
            'Requested %d sets of automatic snap package builds.' %
            len(build_requests))
        build_requests = getUtility(ICharmRecipeSet).makeAutoBuilds(
            self.logger)
        self.logger.info(
            'Requested %d sets of automatic charm recipe builds.' %
            len(build_requests))
        transaction.commit()


if __name__ == '__main__':
    script = RequestDailyBuilds()
    script.lock_and_run()
