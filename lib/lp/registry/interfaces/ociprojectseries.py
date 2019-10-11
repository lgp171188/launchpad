# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface implementing `OCIProjectSeries`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIProjectSeries',
    'IOCIProjectSeriesSet'
    ]

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import (
    Int,
    TextLine,
    )

from lp import _
from lp.app.validators.name import name_validator
from lp.registry.interfaces.ociproject import IOCIProject


class IOCIProjectSeries(Interface):
    """A series of an Open Container Initiative recipe target,
       used to allow tracking bugs against multiple versions of images.
    """

    id = Int(title=_("ID"), required=True, readonly=True)

    ociproject = Reference(
        IOCIProject,
        title=_("The target that this series belongs to."),
        required=True)

    name = TextLine(
        title=_("Name"), constraint=name_validator,
        required=True, readonly=False,
        description=_("The name of this series."))


class IOCIProjectSeriesSet(Interface):
    """A set of OCIProjectSeries."""

    def new(ociproject, name):
        """Create a new `OCIProjectSeries`."""
