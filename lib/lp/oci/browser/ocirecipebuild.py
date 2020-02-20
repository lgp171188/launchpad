# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI recipe build views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeBuildNavigation',
    'OCIRecipeBuildView',
    ]

from zope.interface import Interface

from lp.app.browser.launchpadform import LaunchpadFormView
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild
from lp.services.webapp import (
    canonical_url,
    Navigation,
    )


class OCIRecipeBuildNavigation(Navigation):

    usedfor = IOCIRecipeBuild


class OCIRecipeBuildView(LaunchpadFormView):
    """Default view of an OCIRecipeBuild."""

    class schema(Interface):
        """Schema for uploading a build."""

    @property
    def label(self):
        return self.context.title

    page_title = label

    @property
    def next_url(self):
        return canonical_url(self.context)
