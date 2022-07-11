# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the lp.services.messages package."""

__all__ = []

from lp.app.security import (
    AuthorizationBase,
    DelegatedAuthorization,
    )
from lp.services.messages.interfaces.message import IMessage
from lp.services.messages.interfaces.messagerevision import IMessageRevision


class SetMessageVisibility(AuthorizationBase):
    permission = 'launchpad.Admin'
    usedfor = IMessage

    def checkAuthenticated(self, user):
        """Admins and registry admins can set bug comment visibility."""
        return (user.in_admin or user.in_registry_experts)


class EditMessage(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = IMessage

    def checkAuthenticated(self, user):
        """Only message owner can edit it."""
        return user.isOwner(self.obj)


class EditMessageRevision(DelegatedAuthorization):
    permission = 'launchpad.Edit'
    usedfor = IMessageRevision

    def __init__(self, obj):
        super().__init__(obj, obj.message, 'launchpad.Edit')
