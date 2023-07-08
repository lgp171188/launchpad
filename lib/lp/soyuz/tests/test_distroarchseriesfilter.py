# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test distro arch series filters."""

from testtools.matchers import MatchesStructure
from zope.component import getUtility
from zope.security.interfaces import Unauthorized

from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.soyuz.enums import DistroArchSeriesFilterSense
from lp.soyuz.interfaces.distroarchseriesfilter import (
    IDistroArchSeriesFilter,
    IDistroArchSeriesFilterSet,
)
from lp.testing import TestCaseWithFactory, admin_logged_in, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer, ZopelessDatabaseLayer


class TestDistroArchSeriesFilter(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_implements_interfaces(self):
        # DistroArchSeriesFilter implements IDistroArchSeriesFilter.
        dasf = self.factory.makeDistroArchSeriesFilter()
        with admin_logged_in():
            self.assertProvides(dasf, IDistroArchSeriesFilter)

    def test___repr__(self):
        # `DistroArchSeriesFilter` objects have an informative __repr__.
        das = self.factory.makeDistroArchSeries()
        dasf = self.factory.makeDistroArchSeriesFilter(distroarchseries=das)
        self.assertEqual(
            "<DistroArchSeriesFilter for %s>" % das.title, repr(dasf)
        )

    def test_isSourceIncluded_include(self):
        # INCLUDE filters report that a source is included if it is in the
        # packageset.
        spns = [self.factory.makeSourcePackageName() for _ in range(3)]
        dasf = self.factory.makeDistroArchSeriesFilter(
            sense=DistroArchSeriesFilterSense.INCLUDE
        )
        with admin_logged_in():
            dasf.packageset.add(spns[:2])
        self.assertTrue(dasf.isSourceIncluded(spns[0]))
        self.assertTrue(dasf.isSourceIncluded(spns[1]))
        self.assertFalse(dasf.isSourceIncluded(spns[2]))

    def test_isSourceIncluded_exclude(self):
        # EXCLUDE filters report that a source is included if it is not in
        # the packageset.
        spns = [self.factory.makeSourcePackageName() for _ in range(3)]
        dasf = self.factory.makeDistroArchSeriesFilter(
            sense=DistroArchSeriesFilterSense.EXCLUDE
        )
        with admin_logged_in():
            dasf.packageset.add(spns[:2])
        self.assertFalse(dasf.isSourceIncluded(spns[0]))
        self.assertFalse(dasf.isSourceIncluded(spns[1]))
        self.assertTrue(dasf.isSourceIncluded(spns[2]))

    def test_destroySelf_unauthorized(self):
        # Ordinary users cannot delete a filter.
        das = self.factory.makeDistroArchSeries()
        self.factory.makeDistroArchSeriesFilter(distroarchseries=das)
        dasf = das.getSourceFilter()
        with person_logged_in(self.factory.makePerson()):
            self.assertRaises(Unauthorized, getattr, dasf, "destroySelf")

    def test_destroySelf(self):
        # Owners of the DAS's archive can delete a filter.
        das = self.factory.makeDistroArchSeries()
        self.factory.makeDistroArchSeriesFilter(distroarchseries=das)
        dasf = das.getSourceFilter()
        with person_logged_in(das.main_archive.owner):
            dasf.destroySelf()
        self.assertIsNone(das.getSourceFilter())


class TestDistroArchSeriesFilterSet(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def test_class_implements_interface(self):
        # The DistroArchSeriesFilterSet class implements
        # IDistroArchSeriesFilterSet.
        self.assertProvides(
            getUtility(IDistroArchSeriesFilterSet), IDistroArchSeriesFilterSet
        )

    def test_new(self):
        # The arguments passed when creating a filter are present on the new
        # object.
        das = self.factory.makeDistroArchSeries()
        packageset = self.factory.makePackageset(distroseries=das.distroseries)
        sense = DistroArchSeriesFilterSense.EXCLUDE
        creator = self.factory.makePerson()
        dasf = getUtility(IDistroArchSeriesFilterSet).new(
            distroarchseries=das,
            packageset=packageset,
            sense=sense,
            creator=creator,
        )
        now = get_transaction_timestamp(IStore(dasf))
        self.assertThat(
            dasf,
            MatchesStructure.byEquality(
                distroarchseries=das,
                packageset=packageset,
                sense=sense,
                creator=creator,
                date_created=now,
                date_last_modified=now,
            ),
        )

    def test_getByDistroArchSeries(self):
        # getByDistroArchSeries returns the filter for a DAS, if any.
        das = self.factory.makeDistroArchSeries()
        dasf_set = getUtility(IDistroArchSeriesFilterSet)
        self.assertIsNone(dasf_set.getByDistroArchSeries(das))
        dasf = self.factory.makeDistroArchSeriesFilter(distroarchseries=das)
        self.assertEqual(dasf, dasf_set.getByDistroArchSeries(das))

    def test_findByPackageset(self):
        # findByPackageset returns any filters using a package set.
        packageset = self.factory.makePackageset()
        dasf_set = getUtility(IDistroArchSeriesFilterSet)
        self.assertContentEqual([], dasf_set.findByPackageset(packageset))
        dasfs = [
            self.factory.makeDistroArchSeriesFilter(packageset=packageset)
            for _ in range(2)
        ]
        self.assertContentEqual(dasfs, dasf_set.findByPackageset(packageset))
