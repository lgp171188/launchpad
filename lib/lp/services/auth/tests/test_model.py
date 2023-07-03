# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test personal access tokens."""

import hashlib
import os
import signal
from datetime import datetime, timedelta, timezone

import transaction
from storm.store import Store
from testtools.matchers import Is, MatchesStructure
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.services.auth.enums import AccessTokenScope
from lp.services.auth.interfaces import IAccessTokenSet
from lp.services.auth.utils import create_access_token_secret
from lp.services.database.sqlbase import (
    disconnect_stores,
    get_transaction_timestamp,
)
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    TestCaseWithFactory,
    api_url,
    login,
    login_person,
    person_logged_in,
    record_two_runs,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import webservice_for_person


class TestAccessToken(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_owner_can_edit(self):
        owner = self.factory.makePerson()
        _, token = self.factory.makeAccessToken(owner=owner)
        login_person(owner)
        self.assertTrue(check_permission("launchpad.Edit", token))

    def test_target_owner_can_edit(self):
        target_owner = self.factory.makePerson()
        repository = self.factory.makeGitRepository(owner=target_owner)
        _, token = self.factory.makeAccessToken(target=repository)
        login_person(target_owner)
        self.assertTrue(check_permission("launchpad.Edit", token))

    def test_other_user_cannot_edit(self):
        _, token = self.factory.makeAccessToken()
        login_person(self.factory.makePerson())
        self.assertFalse(check_permission("launchpad.Edit", token))

    def test_updateLastUsed_never_used(self):
        # If the token has never been used, we update its last-used date.
        owner = self.factory.makePerson()
        _, token = self.factory.makeAccessToken(owner=owner)
        login_person(owner)
        self.assertIsNone(token.date_last_used)
        transaction.commit()
        token.updateLastUsed()
        now = get_transaction_timestamp(Store.of(token))
        self.assertEqual(now, token.date_last_used)

    def test_updateLastUsed_recent(self):
        # If the token's last-used date was updated recently, we leave it
        # alone.
        owner = self.factory.makePerson()
        _, token = self.factory.makeAccessToken(owner=owner)
        login_person(owner)
        recent = datetime.now(timezone.utc) - timedelta(minutes=1)
        removeSecurityProxy(token).date_last_used = recent
        transaction.commit()
        token.updateLastUsed()
        self.assertEqual(recent, token.date_last_used)

    def test_updateLastUsed_old(self):
        # If the token's last-used date is outside our update resolution, we
        # update it.
        owner = self.factory.makePerson()
        _, token = self.factory.makeAccessToken(owner=owner)
        login_person(owner)
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        removeSecurityProxy(token).date_last_used = recent
        transaction.commit()
        token.updateLastUsed()
        now = get_transaction_timestamp(Store.of(token))
        self.assertEqual(now, token.date_last_used)

    def test_updateLastUsed_concurrent(self):
        # If the token is locked by another transaction, we leave it alone.
        owner = self.factory.makePerson()
        owner_email = removeSecurityProxy(owner.preferredemail).email
        secret, token = self.factory.makeAccessToken(owner=owner)
        login_person(owner)
        self.assertIsNone(token.date_last_used)
        transaction.commit()
        # Fork so that we can lock the token from a different PostgreSQL
        # session.  We must disconnect the Storm store before forking, as
        # libpq connections are not safe for use across forks.
        disconnect_stores()
        read, write = os.pipe()
        pid = os.fork()
        if pid == 0:  # child
            os.close(read)
            login(owner_email)
            token = getUtility(IAccessTokenSet).getBySecret(secret)
            token.updateLastUsed()
            os.write(write, b"1")
            try:
                signal.pause()
            except KeyboardInterrupt:
                pass
            transaction.commit()
            os._exit(0)
        else:  # parent
            try:
                os.close(write)
                os.read(read, 1)
                login(owner_email)
                token = getUtility(IAccessTokenSet).getBySecret(secret)
                token.updateLastUsed()
                now = get_transaction_timestamp(Store.of(token))
                # The last-used date is being updated by a different
                # transaction, which hasn't been committed yet.
                self.assertIsNone(token.date_last_used)
            finally:
                os.kill(pid, signal.SIGINT)
                os.waitpid(pid, 0)
            transaction.commit()
            self.assertIsNotNone(token.date_last_used)
            self.assertNotEqual(now, token.date_last_used)

    def test_is_expired(self):
        owner = self.factory.makePerson()
        login_person(owner)
        _, current_token = self.factory.makeAccessToken(owner=owner)
        _, expired_token = self.factory.makeAccessToken(
            owner=owner,
            date_expires=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        self.assertFalse(current_token.is_expired)
        self.assertTrue(expired_token.is_expired)

    def test_revoke(self):
        owner = self.factory.makePerson()
        _, token = self.factory.makeAccessToken(
            owner=owner, scopes=[AccessTokenScope.REPOSITORY_BUILD_STATUS]
        )
        login_person(owner)
        self.assertThat(
            token, MatchesStructure(date_expires=Is(None), revoked_by=Is(None))
        )
        token.revoke(token.owner)
        now = get_transaction_timestamp(Store.of(token))
        self.assertThat(
            token,
            MatchesStructure.byEquality(
                date_expires=now, revoked_by=token.owner
            ),
        )


class TestAccessTokenSet(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_new(self):
        secret = create_access_token_secret()
        self.assertEqual(64, len(secret))
        owner = self.factory.makePerson()
        description = "Test token"
        target = self.factory.makeGitRepository()
        scopes = [AccessTokenScope.REPOSITORY_BUILD_STATUS]
        _, token = self.factory.makeAccessToken(
            secret=secret,
            owner=owner,
            description=description,
            target=target,
            scopes=scopes,
        )
        self.assertThat(
            removeSecurityProxy(token),
            MatchesStructure.byEquality(
                _token_sha256=hashlib.sha256(secret.encode()).hexdigest(),
                owner=owner,
                description=description,
                target=target,
                scopes=scopes,
            ),
        )

    def test_getByID(self):
        secret, token = self.factory.makeAccessToken()
        token_id = removeSecurityProxy(token).id
        self.assertEqual(token, getUtility(IAccessTokenSet).getByID(token_id))
        self.assertIsNone(getUtility(IAccessTokenSet).getByID(token_id + 1))

    def test_getBySecret(self):
        secret, token = self.factory.makeAccessToken()
        self.assertEqual(
            token, getUtility(IAccessTokenSet).getBySecret(secret)
        )
        self.assertIsNone(
            getUtility(IAccessTokenSet).getBySecret(
                create_access_token_secret()
            )
        )

    def test_findByOwner(self):
        owners = [self.factory.makePerson() for _ in range(3)]
        tokens = [
            self.factory.makeAccessToken(owner=owners[0])[1],
            self.factory.makeAccessToken(owner=owners[0])[1],
            self.factory.makeAccessToken(owner=owners[1])[1],
        ]
        self.assertContentEqual(
            tokens[:2], getUtility(IAccessTokenSet).findByOwner(owners[0])
        )
        self.assertContentEqual(
            [tokens[2]], getUtility(IAccessTokenSet).findByOwner(owners[1])
        )
        self.assertContentEqual(
            [], getUtility(IAccessTokenSet).findByOwner(owners[2])
        )

    def test_findByTarget(self):
        targets = [self.factory.makeGitRepository() for _ in range(3)]
        tokens = [
            self.factory.makeAccessToken(target=targets[0])[1],
            self.factory.makeAccessToken(target=targets[0])[1],
            self.factory.makeAccessToken(target=targets[1])[1],
        ]
        self.assertContentEqual(
            tokens[:2], getUtility(IAccessTokenSet).findByTarget(targets[0])
        )
        self.assertContentEqual(
            [tokens[2]], getUtility(IAccessTokenSet).findByTarget(targets[1])
        )
        self.assertContentEqual(
            [], getUtility(IAccessTokenSet).findByTarget(targets[2])
        )

    def test_findByTarget_visible_by_user(self):
        targets = [self.factory.makeGitRepository() for _ in range(3)]
        owners = [self.factory.makePerson() for _ in range(3)]
        tokens = [
            self.factory.makeAccessToken(
                owner=owners[owner_index], target=targets[target_index]
            )[1]
            for owner_index, target_index in (
                (0, 0),
                (0, 0),
                (1, 0),
                (1, 1),
                (2, 1),
            )
        ]
        for owner_index, target_index, expected_tokens in (
            (0, 0, tokens[:2]),
            (0, 1, []),
            (0, 2, []),
            (1, 0, [tokens[2]]),
            (1, 1, [tokens[3]]),
            (1, 2, []),
            (2, 0, []),
            (2, 1, [tokens[4]]),
            (2, 2, []),
        ):
            self.assertContentEqual(
                expected_tokens,
                getUtility(IAccessTokenSet).findByTarget(
                    targets[target_index], visible_by_user=owners[owner_index]
                ),
            )

    def test_findByTarget_excludes_expired(self):
        target = self.factory.makeGitRepository()
        _, current_token = self.factory.makeAccessToken(target=target)
        _, expires_soon_token = self.factory.makeAccessToken(
            target=target,
            date_expires=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        _, expired_token = self.factory.makeAccessToken(
            target=target,
            date_expires=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        self.assertContentEqual(
            [current_token, expires_soon_token],
            getUtility(IAccessTokenSet).findByTarget(target),
        )
        self.assertContentEqual(
            [current_token, expires_soon_token, expired_token],
            getUtility(IAccessTokenSet).findByTarget(
                target, include_expired=True
            ),
        )

    def test_getByTargetAndID(self):
        targets = [self.factory.makeGitRepository() for _ in range(3)]
        tokens = [
            self.factory.makeAccessToken(target=targets[0])[1],
            self.factory.makeAccessToken(target=targets[0])[1],
            self.factory.makeAccessToken(target=targets[1])[1],
        ]
        self.assertEqual(
            tokens[0],
            getUtility(IAccessTokenSet).getByTargetAndID(
                targets[0], removeSecurityProxy(tokens[0]).id
            ),
        )
        self.assertEqual(
            tokens[1],
            getUtility(IAccessTokenSet).getByTargetAndID(
                targets[0], removeSecurityProxy(tokens[1]).id
            ),
        )
        self.assertIsNone(
            getUtility(IAccessTokenSet).getByTargetAndID(
                targets[0], removeSecurityProxy(tokens[2]).id
            )
        )

    def test_getByTargetAndID_visible_by_user(self):
        targets = [self.factory.makeGitRepository() for _ in range(3)]
        owners = [self.factory.makePerson() for _ in range(3)]
        tokens = [
            self.factory.makeAccessToken(
                owner=owners[owner_index], target=targets[target_index]
            )[1]
            for owner_index, target_index in (
                (0, 0),
                (0, 0),
                (1, 0),
                (1, 1),
                (2, 1),
            )
        ]
        for owner_index, target_index, expected_tokens in (
            (0, 0, tokens[:2]),
            (0, 1, []),
            (0, 2, []),
            (1, 0, [tokens[2]]),
            (1, 1, [tokens[3]]),
            (1, 2, []),
            (2, 0, []),
            (2, 1, [tokens[4]]),
            (2, 2, []),
        ):
            for token in tokens:
                fetched_token = getUtility(IAccessTokenSet).getByTargetAndID(
                    targets[target_index],
                    removeSecurityProxy(token).id,
                    visible_by_user=owners[owner_index],
                )
                if token in expected_tokens:
                    self.assertEqual(token, fetched_token)
                else:
                    self.assertIsNone(fetched_token)

    def test_getByTargetAndID_excludes_expired(self):
        target = self.factory.makeGitRepository()
        _, current_token = self.factory.makeAccessToken(target=target)
        _, expires_soon_token = self.factory.makeAccessToken(
            target=target,
            date_expires=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        _, expired_token = self.factory.makeAccessToken(
            target=target,
            date_expires=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        self.assertEqual(
            current_token,
            getUtility(IAccessTokenSet).getByTargetAndID(
                target, removeSecurityProxy(current_token).id
            ),
        )
        self.assertEqual(
            expires_soon_token,
            getUtility(IAccessTokenSet).getByTargetAndID(
                target, removeSecurityProxy(expires_soon_token).id
            ),
        )
        self.assertIsNone(
            getUtility(IAccessTokenSet).getByTargetAndID(
                target, removeSecurityProxy(expired_token).id
            )
        )


class TestAccessTokenTargetBase:
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.target = self.makeTarget()
        self.owner = self.target.owner
        self.target_url = api_url(self.target)
        self.webservice = webservice_for_person(
            self.owner, permission=OAuthPermission.WRITE_PRIVATE
        )

    def test_getAccessTokens(self):
        with person_logged_in(self.owner):
            for description in ("Test token 1", "Test token 2"):
                self.factory.makeAccessToken(
                    owner=self.owner,
                    description=description,
                    target=self.target,
                )
        response = self.webservice.named_get(
            self.target_url, "getAccessTokens", api_version="devel"
        )
        self.assertEqual(200, response.status)
        self.assertContentEqual(
            ["Test token 1", "Test token 2"],
            [entry["description"] for entry in response.jsonBody()["entries"]],
        )

    def test_getAccessTokens_excludes_expired(self):
        with person_logged_in(self.owner):
            self.factory.makeAccessToken(
                owner=self.owner, description="Current", target=self.target
            )
            self.factory.makeAccessToken(
                owner=self.owner,
                description="Expired",
                target=self.target,
                date_expires=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        response = self.webservice.named_get(
            self.target_url, "getAccessTokens", api_version="devel"
        )
        self.assertEqual(200, response.status)
        self.assertContentEqual(
            ["Current"],
            [entry["description"] for entry in response.jsonBody()["entries"]],
        )

    def test_getAccessTokens_permissions(self):
        webservice = webservice_for_person(None)
        response = webservice.named_get(
            self.target_url, "getAccessTokens", api_version="devel"
        )
        self.assertEqual(401, response.status)
        self.assertIn(b"launchpad.Edit", response.body)

    def test_getAccessTokens_query_count(self):
        def get_tokens():
            response = self.webservice.named_get(
                self.target_url, "getAccessTokens", api_version="devel"
            )
            self.assertEqual(200, response.status)
            self.assertIn(len(response.jsonBody()["entries"]), {0, 2, 4})

        def create_token():
            with person_logged_in(self.owner):
                self.factory.makeAccessToken(
                    owner=self.owner, target=self.target
                )

        get_tokens()
        recorder1, recorder2 = record_two_runs(get_tokens, create_token, 2)
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))


class TestAccessTokenTargetGitRepository(
    TestAccessTokenTargetBase, TestCaseWithFactory
):
    def makeTarget(self):
        return self.factory.makeGitRepository()
