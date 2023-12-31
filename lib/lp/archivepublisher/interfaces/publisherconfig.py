# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""PublisherConfig interface."""

__all__ = [
    "IPublisherConfig",
    "IPublisherConfigSet",
]

import os.path

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import Int, TextLine

from lp import _
from lp.app.validators.path import path_does_not_escape
from lp.registry.interfaces.distribution import IDistribution


class IPublisherConfig(Interface):
    """`PublisherConfig` interface."""

    id = Int(title=_("ID"), required=True, readonly=True)

    distribution = Reference(
        IDistribution,
        title=_("Distribution"),
        required=True,
        description=_("The Distribution for this configuration."),
    )

    root_dir = TextLine(
        title=_("Root Directory"),
        required=True,
        description=_("The root directory for published archives."),
        # Only basic validation; setting this field is restricted to
        # Launchpad administrators, and they can already set full absolute
        # paths here, so we don't currently worry about symlink attacks or
        # similar.  We forbid a leading ../ just to avoid getting ourselves
        # into confusing tangles.
        constraint=(
            lambda path: os.path.isabs(path) or path_does_not_escape(path)
        ),
    )

    absolute_root_dir = TextLine(
        title=_("Root directory as an absolute path"),
        required=True,
        readonly=True,
        description=_(
            "The root directory for published archives, expanded relative to "
            "config.archivepublisher.archives_dir."
        ),
    )

    base_url = TextLine(
        title=_("Base URL"),
        required=True,
        description=_("The base URL for published archives"),
    )

    copy_base_url = TextLine(
        title=_("Copy Base URL"),
        required=True,
        description=_("The base URL for published copy archives"),
    )


class IPublisherConfigSet(Interface):
    """`PublisherConfigSet` interface."""

    def new(distribution, root_dir, base_url, copy_base_url):
        """Create a new `PublisherConfig`."""

    def getByDistribution(distribution):
        """Get the config for a a distribution.

        :param distribution: An `IDistribution`
        """
