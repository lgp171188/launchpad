# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for a build record for OCI recipes."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'IOCIRecipeBuild',
    ]

from lp.buildmaster.enums import BuildStatus
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import (
    Bool,
    Datetime,
    Int,
    Text,
    )

from lp import _
from lp.buildmaster.interfaces.builder import IBuilder
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.buildmaster.interfaces.processor import IProcessor
from lp.oci.interfaces.ocirecipe import IOCIRecipe


class IOCIRecipeBuild(IPackageBuild):

    requester = PublicPersonChoice(
        title=_("Requester"),
        description=_("The person who requested this OCI recipe build."),
        vocabulary='ValidPersonOrTeam', required=True, readonly=True)

    recipe = Reference(
        IOCIRecipe,
        title=_("The OCI recipe to build."),
        required=True,
        readonly=True)
