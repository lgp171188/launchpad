# Copyright 2015-2019 Canonical Ltd.  This software is licensed under the GNU
# Affero General Public License version 3 (see the file LICENSE).

"""Snappy vocabularies."""

from __future__ import absolute_import, print_function, unicode_literals

from lp.registry.interfaces.series import SeriesStatus
from lp.snappy.interfaces.snappyseries import ISnappyDistroSeries


__metaclass__ = type

__all__ = [
    'SnapDistroArchSeriesVocabulary',
    'SnappyDistroSeriesVocabulary',
    'SnappySeriesVocabulary',
    'SnapStoreChannel',
    'SnapStoreChannelVocabulary',
    ]

from lazr.restful.interfaces import IJSONPublishable
from storm.expr import LeftJoin
from storm.locals import (
    Desc,
    Not,
    )
from zope.component import getUtility
from zope.interface import implementer
from zope.schema.vocabulary import (
    SimpleTerm,
    SimpleVocabulary,
    )
from zope.security.proxy import removeSecurityProxy

from lp.registry.model.distribution import Distribution
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.series import ACTIVE_STATUSES
from lp.services.database.interfaces import IStore
from lp.services.database.stormexpr import (
    IsDistinctFrom,
    )
from lp.services.webapp.vocabulary import StormVocabularyBase
from lp.snappy.interfaces.snap import ISnap
from lp.snappy.interfaces.snapstoreclient import ISnapStoreClient
from lp.snappy.model.snappyseries import (
    SnappyDistroSeries,
    SnappySeries,
    )
from lp.soyuz.model.distroarchseries import DistroArchSeries


class SnapDistroArchSeriesVocabulary(StormVocabularyBase):
    """All architectures of a Snap's distribution series."""

    _table = DistroArchSeries

    def toTerm(self, das):
        return SimpleTerm(das, das.id, das.architecturetag)

    def __iter__(self):
        for obj in self.context.getAllowedArchitectures():
            yield self.toTerm(obj)

    def __len__(self):
        return len(self.context.getAllowedArchitectures())


class SnappySeriesVocabulary(StormVocabularyBase):
    """A vocabulary for searching snappy series."""

    _table = SnappySeries
    _clauses = [SnappySeries.status.is_in(ACTIVE_STATUSES)]
    _order_by = Desc(SnappySeries.date_created)


@implementer(ISnappyDistroSeries)
class SyntheticSnappyDistroSeries:
    def __init__(self, snappy_series, distro_series):
        self.snappy_series = snappy_series
        self.distro_series = distro_series

    preferred = False

    @property
    def title(self):
        if self.distro_series is not None:
            if self.snappy_series.status != SeriesStatus.CURRENT:
                return "%s, for %s" % (
                    self.distro_series.fullseriesname,
                    self.snappy_series.title)
            else:
                return self.distro_series.fullseriesname
        else:
            return self.snappy_series.title


def sorting_tuple_date_created(element):

    if element.distro_series is not None:
        if element.snappy_series is not None:
            return ((1, element.distro_series.display_name),
                    (1, element.distro_series.date_created),
                    element.snappy_series.date_created)
    else:
        if element.snappy_series is not None:
            return ((0, None), (0, None), element.snappy_series.date_created)


class SnappyDistroSeriesVocabulary(StormVocabularyBase):
    """A vocabulary for searching snappy/distro series combinations."""

    _table = SnappyDistroSeries
    _origin = [
        SnappyDistroSeries,
        LeftJoin(
            DistroSeries,
            SnappyDistroSeries.distro_series_id == DistroSeries.id),
        LeftJoin(Distribution, DistroSeries.distributionID == Distribution.id),
        SnappySeries,
        ]
    _clauses = [SnappyDistroSeries.snappy_series_id == SnappySeries.id,
                SnappySeries.status.is_in(ACTIVE_STATUSES)]

    @property
    def _entries(self):
        entries = list(IStore(self._table).using(*self._origin).find(
            self._table, *self._clauses))

        if (ISnap.providedBy(self.context) and not
                any(entry.snappy_series == self.context.store_series
                    and entry.distro_series == self.context.distro_series
                    for entry in entries)):
            entries.append(SyntheticSnappyDistroSeries(
                self.context.store_series, self.context.distro_series))
        return sorted(entries, key=sorting_tuple_date_created)

    def toTerm(self, obj):
        """See `IVocabulary`."""
        if obj.distro_series is None:
            token = obj.snappy_series.name
        else:
            token = "%s/%s/%s" % (
                obj.distro_series.distribution.name, obj.distro_series.name,
                obj.snappy_series.name)
        return SimpleTerm(obj, token, obj.title)

    def __contains__(self, value):
        """See `IVocabulary`."""
        return value in self._entries

    def getTerm(self, value):
        """See `IVocabulary`."""
        if value not in self:
            raise LookupError(value)
        return self.toTerm(value)

    def getTermByToken(self, token):
        """See `IVocabularyTokenized`."""
        if "/" in token:
            try:
                distribution_name, distro_series_name, snappy_series_name = (
                    token.split("/", 2))
            except ValueError:
                raise LookupError(token)
        else:
            distribution_name = None
            distro_series_name = None
            snappy_series_name = token
        entry = IStore(self._table).using(*self._origin).find(
            self._table,
            Not(IsDistinctFrom(Distribution.name, distribution_name)),
            Not(IsDistinctFrom(DistroSeries.name, distro_series_name)),
            SnappySeries.name == snappy_series_name,
            *self._clauses).one()

        if entry is None and ISnap.providedBy(self.context):
            context_store_series_name = self.context.store_series.name
            if self.context.distro_series is not None:
                context_distribution_name = (
                    self.context.distro_series.distribution.name)
                context_distro_series_name = self.context.distro_series.name
            else:
                context_distribution_name = None
                context_distro_series_name = None
            if (context_distribution_name == distribution_name and
                    context_distro_series_name == distro_series_name and
                    context_store_series_name == snappy_series_name):
                entry = SyntheticSnappyDistroSeries(
                    self.context.store_series, self.context.distro_series)
        if entry is None:
            raise LookupError(token)

        return self.toTerm(entry)


@implementer(IJSONPublishable)
class SnapStoreChannel(SimpleTerm):
    """A store channel."""

    def toDataForJSON(self, media_type):
        """See `IJSONPublishable`."""
        return self.token


class SnapStoreChannelVocabulary(SimpleVocabulary):
    """A vocabulary for searching store channels."""

    def __init__(self, context=None):
        channels = getUtility(ISnapStoreClient).listChannels()
        terms = [
            self.createTerm(
                channel["name"], channel["name"], channel["display_name"])
            for channel in channels]
        if ISnap.providedBy(context):
            # Supplement the vocabulary with any obsolete channels still
            # used by this context.
            context_channels = removeSecurityProxy(context)._store_channels
            if context_channels is not None:
                known_names = set(channel["name"] for channel in channels)
                for name in context_channels:
                    if name not in known_names:
                        terms.append(self.createTerm(name, name, name))
        super(SnapStoreChannelVocabulary, self).__init__(terms)

    @classmethod
    def createTerm(cls, *args):
        """See `SimpleVocabulary`."""
        return SnapStoreChannel(*args)
