# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap subscription model."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'ISnapSubscription'
]

from lazr.restful.fields import Reference
from lp.snappy.interfaces.snap import ISnap
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import (
    Choice,
    Datetime,
    Int,
    )

from lp import _
from lp.services.fields import PersonChoice


class ISnapSubscription(Interface):
    """A person subscription to a specific Snap recipe."""

    id = Int(title=_('ID'), readonly=True, required=True)
    person = PersonChoice(
        title=_('Person'), required=True, vocabulary='ValidPersonOrTeam',
        readonly=True,
        description=_("The person subscribed to the related snap recipe."))
    snap = Reference(ISnap, title=_("Snap"), required=True, readonly=True)
    subscribed_by = PersonChoice(
        title=_('Subscribed by'), required=True,
        vocabulary='ValidPersonOrTeam', readonly=True,
        description=_("The person who created this subscription."))
    date_created = Datetime(
        title=_('Date subscribed'), required=True, readonly=True)

    def canBeUnsubscribedByUser(user):
        """Can the user unsubscribe the subscriber from the snap recipe?"""
