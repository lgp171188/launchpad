# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test `BugTargetTraversalMixin`."""

from zope.publisher.interfaces import NotFound
from zope.security.proxy import removeSecurityProxy

from lp.registry.interfaces.externalpackage import ExternalPackageType
from lp.services.webapp.publisher import canonical_url
from lp.testing import TestCaseWithFactory, login_person
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.publication import test_traverse


class TestBugTaskTraversal(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_traversal_to_nonexistent_bugtask(self):
        # Test that a traversing to a non-existent bugtask redirects to the
        # bug's default bugtask.
        bug = self.factory.makeBug()
        bugtask = self.factory.makeBugTask(bug=bug)
        bugtask_url = canonical_url(bugtask, rootsite="bugs")
        login_person(bugtask.owner)
        bugtask.delete()
        obj, view, request = test_traverse(bugtask_url)
        view()
        naked_view = removeSecurityProxy(view)
        self.assertEqual(301, request.response.getStatus())
        self.assertEqual(
            naked_view.target,
            canonical_url(bug.default_bugtask, rootsite="bugs"),
        )

    def test_traversal_to_bugtask_delete_url(self):
        # Test that a traversing to the delete URL of a non-existent bugtask
        # raises a NotFound error.
        bug = self.factory.makeBug()
        bugtask = self.factory.makeBugTask(bug=bug)
        bugtask_delete_url = canonical_url(
            bugtask, rootsite="bugs", view_name="+delete"
        )
        login_person(bugtask.owner)
        bugtask.delete()
        self.assertRaises(NotFound, test_traverse, bugtask_delete_url)

    def test_traversal_to_nonexistent_bugtask_on_api(self):
        # Traversing to a non-existent bugtask on the API redirects to
        # the default bugtask, but also on the API.
        bug = self.factory.makeBug()
        product = self.factory.makeProduct()
        obj, view, request = test_traverse(
            "http://api.launchpad.test/1.0/%s/+bug/%d"
            % (product.name, bug.default_bugtask.bug.id)
        )
        self.assertEqual(
            removeSecurityProxy(view).target,
            "http://api.launchpad.test/1.0/%s/+bug/%d"
            % (bug.default_bugtask.target.name, bug.default_bugtask.bug.id),
        )

    def test_traversal_to_external_package_bugtask(self):
        # Test that traversal using +bugtask/id works
        # Test that we can differ between bugtasks with same packagename and
        # distribution, but different packagetype or channel
        bug = self.factory.makeBug()
        distribution = self.factory.makeDistribution()
        spn = self.factory.makeSourcePackageName(name="mypackage")

        ep = self.factory.makeExternalPackage(
            distribution=distribution,
            sourcepackagename=spn,
            packagetype=ExternalPackageType.SNAP,
            channel=("11", "stable"),
        )
        ep_2 = self.factory.makeExternalPackage(
            distribution=distribution,
            sourcepackagename=spn,
            packagetype=ExternalPackageType.SNAP,
            channel=("11", "edge"),
        )
        ep_3 = self.factory.makeExternalPackage(
            distribution=distribution,
            sourcepackagename=spn,
            packagetype=ExternalPackageType.CHARM,
            channel=("11", "stable"),
        )

        bugtask = self.factory.makeBugTask(bug=bug, target=ep)
        bugtask_url = canonical_url(bugtask)
        bugtask_2 = self.factory.makeBugTask(bug=bug, target=ep_2)
        bugtask_url_2 = canonical_url(bugtask_2)
        bugtask_3 = self.factory.makeBugTask(bug=bug, target=ep_3)
        bugtask_url_3 = canonical_url(bugtask_3)
        # makeBug creates the first and default bugtask
        self.assertEqual(4, len(bug.bugtasks))

        self.assertEqual(
            bugtask_url,
            "http://bugs.launchpad.test/%s/+external/%s/+bug/%d/+bugtask/%s"
            % (
                bugtask.distribution.name,
                bugtask.target.name,
                bugtask.bug.id,
                bugtask.id,
            ),
        )
        self.assertEqual(
            bugtask_url_2,
            "http://bugs.launchpad.test/%s/+external/%s/+bug/%d/+bugtask/%s"
            % (
                bugtask_2.distribution.name,
                bugtask_2.target.name,
                bugtask_2.bug.id,
                bugtask_2.id,
            ),
        )
        self.assertEqual(
            bugtask_url_3,
            "http://bugs.launchpad.test/%s/+external/%s/+bug/%d/+bugtask/%s"
            % (
                bugtask_3.distribution.name,
                bugtask_3.target.name,
                bugtask_3.bug.id,
                bugtask_3.id,
            ),
        )

        obj, _, _ = test_traverse(bugtask_url)
        self.assertEqual(bugtask, obj)
        self.assertEqual(ep, obj.target)
        obj_2, _, _ = test_traverse(bugtask_url_2)
        self.assertEqual(bugtask_2, obj_2)
        self.assertEqual(ep_2, obj_2.target)
        obj_3, _, _ = test_traverse(bugtask_url_3)
        self.assertEqual(bugtask_3, obj_3)
        self.assertEqual(ep_3, obj_3.target)

    def test_traversal_to_default_external_package_bugtask(self):
        # Test that a traversing to a bug with an external package as default
        # bugtask redirects to the bug's default bugtask using +bugtask/id.
        ep = self.factory.makeExternalPackage()
        bug = self.factory.makeBug(target=ep)
        bug_url = canonical_url(bug, rootsite="bugs")
        obj, view, request = test_traverse(bug_url)
        view()
        naked_view = removeSecurityProxy(view)
        self.assertEqual(303, request.response.getStatus())
        self.assertEqual(
            naked_view.target,
            canonical_url(bug.default_bugtask, rootsite="bugs"),
        )
        self.assertEqual(
            removeSecurityProxy(view).target,
            "http://bugs.launchpad.test/%s/+external/%s/+bug/%d/+bugtask/%s"
            % (
                bug.default_bugtask.distribution.name,
                bug.default_bugtask.target.name,
                bug.default_bugtask.bug.id,
                bug.default_bugtask.id,
            ),
        )

    def test_traversal_to_default_external_package_bugtask_on_api(self):
        # Traversing to a bug with an external package as default task
        # redirects to the +bugtask/id also in the API.
        ep = self.factory.makeExternalPackage()
        bug = self.factory.makeBug(target=ep)
        obj, view, request = test_traverse(
            "http://api.launchpad.test/1.0/%s/+bug/%d"
            % (
                removeSecurityProxy(ep).distribution.name,
                bug.default_bugtask.bug.id,
            )
        )
        self.assertEqual(
            removeSecurityProxy(view).target,
            "http://api.launchpad.test/1.0/%s/+external/%s/+bug/%d/+bugtask/%s"
            % (
                bug.default_bugtask.distribution.name,
                bug.default_bugtask.target.name,
                bug.default_bugtask.bug.id,
                bug.default_bugtask.id,
            ),
        )
