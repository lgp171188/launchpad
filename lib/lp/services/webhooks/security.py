# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the lp.services.webhooks package."""

__all__ = []

from lp.app.security import (
    AuthorizationBase,
    DelegatedAuthorization,
    )
from lp.services.webhooks.interfaces import (
    IWebhook,
    IWebhookDeliveryJob,
    )


class ViewWebhook(AuthorizationBase):
    """Webhooks can be viewed and edited by someone who can edit the target."""
    permission = 'launchpad.View'
    usedfor = IWebhook

    def checkUnauthenticated(self):
        return False

    def checkAuthenticated(self, user):
        yield self.obj.target, 'launchpad.Edit'


class ViewWebhookDeliveryJob(DelegatedAuthorization):
    """Webhooks can be viewed and edited by someone who can edit the target."""
    permission = 'launchpad.View'
    usedfor = IWebhookDeliveryJob

    def __init__(self, obj):
        super().__init__(obj, obj.webhook, 'launchpad.View')
