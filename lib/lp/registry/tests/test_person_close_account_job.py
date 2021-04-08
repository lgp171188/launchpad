# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `PersonDeactivateJob`."""

__metaclass__ = type

from testtools.matchers import (
    Not,
    StartsWith,
    )
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.persontransferjob import (
    IPersonCloseAccountJobSource,
    )
from lp.registry.model.persontransferjob import PersonCloseAccountJob
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.identity.interfaces.account import (
    AccountStatus,
    IAccountSet,
    )
from lp.services.identity.interfaces.emailaddress import IEmailAddressSet
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.job.tests import block_on_job
from lp.services.log.logger import BufferLogger
from lp.services.scripts import log
from lp.services.verification.interfaces.authtoken import LoginTokenType
from lp.services.verification.interfaces.logintoken import ILoginTokenSet
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.layers import (
    CeleryJobLayer,
    LaunchpadZopelessLayer,
    )


class TestPersonCloseAccountJob(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_close_account_job_nonexistent_username_email(self):
        self.assertRaisesWithContent(
            TypeError,
            "User nonexistent_username does not exist",
            getUtility(IPersonCloseAccountJobSource).create,
            u'nonexistent_username')

        self.assertRaisesWithContent(
            TypeError,
            "User nonexistent_email@username.test does not exist",
            getUtility(IPersonCloseAccountJobSource).create,
            u'nonexistent_email@username.test')

    def test_close_account_job_valid_username(self):
        user_to_delete = self.factory.makePerson(name=u'delete-me')
        job_source = getUtility(IPersonCloseAccountJobSource)
        jobs = list(job_source.iterReady())

        # at this point we have no jobs
        self.assertEqual([], jobs)

        getUtility(IPersonCloseAccountJobSource).create(u'delete-me')
        jobs = list(job_source.iterReady())
        jobs[0] = removeSecurityProxy(jobs[0])
        with dbuser(config.IPersonCloseAccountJobSource.dbuser):
            JobRunner(jobs).runAll()

        self.assertEqual(JobStatus.COMPLETED, jobs[0].status)
        person = removeSecurityProxy(
            getUtility(IPersonSet).getByName(user_to_delete.name))
        self.assertEqual(person.name, u'removed%d' % user_to_delete.id)

    def test_close_account_job_valid_email(self):
        user_to_delete = self.factory.makePerson(
            email=u'delete-me@example.com')
        getUtility(
            IPersonCloseAccountJobSource).create(u'delete-me@example.com')
        self.assertJobCompletes()

        person = removeSecurityProxy(
            getUtility(IPersonSet).getByName(user_to_delete.name))
        self.assertEqual(person.name, u'removed%d' % user_to_delete.id)

    def test_team(self):
        team = self.factory.makeTeam()
        self.assertRaisesWithContent(
            TypeError,
            "%s is a team" % team.name,
            getUtility(IPersonCloseAccountJobSource).create,
            team.name)

    def test_unhandled_reference(self):
        user_to_delete = self.factory.makePerson(name=u'delete-me')
        self.factory.makeProduct(owner=user_to_delete)
        person = removeSecurityProxy(
            getUtility(IPersonSet).getByName(user_to_delete.name))
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(u'delete-me')
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        error_message = (
            {u'ERROR User delete-me is still '
             u'referenced by 1 product.owner values',
             u'ERROR User delete-me is still '
             u'referenced by 1 productseries.owner values',
             u'ERROR PersonCloseAccountJob User delete-me is still referenced'
             })
        self.assertTrue(
            error_message.issubset(logger.getLogBuffer().splitlines()))

        self.assertNotRemoved(account_id, person_id)

    def test_unactivated(self):
        person = self.factory.makePerson(
            account_status=AccountStatus.NOACCOUNT)
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.guessedemails[0].email)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()

        self.assertAccountRemoved(account_id, person_id)

    def test_handles_login_token(self):
        person = self.factory.makePerson(name=u'delete-me')
        email = '%s@another-domain.test' % person.name
        login_token_set = getUtility(ILoginTokenSet)
        token = login_token_set.new(
            person, person.preferredemail.email, email,
            LoginTokenType.VALIDATEEMAIL)
        plaintext_token = token.token
        self.assertEqual(token, login_token_set[plaintext_token])
        person_id = person.id
        account_id = person.account.id
        getUtility(
            IPersonCloseAccountJobSource).create(u'delete-me')
        self.assertJobCompletes()
        self.assertAccountRemoved(account_id, person_id)
        self.assertRaises(
            KeyError, login_token_set.__getitem__, plaintext_token)

    def assertJobCompletes(self):
        job_source = getUtility(IPersonCloseAccountJobSource)
        jobs = list(job_source.iterReady())
        jobs[0] = removeSecurityProxy(jobs[0])
        with dbuser(config.IPersonCloseAccountJobSource.dbuser):
            JobRunner(jobs).runAll()
        self.assertEqual(JobStatus.COMPLETED, jobs[0].status)

    def assertAccountRemoved(self, account_id, person_id):
        # The Account row still exists, but has been anonymised, leaving
        # only a minimal audit trail.
        account = getUtility(IAccountSet).get(account_id)
        self.assertEqual('Removed by request', account.displayname)
        self.assertEqual(AccountStatus.CLOSED, account.status)
        self.assertIn('Closed using close-account.', account.status_history)

        # The Person row still exists to maintain links with information
        # that won't be removed, such as bug comments, but has been
        # anonymised.
        person = getUtility(IPersonSet).get(person_id)
        self.assertThat(person.name, StartsWith('removed'))
        self.assertEqual('Removed by request', person.display_name)
        self.assertEqual(account, person.account)

        # The corresponding PersonSettings row has been reset to the
        # defaults.
        self.assertFalse(person.selfgenerated_bugnotifications)
        self.assertFalse(person.expanded_notification_footers)
        self.assertFalse(person.require_strong_email_authentication)

        # EmailAddress and OpenIdIdentifier rows have been removed.
        self.assertEqual(
            [], list(getUtility(IEmailAddressSet).getByPerson(person)))
        self.assertEqual([], list(account.openid_identifiers))

    def assertNotRemoved(self, account_id, person_id):
        account = getUtility(IAccountSet).get(account_id)
        self.assertNotEqual('Removed by request', account.displayname)
        self.assertEqual(AccountStatus.ACTIVE, account.status)
        person = getUtility(IPersonSet).get(person_id)
        self.assertEqual(account, person.account)
        self.assertNotEqual('Removed by request', person.display_name)
        self.assertThat(person.name, Not(StartsWith('removed')))
        self.assertNotEqual(
            [], list(getUtility(IEmailAddressSet).getByPerson(person)))
        self.assertNotEqual([], list(account.openid_identifiers))


class TestPersonCloseAccountJobViaCelery(TestCaseWithFactory):

    layer = CeleryJobLayer

    def test_PersonCloseAccountJob(self):
        """PersonCloseAccountJob runs under Celery."""
        self.useFixture(FeatureFixture(
            {'jobs.celery.enabled_classes':
             'PersonCloseAccountJob'}))
        user_to_delete = self.factory.makePerson(name=u'delete-me')

        with block_on_job():
            job = PersonCloseAccountJob.create(u'delete-me')
            transaction.commit()
        person = removeSecurityProxy(
            getUtility(IPersonSet).getByName(user_to_delete.name))
        self.assertEqual(person.name, u'removed%d' % user_to_delete.id)
        self.assertEqual(JobStatus.COMPLETED, job.status)
