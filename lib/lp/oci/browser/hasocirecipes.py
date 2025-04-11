# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Mixins for browser classes for objects related to OCI recipe."""

__all__ = [
    "HasOCIRecipesMenuMixin",
]

# from zope.component import getUtility

# from lp.oci.interfaces.ocirecipe import IOCIRecipeSet
from lp.services.webapp import Link


class HasOCIRecipesMenuMixin:
    """A mixin for context menus for objects that has OCI recipes."""

    def view_oci_recipes(self):
        target = "+oci-recipes"
        text = "View OCI recipes"

        # The dynamic link enablement uses a query too complex to be useful
        # So we disable it for now, for all recipe types:
        # snap, charm, source, rock and oci
        enabled = True

        # enabled = (
        #    not getUtility(IOCIRecipeSet)
        #    .findByContext(self.context, visible_by_user=self.user)
        #    .is_empty()
        # )
        return Link(target, text, enabled=enabled, icon="info")
