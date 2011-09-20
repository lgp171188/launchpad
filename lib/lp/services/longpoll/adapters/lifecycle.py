# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Long-poll life-cycle adapters."""

__metaclass__ = type
__all__ = []

from lazr.lifecycle.interfaces import (
    IObjectCreatedEvent,
    IObjectDeletedEvent,
    IObjectModifiedEvent,
    )
from storm.base import Storm
from storm.info import get_obj_info
from zope.component import adapter
from zope.interface import implements

from lp.services.longpoll.adapters.event import (
    generate_event_key,
    LongPollEvent,
    )
from lp.services.longpoll.interfaces import ILongPollEvent


class LongPollStormLifecycleEvent(LongPollEvent):
    """A `ILongPollEvent` for life-cycle events of `Storm` objects.

    In fact, there is little specialization towards life-cycle here; this
    class merely knows how to construct a stable event key given a Storm
    object.
    """

    implements(ILongPollEvent)

    @property
    def event_key(self):
        """See `ILongPollEvent`.

        Constructs the key from the table name and primary key values of the
        Storm model object.
        """
        cls_info = get_obj_info(self.source).cls_info
        key_parts = [cls_info.table.name.lower()]
        key_parts.extend(
            primary_key_column.__get__(self.source)
            for primary_key_column in cls_info.primary_key)
        key_parts.append(self.event)
        return generate_event_key(*key_parts)


@adapter(Storm, IObjectCreatedEvent)
def storm_object_created(model_instance, object_event):
    """Subscription handler for `Storm` creation events."""
    event = LongPollStormLifecycleEvent(model_instance, "created")
    event.emit({})


@adapter(Storm, IObjectDeletedEvent)
def storm_object_deleted(model_instance, object_event):
    """Subscription handler for `Storm` deletion events."""
    event = LongPollStormLifecycleEvent(model_instance, "deleted")
    event.emit({})


@adapter(Storm, IObjectModifiedEvent)
def storm_object_modified(model_instance, object_event):
    """Subscription handler for `Storm` modification events."""
    event = LongPollStormLifecycleEvent(model_instance, "modified")
    event.emit({"edited_fields": sorted(object_event.edited_fields)})
