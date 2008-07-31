# Copyright 2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'DistributionSourcePackageReleaseNavigation',
    'DistributionSourcePackageReleaseShortLink',
    ]

from zope.component import getUtility

from canonical.launchpad.browser.launchpad import (
    DefaultShortLink)

from canonical.launchpad.interfaces import (
    IBuildSet, IDistributionSourcePackageRelease,
    IStructuralHeaderPresentation, NotFoundError)


from canonical.launchpad.webapp import (
    ApplicationMenu, Navigation, stepthrough)


class DistributionSourcePackageReleaseOverviewMenu(ApplicationMenu):

    usedfor = IDistributionSourcePackageRelease
    facet = 'overview'
    links = []


class DistributionSourcePackageReleaseNavigation(Navigation):
    usedfor = IDistributionSourcePackageRelease

    @stepthrough('+build')
    def traverse_build(self, name):
        try:
            build_id = int(name)
        except ValueError:
            return None
        try:
            return getUtility(IBuildSet).getByBuildID(build_id)
        except NotFoundError:
            return None


class DistributionSourcePackageReleaseShortLink(DefaultShortLink):

    def getLinkText(self):
        return self.context.sourcepackagerelease.version

