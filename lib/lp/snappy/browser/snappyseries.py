# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""SnappySeries views."""

__all__ = [
    "SnappySeriesSetNavigation",
]

from lp.services.webapp import GetitemNavigation
from lp.snappy.interfaces.snappyseries import ISnappySeriesSet


class SnappySeriesSetNavigation(GetitemNavigation):
    """Navigation methods for `ISnappySeriesSet`."""

    usedfor = ISnappySeriesSet
