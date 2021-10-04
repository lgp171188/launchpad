# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the snappy vocabularies."""

from lp.registry.interfaces.series import SeriesStatus
from lp.snappy.vocabularies import SnappyDistroSeriesVocabulary
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestSnappyDistroSeriesVocabulary(TestCaseWithFactory):
    """Test that the SnappyDistroSeriesVocabulary behaves as expected."""

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(TestSnappyDistroSeriesVocabulary, self).setUp()
        self.vocab = SnappyDistroSeriesVocabulary()

    def test_getTermByToken(self):
        distro_series = self.factory.makeDistroSeries()
        snappy_series = self.factory.makeSnappySeries(
            usable_distro_series=[distro_series])

        term = self.vocab.getTermByToken("%s/%s/%s" % (
            distro_series.distribution.name,
            distro_series.name,
            snappy_series.name
        ))
        self.assertIsNotNone(term)

    def test_term_structure_for_current_store_series(self):
        distro_series = self.factory.makeUbuntuDistroSeries()
        snappy_series = self.factory.makeSnappySeries(
            usable_distro_series=[distro_series],
            status=SeriesStatus.CURRENT
        )

        term = self.vocab.getTermByToken("%s/%s/%s" % (
            distro_series.distribution.name,
            distro_series.name,
            snappy_series.name
        ))

        self.assertEqual(term.title, distro_series.fullseriesname)

    def test_term_structure_for_older_store_series(self):
        distro_series = self.factory.makeUbuntuDistroSeries()
        snappy_series = self.factory.makeSnappySeries(
            usable_distro_series=[distro_series],
            status=SeriesStatus.SUPPORTED)

        term = self.vocab.getTermByToken("%s/%s/%s" % (
            distro_series.distribution.name,
            distro_series.name,
            snappy_series.name
        ))

        self.assertEqual(term.title, "%s, for %s" % (
            distro_series.fullseriesname,
            snappy_series.title))

    def test_term_structure_for_distro_series_None(self):
        snappy_series = self.factory.makeSnappySeries(
            can_infer_distro_series=True)
        term = self.vocab.getTermByToken(snappy_series.name)
        self.assertEqual(term.title, snappy_series.title)

    def test_term_structure_for_infer_from_snapcraft(self):
        snappy_series = self.factory.makeSnappySeries(
            can_infer_distro_series=True,
            status=SeriesStatus.CURRENT)
        term = self.vocab.getTermByToken(snappy_series.name)

        self.assertEqual(term.title, "Infer from snapcraft.yaml (recommended)")
        self.assertEqual(term.token, snappy_series.name)

    def test_term_order_for_distro_series_None(self):
        # entry with DistroSeries=None should be at the top of
        # the entries list in the vocabulary
        # in this instance it will also be the most recent one
        # which should also be a the top

        snappy_series = self.factory.makeSnappySeries(
            can_infer_distro_series=True)
        entries = self.vocab._entries

        self.assertIsNone(entries[0].distro_series)
        self.assertEqual(entries[0].title, snappy_series.title)
