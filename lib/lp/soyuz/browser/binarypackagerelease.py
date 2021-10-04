# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    'BinaryPackageReleaseNavigation',
    'BinaryPackageView',
    ]

from lp.services.webapp import Navigation
from lp.services.webapp.publisher import (
    canonical_url,
    LaunchpadView,
    )
from lp.soyuz.browser.packagerelationship import (
    PackageRelationshipSet,
    relationship_builder,
    )
from lp.soyuz.interfaces.binarypackagerelease import IBinaryPackageRelease


class BinaryPackageReleaseNavigation(Navigation):
    usedfor = IBinaryPackageRelease


class BinaryPackageView(LaunchpadView):
    """View class for BinaryPackage"""

    def _relationship_parser(self, content):
        """Wrap the relationship_builder for BinaryPackages.

        Define IDistroArchSeries.getBinaryPackage as a relationship 'getter'.
        """
        getter = self.context.build.distro_arch_series.getBinaryPackage
        return relationship_builder(content, getter=getter)

    def depends(self):
        return self._relationship_parser(self.context.depends)

    def recommends(self):
        return self._relationship_parser(self.context.recommends)

    def conflicts(self):
        return self._relationship_parser(self.context.conflicts)

    def replaces(self):
        return self._relationship_parser(self.context.replaces)

    def suggests(self):
        return self._relationship_parser(self.context.suggests)

    def provides(self):
        return self._relationship_parser(self.context.provides)

    def pre_depends(self):
        return self._relationship_parser(self.context.pre_depends)

    def enhances(self):
        return self._relationship_parser(self.context.enhances)

    def breaks(self):
        return self._relationship_parser(self.context.breaks)

    def built_using(self):
        relationship_set = PackageRelationshipSet()
        for reference in self.context.built_using_references:
            spr = reference.source_package_release
            sp = spr.upload_distroseries.getSourcePackage(
                spr.sourcepackagename)
            sp_url = canonical_url(sp) if sp is not None else None
            relationship_set.add(spr.name, '=', spr.version, sp_url)
        return relationship_set
