# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from testscenarios.testcase import WithScenarios

from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.views import create_view


class TestBugTargetTags(WithScenarios, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    scenarios = [
        ("product + group", {"factory_name": "makeProductAndGroup"}),
        ("product", {"factory_name": "makeProduct"}),
        ("distribution", {"factory_name": "makeDistribution"}),
        (
            "ociproject of product",
            {"factory_name": "makeOCIProjectFromProduct"},
        ),
        ("ociproject of distro", {"factory_name": "makeOCIProjectFromDistro"}),
    ]

    def makeProductAndGroup(self):
        project_group = self.factory.makeProject()
        product = self.factory.makeProduct(projectgroup=project_group)
        return project_group, product

    def makeProduct(self):
        prod = self.factory.makeProduct()
        return prod, prod

    def makeDistribution(self):
        distro = self.factory.makeDistribution()
        return distro, distro

    def makeOCIProjectFromProduct(self):
        target = self.factory.makeProduct()
        ociproject = self.factory.makeOCIProject(pillar=target)
        return ociproject, ociproject

    def makeOCIProjectFromDistro(self):
        target = self.factory.makeDistribution()
        ociproject = self.factory.makeOCIProject(pillar=target)
        return ociproject, ociproject

    def setUp(self):
        super().setUp()
        builder = getattr(self, self.factory_name)
        self.view_context, self.bug_target = builder()

    def test_no_tags(self):
        self.factory.makeBug(target=self.bug_target)
        view = create_view(
            self.view_context, name="+bugtarget-portlet-tags-content"
        )
        self.assertEqual([], [tag["tag"] for tag in view.tags_cloud_data])

    def test_tags(self):
        self.factory.makeBug(target=self.bug_target, tags=["foo"])
        view = create_view(
            self.view_context, name="+bugtarget-portlet-tags-content"
        )
        self.assertEqual(["foo"], [tag["tag"] for tag in view.tags_cloud_data])

    def test_tags_order(self):
        """Test that the tags are ordered by most used first"""
        self.factory.makeBug(target=self.bug_target, tags=["tag-last"])
        for counter in range(0, 2):
            self.factory.makeBug(target=self.bug_target, tags=["tag-middle"])
        for counter in range(0, 3):
            self.factory.makeBug(target=self.bug_target, tags=["tag-first"])
        view = create_view(
            self.view_context, name="+bugtarget-portlet-tags-content"
        )
        self.assertEqual(
            ["tag-first", "tag-middle", "tag-last"],
            [tag["tag"] for tag in view.tags_cloud_data],
        )
