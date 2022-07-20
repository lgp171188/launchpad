# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""VCS-agnostic view aliases that show the default VCS."""

from zope.component import queryMultiAdapter

from lp.registry.enums import VCSType
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.persondistributionsourcepackage import (
    IPersonDistributionSourcePackage,
)
from lp.registry.interfaces.personociproject import IPersonOCIProject
from lp.registry.interfaces.personproduct import IPersonProduct
from lp.services.webapp import stepto


class TargetDefaultVCSNavigationMixin:
    @stepto("+code")
    def traverse_code_view(self):
        if IOCIProject.providedBy(self.context):
            # OCI projects only support Git.
            vcs = VCSType.GIT
        else:
            vcs = self.context.pillar.vcs
        if vcs in (VCSType.BZR, None):
            view_name = "+branches"
        elif vcs == VCSType.GIT:
            view_name = "+git"
        else:
            raise AssertionError("Unknown VCS")
        return queryMultiAdapter((self.context, self.request), name=view_name)


class PersonTargetDefaultVCSNavigationMixin:
    @stepto("+code")
    def traverse_code_view(self):
        if IPersonProduct.providedBy(self.context):
            target = self.context.product
        elif IPersonDistributionSourcePackage.providedBy(self.context):
            target = self.context.distro_source_package
        elif IPersonOCIProject.providedBy(self.context):
            target = self.context.oci_project
        else:
            raise AssertionError("Unknown target: %r" % self.context)
        if IOCIProject.providedBy(target):
            # OCI projects only support Git.
            vcs = VCSType.GIT
        else:
            vcs = target.pillar.vcs
        if vcs in (VCSType.BZR, None):
            view_name = "+branches"
        elif vcs == VCSType.GIT:
            view_name = "+git"
        else:
            raise AssertionError("Unknown VCS")
        return queryMultiAdapter((self.context, self.request), name=view_name)
