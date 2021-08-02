# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Health check view for Talisker."""

__metaclass__ = type
__all__ = [
    "StatusCheckView",
    ]

from zope.publisher.interfaces import NotFound


class StatusView:

    def __init__(self, context, request):
        self.context = context

    def browserDefault(self, request):
        return self, ()

    def publishTraverse(self, request, name):
        if name == "check":
            return StatusCheckView(self.context, request)
        else:
            raise NotFound(self.context, name)

    def __call__(self):
        raise NotFound(self.context, self.__name__)


class StatusCheckView:
    """/_status/check view for use by Talisker.

    This currently just checks that we have a working database connection.
    """

    def __init__(self, context, request):
        pass

    def __call__(self):
        return b""
