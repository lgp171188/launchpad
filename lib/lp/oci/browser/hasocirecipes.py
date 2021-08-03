# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Mixins for browser classes for objects related to OCI recipe."""

__metaclass__ = type
__all__ = [
    'HasOCIRecipesMenuMixin',
    ]

from lp.oci.interfaces.ocirecipe import IOCIRecipeSet
from zope.component import getUtility

from lp.services.webapp import Link


class HasOCIRecipesMenuMixin:
    """A mixin for context menus for objects that has OCI recipes."""

    def view_oci_recipes(self):
        target = '+oci-recipes'
        text = 'View OCI recipes'
        enabled = not getUtility(IOCIRecipeSet).findByContext(
            self.context, visible_by_user=self.user).is_empty()
        return Link(target, text, enabled=enabled, icon='info')
