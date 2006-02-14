# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Helper class for checking the event notifications."""

__metaclass__ = type

from zope.app.tests import ztapi


class TestEventListener:
    """Listen for a specific object event.

    When an event of the specified type is fired of for an object with
    the specifed type, the given callback is called.

    At the end of the test you have to unregister the even listener
    using event_listener.unregister().
    """

    def __init__(self, object_type, event_type, callback):
        self.object_type = object_type
        self.event_type = event_type
        self.callback = callback
        self._active = True
        ztapi.subscribe((object_type, event_type), None, self)

    def __call__(self, object, event):
        if not self._active:
            return
        self.callback(object, event)

    def unregister(self):
        """Stop the event listener from listening to events."""
        # XXX: There is currently no way of unsubscribing an event
        #      handler, so we simply set self._active to False in order
        #      to make the handler return without doing anything.
        #      This won't be necessary anymore after bug 2338 has been
        #      fixed, so that it will be possible to tear down the CA.
        #      -- Bjorn Tillenius, 2006-02-14
        self._active = False

