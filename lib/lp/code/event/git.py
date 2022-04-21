# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Events related to Git repositories."""

__all__ = [
    'GitRefsCreatedEvent',
    'GitRefsUpdatedEvent',
    ]

from zope.interface import implementer
from zope.interface.interfaces import ObjectEvent

from lp.code.interfaces.event import (
    IGitRefsCreatedEvent,
    IGitRefsUpdatedEvent,
    )


@implementer(IGitRefsCreatedEvent)
class GitRefsCreatedEvent(ObjectEvent):
    """See `IGitRefsCreatedEvent`."""

    def __init__(self, repository, paths, logger):
        super().__init__(repository)
        self.paths = paths
        self.logger = logger


@implementer(IGitRefsUpdatedEvent)
class GitRefsUpdatedEvent(ObjectEvent):
    """See `IGitRefsUpdatedEvent`."""

    def __init__(self, repository, paths, logger):
        super().__init__(repository)
        self.paths = paths
        self.logger = logger
