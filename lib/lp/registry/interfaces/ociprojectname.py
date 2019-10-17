# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Project Name interfaces."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIProjectName',
    'IOCIProjectNameSet',
    ]

from zope.interface import Interface
from zope.schema import (
    Int,
    TextLine,
    )

from lp import _
from lp.app.validators.name import name_validator


class IOCIProjectName(Interface):
    """A name of an Open Container Initiative project.

    This is a tiny table that allows multiple OCIProject entities to share
    a single name.
    """
    id = Int(title=_("ID"), required=True, readonly=True)

    name = TextLine(
        title=_("Name"), constraint=name_validator,
        required=True, readonly=False,
        description=_("The name of the OCI Project."))


class IOCIProjectNameSet(Interface):
    """A set of `OCIProjectName`."""

    def __getitem__(name):
        """Retrieve a `OCIProjectName` by name."""

    def getByName(name):
        """Return a `OCIProjectName` by its name.

        :raises NoSuchOCIProjectName: if the `OCIProjectName` can't be found.
        """

    def new(name):
        """Create a new `OCIProjectName`."""
