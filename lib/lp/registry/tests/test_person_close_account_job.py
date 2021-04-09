# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `PersonDeactivateJob`."""

__metaclass__ = type

from storm.store import Store
from testtools.matchers import (
    MatchesSetwise,
    MatchesStructure,
    Not,
    StartsWith,
    )
import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.answers.enums import QuestionStatus
from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.archivepublisher.config import getPubConfig
from lp.archivepublisher.publishing import Publisher
from lp.bugs.model.bugsummary import BugSummary
from lp.code.enums import TargetRevisionControlSystems, CodeImportResultStatus
from lp.code.interfaces.codeimportjob import ICodeImportJobWorkflow
from lp.code.tests.helpers import GitHostingFixture
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.persontransferjob import (
    IPersonCloseAccountJobSource,
    )
from lp.registry.interfaces.teammembership import ITeamMembershipSet
from lp.registry.model.persontransferjob import PersonCloseAccountJob
from lp.scripts.garbo import PopulateLatestPersonSourcePackageReleaseCache
from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.features.testing import FeatureFixture
from lp.services.identity.interfaces.account import (
    AccountStatus,
    IAccountSet,
    )
from lp.services.identity.interfaces.emailaddress import IEmailAddressSet
from lp.services.job.interfaces.job import JobStatus, JobType
from lp.services.job.model.job import Job
from lp.services.job.runner import JobRunner
from lp.services.job.tests import block_on_job
from lp.services.log.logger import BufferLogger, DevNullLogger
from lp.services.scripts import log
from lp.services.scripts.base import LaunchpadScriptFailure
from lp.services.verification.interfaces.authtoken import LoginTokenType
from lp.services.verification.interfaces.logintoken import ILoginTokenSet
from lp.soyuz.enums import PackagePublishingStatus, ArchiveSubscriberStatus
from lp.soyuz.model.archive import Archive
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory, login_celebrity
from lp.testing.dbuser import dbuser
from lp.testing.layers import (
    CeleryJobLayer,
    LaunchpadZopelessLayer,
    )
from lp.translations.interfaces.pofiletranslator import IPOFileTranslatorSet
from lp.translations.interfaces.translationsperson import ITranslationsPerson


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

    def test_retains_audit_trail(self):
        person = self.factory.makePerson()
        person_id = person.id
        account_id = person.account.id
        branch_subscription = self.factory.makeBranchSubscription(
            subscribed_by=person)
        snap = self.factory.makeSnap()
        snap_build = self.factory.makeSnapBuild(requester=person, snap=snap)
        specification = self.factory.makeSpecification(drafter=person)
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertEqual(person, branch_subscription.subscribed_by)
        self.assertEqual(person, snap_build.requester)
        self.assertEqual(person, specification.drafter)

    def test_solves_questions_in_non_final_states(self):
        person = self.factory.makePerson()
        person_id = person.id
        account_id = person.account.id
        questions = []
        for status in (
                QuestionStatus.OPEN, QuestionStatus.NEEDSINFO,
                QuestionStatus.ANSWERED):
            question = self.factory.makeQuestion(owner=person)
            question.addComment(person, "comment")
            removeSecurityProxy(question).status = status
            questions.append(question)
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        for question in questions:
            self.assertEqual(QuestionStatus.SOLVED, question.status)
            self.assertEqual(
                'Closed by Launchpad due to owner requesting account removal',
                question.whiteboard)

    def test_skips_questions_in_final_states(self):
        person = self.factory.makePerson()
        person_id = person.id
        account_id = person.account.id
        questions = {}
        for status in (
                QuestionStatus.SOLVED, QuestionStatus.EXPIRED,
                QuestionStatus.INVALID):
            question = self.factory.makeQuestion(owner=person)
            question.addComment(person, "comment")
            removeSecurityProxy(question).status = status
            questions[status] = question
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        for question_status, question in questions.items():
            self.assertEqual(question_status, question.status)
            self.assertIsNone(question.whiteboard)

    def test_handles_packaging_references(self):
        person = self.factory.makePerson()
        person_id = person.id
        account_id = person.account.id
        self.factory.makeGPGKey(person)
        publisher = SoyuzTestPublisher()
        publisher.person = person
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        spph = publisher.getPubSource(
            status=PackagePublishingStatus.PUBLISHED,
            distroseries=ubuntu.currentseries,
            maintainer=person, creator=person)
        with dbuser('garbo_frequently'):
            job = PopulateLatestPersonSourcePackageReleaseCache(
                DevNullLogger())
            while not job.isDone():
                job(chunk_size=100)
        self.assertTrue(person.hasMaintainedPackages())
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertEqual(person, spph.package_maintainer)
        self.assertEqual(person, spph.package_creator)
        self.assertFalse(person.hasMaintainedPackages())

    def test_skips_reported_bugs(self):
        person = self.factory.makePerson()
        bug = self.factory.makeBug(owner=person)
        bugtask = self.factory.makeBugTask(bug=bug, owner=person)
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertEqual(person, bug.owner)
        self.assertEqual(person, bugtask.owner)

    def test_handles_bug_affects_person(self):
        person = self.factory.makePerson()
        bug = self.factory.makeBug()
        bug.markUserAffected(person)
        self.assertTrue(bug.isUserAffected(person))
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertFalse(bug.isUserAffected(person))

    def test_skips_translation_relicensing_agreements(self):
        person = self.factory.makePerson()
        translations_person = ITranslationsPerson(person)
        translations_person.translations_relicensing_agreement = True
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertTrue(translations_person.translations_relicensing_agreement)

    def test_skips_po_file_translators(self):
        person = self.factory.makePerson()
        pofile = self.factory.makePOFile()
        potmsgset = self.factory.makePOTMsgSet(pofile.potemplate)
        self.factory.makeCurrentTranslationMessage(
            potmsgset=potmsgset, translator=person, language=pofile.language)
        self.assertIsNotNone(
            getUtility(IPOFileTranslatorSet).getForPersonPOFile(
                person, pofile))
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertIsNotNone(
            getUtility(IPOFileTranslatorSet).getForPersonPOFile(
                person, pofile))

    def test_handles_archive_subscriptions_and_tokens(self):
        person = self.factory.makePerson()
        ppa = self.factory.makeArchive(private=True)
        subscription = ppa.newSubscription(person, ppa.owner)
        other_subscription = ppa.newSubscription(
            self.factory.makePerson(), ppa.owner)
        ppa.newAuthToken(person)
        self.assertEqual(ArchiveSubscriberStatus.CURRENT, subscription.status)
        self.assertIsNotNone(ppa.getAuthToken(person))
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            now = get_transaction_timestamp(Store.of(person))
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertEqual(
            ArchiveSubscriberStatus.CANCELLED, subscription.status)
        self.assertEqual(now, subscription.date_cancelled)
        self.assertEqual(
            ArchiveSubscriberStatus.CURRENT, other_subscription.status)
        self.assertIsNotNone(ppa.getAuthToken(person))

    def test_handles_hardware_submissions(self):
        # Launchpad used to support hardware submissions.  This is in the
        # process of being removed after a long period of relative disuse,
        # but close-account still needs to cope with old accounts that have
        # them, so we resort to raw SQL to set things up.
        person = self.factory.makePerson()
        store = Store.of(person)
        date_created = get_transaction_timestamp(store)
        keys = [
            self.factory.getUniqueUnicode('submission-key') for _ in range(2)]
        raw_submissions = [
            self.factory.makeLibraryFileAlias(db_only=True) for _ in range(2)]
        systems = [
            self.factory.getUniqueUnicode('system-fingerprint')
            for _ in range(2)]
        system_fingerprint_ids = [
            row[0] for row in store.execute("""
                INSERT INTO HWSystemFingerprint (fingerprint)
                VALUES (?), (?)
                RETURNING id
                """, systems)]
        submission_ids = [
            row[0] for row in store.execute("""
                INSERT INTO HWSubmission
                    (date_created, format, private, contactable,
                     submission_key, owner, raw_submission,
                     system_fingerprint)
                VALUES
                    (?, 1, FALSE, FALSE, ?, ?, ?, ?),
                    (?, 1, FALSE, FALSE, ?, ?, ?, ?)
                RETURNING id
                """,
                (date_created, keys[0], person.id,
                 raw_submissions[0].id, system_fingerprint_ids[0],
                 date_created, keys[1], self.factory.makePerson().id,
                 raw_submissions[1].id, system_fingerprint_ids[1]))]
        with dbuser('hwdb-submission-processor'):
            vendor_name_id = store.execute("""
                INSERT INTO HWVendorName (name) VALUES (?) RETURNING id
                """, (self.factory.getUniqueUnicode(),)).get_one()[0]
            vendor_id = store.execute("""
                INSERT INTO HWVendorID (bus, vendor_id_for_bus, vendor_name)
                VALUES (1, '0x0001', ?)
                RETURNING id
                """, (vendor_name_id,)).get_one()[0]
            device_id = store.execute("""
                INSERT INTO HWDevice
                    (bus_vendor_id, bus_product_id, variant, name, submissions)
                VALUES (?, '0x0002', NULL, ?, 1)
                RETURNING id
                """, (vendor_id, self.factory.getUniqueUnicode())).get_one()[0]
            device_driver_link_id = store.execute("""
                INSERT INTO HWDeviceDriverLink (device, driver)
                VALUES (?, NULL)
                RETURNING id
                """, (device_id,)).get_one()[0]
            parent_submission_device_id = store.execute("""
                INSERT INTO HWSubmissionDevice
                    (device_driver_link, submission, parent, hal_device_id)
                VALUES (?, ?, NULL, 1)
                RETURNING id
                """,
                (device_driver_link_id, submission_ids[0])).get_one()[0]
            store.execute("""
                INSERT INTO HWSubmissionDevice
                    (device_driver_link, submission, parent, hal_device_id)
                VALUES (?, ?, ?, 2)
                """,
                (device_driver_link_id, submission_ids[0],
                 parent_submission_device_id))
            other_submission_device_id = store.execute("""
                INSERT INTO HWSubmissionDevice
                    (device_driver_link, submission, hal_device_id)
                VALUES (?, ?, 1)
                RETURNING id
                """,
                (device_driver_link_id, submission_ids[1])).get_one()[0]

        def get_submissions_by_owner(person):
            return [
                row[0] for row in store.execute("""
                    SELECT HWSubmission.id
                    FROM HWSubmission, HWSystemFingerprint
                    WHERE
                        HWSubmission.owner = ?
                        AND HWSystemFingerprint.id =
                            HWSubmission.system_fingerprint
                    """, (person.id,))]

        def get_submission_by_submission_key(submission_key):
            result = store.execute("""
                SELECT id FROM HWSubmission WHERE submission_key = ?
                """, (submission_key,))
            row = result.get_one()
            self.assertIsNone(result.get_one())
            return row[0] if row else None

        def get_devices_by_submission(submission_id):
            return [
                row[0] for row in store.execute("""
                    SELECT id FROM HWSubmissionDevice WHERE submission = ?
                    """, (submission_id,))]

        self.assertNotEqual([], get_submissions_by_owner(person))
        self.assertEqual(
            submission_ids[0], get_submission_by_submission_key(keys[0]))
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertEqual([], get_submissions_by_owner(person))
        self.assertIsNone(get_submission_by_submission_key(keys[0]))
        self.assertEqual(
            submission_ids[1], get_submission_by_submission_key(keys[1]))
        self.assertEqual(
            [other_submission_device_id],
            get_devices_by_submission(submission_ids[1]))

    def test_skips_bug_summary(self):
        person = self.factory.makePerson()
        other_person = self.factory.makePerson()
        bug = self.factory.makeBug(information_type=InformationType.USERDATA)
        bug.subscribe(person, bug.owner)
        bug.subscribe(other_person, bug.owner)
        store = Store.of(bug)
        summaries = list(store.find(
            BugSummary,
            BugSummary.viewed_by_id.is_in([person.id, other_person.id])))
        self.assertThat(summaries, MatchesSetwise(
            MatchesStructure.byEquality(count=1, viewed_by=person),
            MatchesStructure.byEquality(count=1, viewed_by=other_person)))
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        # BugSummaryJournal has been updated, but BugSummary hasn't yet.
        summaries = list(store.find(
            BugSummary,
            BugSummary.viewed_by_id.is_in([person.id, other_person.id])))
        self.assertThat(summaries, MatchesSetwise(
            MatchesStructure.byEquality(count=1, viewed_by=person),
            MatchesStructure.byEquality(count=1, viewed_by=other_person),
            MatchesStructure.byEquality(count=-1, viewed_by=person)))
        # If we force an update (the equivalent of the
        # BugSummaryJournalRollup garbo job), that's enough to get rid of
        # the reference.
        store.execute('SELECT bugsummary_rollup_journal()')
        summaries = list(store.find(
            BugSummary,
            BugSummary.viewed_by_id.is_in([person.id, other_person.id])))
        self.assertThat(summaries, MatchesSetwise(
            MatchesStructure.byEquality(viewed_by=other_person)))

    def test_skips_inactive_product_owner(self):
        person = self.factory.makePerson()
        product = self.factory.makeProduct(owner=person)
        product.active = False
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertEqual(person, product.owner)

    def test_skips_bug_nomination(self):
        person = self.factory.makePerson()
        other_person = self.factory.makePerson()
        bug = self.factory.makeBug()
        targets = [self.factory.makeProductSeries() for _ in range(2)]
        self.factory.makeBugTask(bug=bug, target=targets[0].parent)
        bug.addNomination(person, targets[0])
        self.factory.makeBugTask(bug=bug, target=targets[1].parent)
        bug.addNomination(other_person, targets[1])
        self.assertThat(bug.getNominations(), MatchesSetwise(
            MatchesStructure.byEquality(owner=person),
            MatchesStructure.byEquality(owner=other_person)))
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertThat(bug.getNominations(), MatchesSetwise(
            MatchesStructure.byEquality(owner=person),
            MatchesStructure.byEquality(owner=other_person)))

    def test_skips_code_import(self):
        self.useFixture(GitHostingFixture())
        person = self.factory.makePerson()
        team = self.factory.makeTeam(members=[person])
        code_imports = [
            self.factory.makeCodeImport(
                registrant=person, target_rcs_type=target_rcs_type, owner=team)
            for target_rcs_type in (
                TargetRevisionControlSystems.BZR,
                TargetRevisionControlSystems.GIT)]
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger),\
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertEqual(person, code_imports[0].registrant)
        self.assertEqual(person, code_imports[1].registrant)

    def test_skips_import_job_requester(self):
        self.useFixture(GitHostingFixture())
        person = self.factory.makePerson()
        team = self.factory.makeTeam(members=[person])
        code_imports = [
            self.factory.makeCodeImport(
                registrant=person, target_rcs_type=target_rcs_type, owner=team)
            for target_rcs_type in (
                TargetRevisionControlSystems.BZR,
                TargetRevisionControlSystems.GIT)]

        for code_import in code_imports:
            getUtility(ICodeImportJobWorkflow).requestJob(
                code_import.import_job, person)
            self.assertEqual(person, code_import.import_job.requesting_user)
            result = self.factory.makeCodeImportResult(
                code_import=code_import,
                requesting_user=person,
                result_status=CodeImportResultStatus.SUCCESS)
            person_id = person.id
            account_id = person.account.id
            job = PersonCloseAccountJob.create(person.name)
            logger = BufferLogger()
            with log.use(logger), \
                    dbuser(config.IPersonCloseAccountJobSource.dbuser):
                job.run()
            self.assertAccountRemoved(account_id, person_id)
            self.assertEqual(person, code_import.registrant)
            self.assertEqual(person, result.requesting_user)
            self.assertEqual(person, code_import.import_job.requesting_user)

    def test_skip_requester_package_diff_job(self):
        person = self.factory.makePerson()
        ppa = self.factory.makeArchive(owner=person)
        other_person = self.factory.makePerson()
        from_spr = self.factory.makeSourcePackageRelease(archive=ppa)
        to_spr = self.factory.makeSourcePackageRelease(archive=ppa)
        from_spr.requestDiffTo(ppa.owner, to_spr)
        job = IStore(Job).find(
            Job, Job.base_job_type == JobType.GENERATE_PACKAGE_DIFF).order_by(
                Job.id).last()
        # XXX ilasc 2021-02-23: deleting the ppa in this test by running the
        # Publisher here results in the "Can't delete non-trivial PPAs
        # for user" exception. So we just point to another owner here
        # to simulate ppa owner removal during deletion. The deletion was
        # successfully performed on the account removal that triggered addition
        # of skipping the requester on job in dogfood so we need to come back
        # and fix this test setup as deletion at this point should work.
        removeSecurityProxy(ppa).owner = other_person
        person_id = person.id
        account_id = person.account.id
        closeAccountjob = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger), \
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            closeAccountjob.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertEqual(person, job.requester)

    def test_skips_specification_owner(self):
        person = self.factory.makePerson()
        person_id = person.id
        account_id = person.account.id
        specification = self.factory.makeSpecification(owner=person)
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger), \
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertEqual(person, specification.owner)

    def test_skips_teammembership_last_changed_by(self):
        targetteam = self.factory.makeTeam(name='target')
        member = self.factory.makePerson()
        login_celebrity('admin')
        targetteam.addMember(member, targetteam.teamowner)
        membershipset = getUtility(ITeamMembershipSet)
        membershipset.deactivateActiveMemberships(
            targetteam, comment='test', reviewer=member)
        membership = membershipset.getByPersonAndTeam(member, targetteam)
        self.assertEqual(member, membership.last_changed_by)

        person_id = member.id
        account_id = member.account.id
        job = PersonCloseAccountJob.create(member.name)
        logger = BufferLogger()
        with log.use(logger), \
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)

    def test_skips_teamowner_merged(self):
        person = self.factory.makePerson()
        merged_person = self.factory.makePerson()
        owned_team1 = self.factory.makeTeam(name='target', owner=person)
        removeSecurityProxy(owned_team1).merged = merged_person
        owned_team2 = self.factory.makeTeam(name='target2', owner=person)
        person_id = person.id
        account_id = person.account.id

        # Closing account fails as the user still owns team2
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger), \
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
            # self.assertRaises(
            #     LaunchpadScriptFailure, job.run)
        self.assertNotRemoved(account_id, person_id)

        # Account will now close as the user doesn't own
        # any other teams at this point
        removeSecurityProxy(owned_team2).merged = merged_person
        with log.use(logger), \
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

    def test_handles_oauth_request_token(self):
        person = self.factory.makePerson()
        other_person = self.factory.makePerson()
        request_token = self.factory.makeOAuthRequestToken(reviewed_by=person)
        other_request_token = self.factory.makeOAuthRequestToken(
            reviewed_by=other_person)
        self.assertContentEqual([request_token], person.oauth_request_tokens)
        self.assertContentEqual(
            [other_request_token], other_person.oauth_request_tokens)
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger), \
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertContentEqual([], person.oauth_request_tokens)
        self.assertContentEqual(
            [other_request_token], other_person.oauth_request_tokens)

    def test_handles_oauth_access_token(self):
        person = self.factory.makePerson()
        other_person = self.factory.makePerson()
        access_token, _ = self.factory.makeOAuthAccessToken(owner=person)
        other_access_token, _ = self.factory.makeOAuthAccessToken(
            owner=other_person)
        self.assertContentEqual([access_token], person.oauth_access_tokens)
        self.assertContentEqual(
            [other_access_token], other_person.oauth_access_tokens)
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        with dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertContentEqual([], person.oauth_access_tokens)
        self.assertContentEqual(
            [other_access_token], other_person.oauth_access_tokens)

    def test_fails_on_undeleted_ppa(self):
        person = self.factory.makePerson()
        ppa = self.factory.makeArchive(owner=person)
        procs = [self.factory.makeProcessor() for _ in range(2)]
        ppa.setProcessors(procs)
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger), \
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        error_message = (
            {u'ERROR User %s is still referenced by 1 '
             u'archive.owner values' % person.name,
             u'ERROR PersonCloseAccountJob User %s is still referenced'
             % person.name
             })
        self.assertTrue(
            error_message.issubset(logger.getLogBuffer().splitlines()))
        self.assertNotRemoved(account_id, person_id)

    def test_fails_on_deleted_ppa_with_builds(self):
        # XXX cjwatson 2019-08-09: A PPA that has ever had builds can't
        # currently be purged.  It's not clear what to do about this case.
        person = self.factory.makePerson()
        ppa = self.factory.makeArchive(owner=person)
        self.factory.makeBinaryPackageBuild(archive=ppa)
        ppa.delete(person)
        Publisher(
            DevNullLogger(), getPubConfig(ppa), None, ppa).deleteArchive()
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger), \
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        error_message = (
            {u"ERROR PersonCloseAccountJob Can\'t delete non-trivial "
             u"PPAs for user %s" % person.name})
        self.assertTrue(
            error_message.issubset(logger.getLogBuffer().splitlines()))
        self.assertNotRemoved(account_id, person_id)

    def test_handles_empty_deleted_ppa(self):
        person = self.factory.makePerson()
        ppa = self.factory.makeArchive(owner=person)
        ppa_id = ppa.id
        other_ppa = self.factory.makeArchive()
        other_ppa_id = other_ppa.id
        procs = [self.factory.makeProcessor() for _ in range(2)]
        ppa.setProcessors(procs)
        ppa.delete(person)
        Publisher(
            DevNullLogger(), getPubConfig(ppa), None, ppa).deleteArchive()
        store = Store.of(ppa)
        person_id = person.id
        account_id = person.account.id
        job = PersonCloseAccountJob.create(person.name)
        logger = BufferLogger()
        with log.use(logger), \
                dbuser(config.IPersonCloseAccountJobSource.dbuser):
            job.run()
        self.assertAccountRemoved(account_id, person_id)
        self.assertIsNone(store.get(Archive, ppa_id))
        self.assertEqual(other_ppa, store.get(Archive, other_ppa_id))

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
