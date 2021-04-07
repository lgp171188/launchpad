# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the WSGI archive authorisation provider."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

import crypt
import os.path
import subprocess
import time

from fixtures import MonkeyPatch
import transaction

from lp.services.config import config
from lp.services.memcache.testing import MemcacheFixture
from lp.soyuz.wsgi import archiveauth
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessAppServerLayer
from lp.xmlrpc import faults


class TestWSGIArchiveAuth(TestCaseWithFactory):

    layer = ZopelessAppServerLayer

    def setUp(self):
        super(TestWSGIArchiveAuth, self).setUp()
        self.now = time.time()
        self.useFixture(MonkeyPatch("time.time", lambda: self.now))
        self.memcache_fixture = self.useFixture(MemcacheFixture())
        # The WSGI provider doesn't use Zope, so we can't rely on the
        # fixture substituting a Zope utility.
        self.useFixture(MonkeyPatch(
            "lp.soyuz.wsgi.archiveauth._memcache_client",
            self.memcache_fixture))

    def test_get_archive_reference_short_url(self):
        self.assertIsNone(archiveauth._get_archive_reference(
            {"SCRIPT_NAME": "/foo"}))

    def test_get_archive_reference_archive_base(self):
        self.assertEqual(
            "~user/ubuntu/ppa",
            archiveauth._get_archive_reference(
                {"SCRIPT_NAME": "/user/ppa/ubuntu"}))

    def test_get_archive_reference_inside_archive(self):
        self.assertEqual(
            "~user/ubuntu/ppa",
            archiveauth._get_archive_reference(
                {"SCRIPT_NAME": "/user/ppa/ubuntu/dists"}))

    def test_check_password_short_url(self):
        self.assertIsNone(archiveauth.check_password(
            {"SCRIPT_NAME": "/foo"}, "user", ""))
        self.assertEqual({}, self.memcache_fixture._cache)

    def test_check_password_not_found(self):
        self.assertIsNone(archiveauth.check_password(
            {"SCRIPT_NAME": "/nonexistent/bad/unknown"}, "user", ""))
        self.assertEqual({}, self.memcache_fixture._cache)

    def test_crypt_sha256(self):
        crypted_password = archiveauth._crypt_sha256("secret")
        self.assertEqual(
            crypted_password, crypt.crypt("secret", crypted_password))

    def makeArchiveAndToken(self):
        archive = self.factory.makeArchive(private=True)
        archive_path = "/%s/%s/ubuntu" % (archive.owner.name, archive.name)
        subscriber = self.factory.makePerson()
        archive.newSubscription(subscriber, archive.owner)
        token = archive.newAuthToken(subscriber)
        transaction.commit()
        return archive, archive_path, subscriber.name, token.token

    def test_check_password_unauthorized(self):
        _, archive_path, username, password = self.makeArchiveAndToken()
        # Test that this returns False, not merely something falsy (e.g.
        # None).
        self.assertIs(
            False,
            archiveauth.check_password(
                {"SCRIPT_NAME": archive_path}, username, password + "-bad"))
        self.assertEqual({}, self.memcache_fixture._cache)

    def test_check_password_success(self):
        archive, archive_path, username, password = self.makeArchiveAndToken()
        self.assertIs(
            True,
            archiveauth.check_password(
                {"SCRIPT_NAME": archive_path}, username, password))
        crypted_password = self.memcache_fixture.get(
            "archive-auth:%s:%s" % (archive.reference, username))
        self.assertEqual(
            crypted_password, crypt.crypt(password, crypted_password))

    def test_check_password_considers_cache(self):
        class FakeProxy:
            def __init__(self, uri):
                pass

            def checkArchiveAuthToken(self, archive_reference, username,
                                      password):
                raise faults.Unauthorized()

        _, archive_path, username, password = self.makeArchiveAndToken()
        self.assertIs(
            True,
            archiveauth.check_password(
                {"SCRIPT_NAME": archive_path}, username, password))
        self.useFixture(
            MonkeyPatch("lp.soyuz.wsgi.archiveauth.ServerProxy", FakeProxy))
        # A subsequent check honours the cache.
        self.assertIs(
            False,
            archiveauth.check_password(
                {"SCRIPT_NAME": archive_path}, username, password + "-bad"))
        self.assertIs(
            True,
            archiveauth.check_password(
                {"SCRIPT_NAME": archive_path}, username, password))
        # If we advance time far enough, then the cached result expires.
        self.now += 60
        self.assertIs(
            False,
            archiveauth.check_password(
                {"SCRIPT_NAME": archive_path}, username, password))

    def test_script(self):
        _, archive_path, username, password = self.makeArchiveAndToken()
        script_path = os.path.join(
            config.root, "scripts", "wsgi-archive-auth.py")

        def check_via_script(archive_path, username, password):
            with open(os.devnull, "w") as devnull:
                return subprocess.call(
                    [script_path, archive_path, username, password],
                    stderr=devnull)

        self.assertEqual(0, check_via_script(archive_path, username, password))
        self.assertEqual(
            1, check_via_script(archive_path, username, password + "-bad"))
        self.assertEqual(
            2, check_via_script("/nonexistent/bad/unknown", "user", ""))
