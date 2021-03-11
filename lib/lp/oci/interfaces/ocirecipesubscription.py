# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipe subscription model."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIRecipeSubscription'
]

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import (
    Datetime,
    Int,
    )

from lp import _
from lp.services.fields import PersonChoice
from lp.oci.interfaces.ocirecipe import IOCIRecipe


class IOCIRecipeSubscription(Interface):
    """A person subscription to a specific OCIRecipe recipe."""

    id = Int(title=_('ID'), readonly=True, required=True)
    person = PersonChoice(
        title=_('Person'), required=True, vocabulary='ValidPersonOrTeam',
        readonly=True,
        description=_("The person subscribed to the related OCI recipe."))
    ocirecipe = Reference(
        IOCIRecipe, title=_("OCI recipe"), required=True, readonly=True)
    subscribed_by = PersonChoice(
        title=_('Subscribed by'), required=True,
        vocabulary='ValidPersonOrTeam', readonly=True,
        description=_("The person who created this subscription."))
    date_created = Datetime(
        title=_('Date subscribed'), required=True, readonly=True)

    def canBeUnsubscribedByUser(user):
        """Can the user unsubscribe the subscriber from the OCI recipe?"""
