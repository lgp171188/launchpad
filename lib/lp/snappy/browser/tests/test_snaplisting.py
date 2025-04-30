# Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test snap package listings."""

from datetime import datetime, timedelta, timezone
from functools import partial

import soupmatchers
from testtools.matchers import MatchesAll, Not
from zope.security.proxy import removeSecurityProxy

from lp.code.tests.helpers import GitHostingFixture
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.product import IProduct
from lp.services.database.constants import ONE_DAY_AGO, SEVEN_DAYS_AGO, UTC_NOW
from lp.services.webapp import canonical_url
from lp.testing import (
    ANONYMOUS,
    BrowserTestCase,
    login,
    person_logged_in,
    record_two_runs,
)
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.views import create_initialized_view


class TestSnapListing(BrowserTestCase):
    layer = LaunchpadFunctionalLayer

    def assertSnapsLink(
        self, context, link_text, link_has_context=False, **kwargs
    ):
        if link_has_context:
            expected_href = canonical_url(context, view_name="+snaps")
        else:
            expected_href = "+snaps"
        matcher = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "View snap packages link",
                "a",
                text=link_text,
                attrs={"href": expected_href},
            )
        )

        if IPerson.providedBy(context) or IProduct.providedBy(context):
            self.assertThat(self.getViewBrowser(context).contents, matcher)
        else:
            self.assertThat(
                self.getViewBrowser(context).contents, Not(matcher)
            )

        login(ANONYMOUS)
        self.factory.makeSnap(**kwargs)
        self.factory.makeSnap(**kwargs)
        self.assertThat(self.getViewBrowser(context).contents, matcher)

    def test_branch_links_to_snaps(self):
        branch = self.factory.makeAnyBranch()
        self.assertSnapsLink(branch, "2 snap packages", branch=branch)

    def test_git_repository_links_to_snaps(self):
        repository = self.factory.makeGitRepository()
        [ref] = self.factory.makeGitRefs(repository=repository)
        self.assertSnapsLink(repository, "2 snap packages", git_ref=ref)

    def test_git_ref_links_to_snaps(self):
        self.useFixture(GitHostingFixture())
        [ref] = self.factory.makeGitRefs()
        self.assertSnapsLink(ref, "2 snap packages", git_ref=ref)

    def test_person_links_to_snaps(self):
        person = self.factory.makePerson()
        self.assertSnapsLink(
            person,
            "View snap packages",
            link_has_context=True,
            registrant=person,
            owner=person,
        )

    def test_project_links_to_snaps(self):
        project = self.factory.makeProduct()
        [ref] = self.factory.makeGitRefs(target=project)
        self.assertSnapsLink(
            project, "View snap packages", link_has_context=True, git_ref=ref
        )

    def test_branch_snap_listing(self):
        # We can see snap packages for a Bazaar branch.
        branch = self.factory.makeAnyBranch()
        self.factory.makeSnap(branch=branch)
        text = self.getMainText(branch, "+snaps")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """
            Snap packages for lp:.*
            Name            Owner           Registered
            snap-name.*     Team Name.*     .*""",
            text,
        )

    def test_git_repository_snap_listing(self):
        # We can see snap packages for a Git repository.
        repository = self.factory.makeGitRepository()
        [ref] = self.factory.makeGitRefs(repository=repository)
        self.factory.makeSnap(git_ref=ref)
        text = self.getMainText(repository, "+snaps")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """
            Snap packages for lp:~.*
            Name            Owner           Registered
            snap-name.*     Team Name.*     .*""",
            text,
        )

    def test_git_ref_snap_listing(self):
        # We can see snap packages for a Git reference.
        [ref] = self.factory.makeGitRefs()
        self.factory.makeSnap(git_ref=ref)
        text = self.getMainText(ref, "+snaps")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """
            Snap packages for ~.*:.*
            Name            Owner           Registered
            snap-name.*     Team Name.*     .*""",
            text,
        )

    def test_person_snap_listing(self):
        # We can see snap packages for a person.
        owner = self.factory.makePerson(displayname="Snap Owner")
        self.factory.makeSnap(
            registrant=owner,
            owner=owner,
            branch=self.factory.makeAnyBranch(),
            date_created=SEVEN_DAYS_AGO,
        )
        [ref] = self.factory.makeGitRefs()
        self.factory.makeSnap(
            registrant=owner,
            owner=owner,
            git_ref=ref,
            date_created=ONE_DAY_AGO,
        )
        remote_ref = self.factory.makeGitRefRemote()
        self.factory.makeSnap(
            registrant=owner,
            owner=owner,
            git_ref=remote_ref,
            date_created=UTC_NOW,
        )
        text = self.getMainText(owner, "+snaps")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """
            Snap packages for Snap Owner
            Name            Source                  Registered
            snap-name.*     http://.* path-.*       .*
            snap-name.*     ~.*:.*                  .*
            snap-name.*     lp:.*                   .*""",
            text,
        )

    def test_project_snap_listing(self):
        # We can see snap packages for a project.
        project = self.factory.makeProduct(displayname="Snappable")
        self.factory.makeSnap(
            branch=self.factory.makeProductBranch(product=project),
            date_created=ONE_DAY_AGO,
        )
        [ref] = self.factory.makeGitRefs(target=project)
        self.factory.makeSnap(git_ref=ref, date_created=UTC_NOW)
        text = self.getMainText(project, "+snaps")
        self.assertTextMatchesExpressionIgnoreWhitespace(
            """
            Snap packages for Snappable
            Name            Owner           Source          Registered
            snap-name.*     Team Name.*     ~.*:.*          .*
            snap-name.*     Team Name.*     lp:.*           .*""",
            text,
        )

    def test_project_private_snap_listing(self):
        # Only users with permission can see private snap packages in the list
        # for a project.
        project = self.factory.makeProduct(displayname="Snappable")
        private_owner = self.factory.makePerson()
        user_with_permission = self.factory.makePerson()
        someone_else = self.factory.makePerson()
        private_snap = self.factory.makeSnap(
            name="private-snap",
            private=True,
            registrant=private_owner,
            owner=private_owner,
            branch=self.factory.makeProductBranch(product=project),
            date_created=ONE_DAY_AGO,
        )
        with person_logged_in(private_owner):
            private_snap.subscribe(user_with_permission, private_owner)
        [ref] = self.factory.makeGitRefs(target=project)
        self.factory.makeSnap(git_ref=ref, date_created=UTC_NOW)

        full_list = """
            Snap packages for Snappable
            Name            Owner           Source          Registered
            snap-name.*     Team Name.*     ~.*:.*           .*
            private-snap.*  Person-name.*   lp:.*            .*"""

        public_list = """
            Snap packages for Snappable
            Name            Owner           Source          Registered
            snap-name.*     Team Name.*     ~.*:.*          .*"""

        # private_owner: full_list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list, self.getMainText(project, "+snaps", user=private_owner)
        )
        # user_with_permission: full_list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list,
            self.getMainText(project, "+snaps", user=user_with_permission),
        )
        # someone_else: public_list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list, self.getMainText(project, "+snaps", user=someone_else)
        )
        # Not logged in: public_list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list, self.getMainText(project, "+snaps", user=None)
        )

    def test_person_private_snap_listing(self):
        private_owner = self.factory.makePerson(name="random-user")
        user_with_permission = self.factory.makePerson()
        someone_else = self.factory.makePerson()
        private_snap = self.factory.makeSnap(
            name="private-snap",
            private=True,
            registrant=private_owner,
            owner=private_owner,
            date_created=ONE_DAY_AGO,
        )
        with person_logged_in(private_owner):
            private_snap.subscribe(user_with_permission, private_owner)
        [ref] = self.factory.makeGitRefs()
        self.factory.makeSnap(
            private=False,
            registrant=private_owner,
            owner=private_owner,
            git_ref=ref,
            date_created=UTC_NOW,
        )

        full_list = """
            Snap packages for Random-user
            Name               Source          Registered
            snap-name.*        ~.*:.*          .*
            private-snap.*     lp:.*           .*"""

        public_list = """
            Snap packages for Random-user
            Name               Source          Registered
            snap-name.*        ~.*:.*          .*"""

        # private_owner: full_list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list,
            self.getMainText(private_owner, "+snaps", user=private_owner),
        )
        # user_with_permission: full_list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list,
            self.getMainText(
                private_owner, "+snaps", user=user_with_permission
            ),
        )
        # someone_else: public_list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list,
            self.getMainText(private_owner, "+snaps", user=someone_else),
        )
        # Not logged in: public_list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list, self.getMainText(private_owner, "+snaps", user=None)
        )

    def test_branch_private_snap_listing(self):
        # Only certain users can see private snaps on branch listing.
        private_owner = self.factory.makePerson(name="random-user")
        user_with_permission = self.factory.makePerson()
        someone_else = self.factory.makePerson()
        branch = self.factory.makeAnyBranch()
        private_snap = self.factory.makeSnap(
            private=True,
            name="private-snap",
            owner=private_owner,
            registrant=private_owner,
            branch=branch,
            date_created=ONE_DAY_AGO,
        )
        with person_logged_in(private_owner):
            private_snap.subscribe(user_with_permission, private_owner)
        self.factory.makeSnap(
            private=False,
            owner=private_owner,
            registrant=private_owner,
            branch=branch,
        )
        full_list = """
            Snap packages for lp:.*
            Name            Owner           Registered
            snap-name.*     Random-user.*   .*
            private-snap.*  Random-user.*   .*"""
        public_list = """
            Snap packages for lp:.*
            Name            Owner           Registered
            snap-name.*     Random-user.*     .*"""

        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list, self.getMainText(branch, "+snaps", user=private_owner)
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list,
            self.getMainText(branch, "+snaps", user=user_with_permission),
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list, self.getMainText(branch, "+snaps", user=someone_else)
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list, self.getMainText(branch, "+snaps", user=None)
        )

    def test_git_repository_private_snap_listing(self):
        # Only certain users can see private snaps on git repo listing.
        private_owner = self.factory.makePerson(name="random-user")
        user_with_permission = self.factory.makePerson()
        someone_else = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        [ref] = self.factory.makeGitRefs(repository=repository)
        private_snap = self.factory.makeSnap(
            private=True,
            name="private-snap",
            owner=private_owner,
            registrant=private_owner,
            git_ref=ref,
            date_created=ONE_DAY_AGO,
        )
        with person_logged_in(private_owner):
            private_snap.subscribe(user_with_permission, private_owner)
        self.factory.makeSnap(
            private=False,
            owner=private_owner,
            registrant=private_owner,
            git_ref=ref,
        )

        full_list = """
            Snap packages for lp:~.*
            Name            Owner           Registered
            snap-name.*     Random-user.*   .*
            private-snap.*  Random-user.*   .*"""
        public_list = """
            Snap packages for lp:.*
            Name            Owner           Registered
            snap-name.*     Random-user.*     .*"""

        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list,
            self.getMainText(repository, "+snaps", user=private_owner),
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list,
            self.getMainText(repository, "+snaps", user=user_with_permission),
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list,
            self.getMainText(repository, "+snaps", user=someone_else),
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list, self.getMainText(repository, "+snaps", user=None)
        )

    def test_git_ref_private_snap_listing(self):
        # Only certain users can see private snaps on git ref listing.
        private_owner = self.factory.makePerson(name="random-user")
        user_with_permission = self.factory.makePerson()
        someone_else = self.factory.makePerson()
        repository = self.factory.makeGitRepository()
        [ref] = self.factory.makeGitRefs(repository=repository)
        private_snap = self.factory.makeSnap(
            private=True,
            name="private-snap",
            owner=private_owner,
            registrant=private_owner,
            git_ref=ref,
            date_created=ONE_DAY_AGO,
        )
        with person_logged_in(private_owner):
            private_snap.subscribe(user_with_permission, private_owner)
        self.factory.makeSnap(
            private=False,
            owner=private_owner,
            registrant=private_owner,
            git_ref=ref,
        )

        full_list = """
                    Snap packages for ~.*:.*
                    Name            Owner           Registered
                    snap-name.*     Random-user.*   .*
                    private-snap.*  Random-user.*   .*"""
        public_list = """
                    Snap packages for ~.*:.*
                    Name            Owner           Registered
                    snap-name.*     Random-user.*     .*"""

        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list, self.getMainText(ref, "+snaps", user=private_owner)
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            full_list,
            self.getMainText(ref, "+snaps", user=user_with_permission),
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list, self.getMainText(ref, "+snaps", user=someone_else)
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            public_list, self.getMainText(ref, "+snaps", user=None)
        )

    def assertSnapsQueryCount(self, context, item_creator):
        self.pushConfig("launchpad", default_batch_size=10)
        recorder1, recorder2 = record_two_runs(
            lambda: self.getMainText(context, "+snaps"), item_creator, 5
        )
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))

    def test_branch_query_count(self):
        # The number of queries required to render the list of all snap
        # packages for a Bazaar branch is constant in the number of owners
        # and snap packages.
        person = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(owner=person)

        def create_snap():
            with person_logged_in(person):
                self.factory.makeSnap(branch=branch)

        self.assertSnapsQueryCount(branch, create_snap)

    def test_git_repository_query_count(self):
        # The number of queries required to render the list of all snap
        # packages for a Git repository is constant in the number of owners
        # and snap packages.
        person = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=person)

        def create_snap():
            with person_logged_in(person):
                [ref] = self.factory.makeGitRefs(repository=repository)
                self.factory.makeSnap(git_ref=ref)

        self.assertSnapsQueryCount(repository, create_snap)

    def test_git_ref_query_count(self):
        # The number of queries required to render the list of all snap
        # packages for a Git reference is constant in the number of owners
        # and snap packages.
        person = self.factory.makePerson()
        [ref] = self.factory.makeGitRefs(owner=person)

        def create_snap():
            with person_logged_in(person):
                self.factory.makeSnap(git_ref=ref)

        self.assertSnapsQueryCount(ref, create_snap)

    def test_person_query_count(self):
        # The number of queries required to render the list of all snap
        # packages for a person is constant in the number of projects,
        # sources, and snap packages.
        person = self.factory.makePerson()
        i = 0

        def create_snap():
            with person_logged_in(person):
                project = self.factory.makeProduct()
                if (i % 2) == 0:
                    branch = self.factory.makeProductBranch(
                        owner=person, product=project
                    )
                    self.factory.makeSnap(branch=branch)
                else:
                    [ref] = self.factory.makeGitRefs(
                        owner=person, target=project
                    )
                    self.factory.makeSnap(git_ref=ref)

        self.assertSnapsQueryCount(person, create_snap)

    def test_project_query_count(self):
        # The number of queries required to render the list of all snap
        # packages for a person is constant in the number of owners,
        # sources, and snap packages.
        person = self.factory.makePerson()
        project = self.factory.makeProduct(owner=person)
        i = 0

        def create_snap():
            with person_logged_in(person):
                if (i % 2) == 0:
                    branch = self.factory.makeProductBranch(product=project)
                    self.factory.makeSnap(branch=branch)
                else:
                    [ref] = self.factory.makeGitRefs(target=project)
                    self.factory.makeSnap(git_ref=ref)

        self.assertSnapsQueryCount(project, create_snap)

    def makeSnapsAndMatchers(self, create_snap, count, start_time):
        snaps = [create_snap() for i in range(count)]
        for i, snap in enumerate(snaps):
            removeSecurityProxy(snap).date_last_modified = (
                start_time - timedelta(seconds=i)
            )
        return [
            soupmatchers.Tag(
                "snap link",
                "a",
                text=snap.name,
                attrs={
                    "href": canonical_url(snap, path_only_if_possible=True)
                },
            )
            for snap in snaps
        ]

    def assertBatches(self, context, link_matchers, batched, start, size):
        view = create_initialized_view(context, "+snaps")
        listing_tag = soupmatchers.Tag(
            "snap listing", "table", attrs={"class": "listing sortable"}
        )
        batch_nav_tag = soupmatchers.Tag(
            "batch nav links", "td", attrs={"class": "batch-navigation-links"}
        )
        present_links = ([batch_nav_tag] if batched else []) + [
            matcher
            for i, matcher in enumerate(link_matchers)
            if i in range(start, start + size)
        ]
        absent_links = ([] if batched else [batch_nav_tag]) + [
            matcher
            for i, matcher in enumerate(link_matchers)
            if i not in range(start, start + size)
        ]
        self.assertThat(
            view.render(),
            MatchesAll(
                soupmatchers.HTMLContains(listing_tag, *present_links),
                Not(soupmatchers.HTMLContains(*absent_links)),
            ),
        )

    def test_branch_batches_snaps(self):
        branch = self.factory.makeAnyBranch()
        create_snap = partial(self.factory.makeSnap, branch=branch)
        now = datetime.now(timezone.utc)
        link_matchers = self.makeSnapsAndMatchers(create_snap, 3, now)
        self.assertBatches(branch, link_matchers, False, 0, 3)
        link_matchers.extend(
            self.makeSnapsAndMatchers(
                create_snap, 7, now - timedelta(seconds=3)
            )
        )
        self.assertBatches(branch, link_matchers, True, 0, 5)

    def test_git_repository_batches_snaps(self):
        repository = self.factory.makeGitRepository()
        [ref] = self.factory.makeGitRefs(repository=repository)
        create_snap = partial(self.factory.makeSnap, git_ref=ref)
        now = datetime.now(timezone.utc)
        link_matchers = self.makeSnapsAndMatchers(create_snap, 3, now)
        self.assertBatches(repository, link_matchers, False, 0, 3)
        link_matchers.extend(
            self.makeSnapsAndMatchers(
                create_snap, 7, now - timedelta(seconds=3)
            )
        )
        self.assertBatches(repository, link_matchers, True, 0, 5)

    def test_git_ref_batches_snaps(self):
        [ref] = self.factory.makeGitRefs()
        create_snap = partial(self.factory.makeSnap, git_ref=ref)
        now = datetime.now(timezone.utc)
        link_matchers = self.makeSnapsAndMatchers(create_snap, 3, now)
        self.assertBatches(ref, link_matchers, False, 0, 3)
        link_matchers.extend(
            self.makeSnapsAndMatchers(
                create_snap, 7, now - timedelta(seconds=3)
            )
        )
        self.assertBatches(ref, link_matchers, True, 0, 5)

    def test_person_batches_snaps(self):
        owner = self.factory.makePerson()
        create_snap = partial(
            self.factory.makeSnap, registrant=owner, owner=owner
        )
        now = datetime.now(timezone.utc)
        link_matchers = self.makeSnapsAndMatchers(create_snap, 3, now)
        self.assertBatches(owner, link_matchers, False, 0, 3)
        link_matchers.extend(
            self.makeSnapsAndMatchers(
                create_snap, 7, now - timedelta(seconds=3)
            )
        )
        self.assertBatches(owner, link_matchers, True, 0, 5)

    def test_project_batches_snaps(self):
        project = self.factory.makeProduct()
        branch = self.factory.makeProductBranch(product=project)
        create_snap = partial(self.factory.makeSnap, branch=branch)
        now = datetime.now(timezone.utc)
        link_matchers = self.makeSnapsAndMatchers(create_snap, 3, now)
        self.assertBatches(project, link_matchers, False, 0, 3)
        link_matchers.extend(
            self.makeSnapsAndMatchers(
                create_snap, 7, now - timedelta(seconds=3)
            )
        )
        self.assertBatches(project, link_matchers, True, 0, 5)
