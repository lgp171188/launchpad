# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "compose_webhook_payload",
    "WebhookAbsoluteURL",
    "WebhookPayloadRequest",
]

from io import BytesIO

from lazr.restful.interfaces import IFieldMarshaller
from zope.component import getMultiAdapter
from zope.interface import implementer
from zope.traversing.browser.interfaces import IAbsoluteURL

from lp.services.webapp.interfaces import ILaunchpadBrowserApplicationRequest
from lp.services.webapp.publisher import canonical_url
from lp.services.webapp.servers import LaunchpadBrowserRequest


class IWebhookPayloadRequest(ILaunchpadBrowserApplicationRequest):
    """An internal fake request used while composing webhook payloads."""


@implementer(IWebhookPayloadRequest)
class WebhookPayloadRequest(LaunchpadBrowserRequest):
    """An internal fake request used while composing webhook payloads."""

    def __init__(self):
        super().__init__(BytesIO(), {})


@implementer(IAbsoluteURL)
class WebhookAbsoluteURL:
    """A variant of CanonicalAbsoluteURL that always forces a local path."""

    def __init__(self, context, request):
        """Initialize with respect to a context and request."""
        self.context = context
        self.request = request

    def __str__(self):
        """Returns an ASCII string with all unicode characters url quoted."""
        return canonical_url(self.context, force_local_path=True)

    def __repr__(self):
        """Get a string representation"""
        raise NotImplementedError()

    __call__ = __str__


def compose_webhook_payload(interface, obj, keys, preferred_names=None):
    """Compose a webhook payload dictionary from some fields of an object.

    Fields are serialised in the same way that lazr.restful does for
    webservice-exported objects, except that object paths are always local.

    :param interface: The interface of the object to serialise.
    :param obj: The object to serialise.
    :param keys: A list of fields from `obj` to serialise.
    :param preferred_names: [Optional] A dictionary with the field-keys
    as keys, and their preferred name as values.
    """
    # XXX cjwatson 2015-10-19: Fields are serialised with the privileges of
    # the actor, not the webhook owner.  Until this is fixed, callers must
    # make sure that this makes no difference to the fields in question.
    if not preferred_names:
        preferred_names = dict()

    payload = {}
    request = WebhookPayloadRequest()
    for key in keys:
        field = interface[key]
        marshaller = getMultiAdapter((field, request), IFieldMarshaller)
        value = getattr(obj, key, None)
        # Get preferred name for the key, or default to key
        name = preferred_names.get(key, key)
        payload[name] = marshaller.unmarshall(field, value)
    return payload
