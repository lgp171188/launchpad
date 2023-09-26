# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test updates to Distroseries stats."""

import os
import subprocess
import unittest
from datetime import timedelta

from storm.expr import Cast, Is, Max, Select
from zope.component import getUtility

from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.distroseries import IDistroSeriesSet
from lp.registry.model.distroseries import DistroSeries
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.statistics.model.statistics import LaunchpadStatistic
from lp.services.worlddata.interfaces.language import ILanguageSet
from lp.services.worlddata.model.language import Language
from lp.testing.dbuser import switch_dbuser
from lp.testing.layers import LaunchpadZopelessLayer
from lp.translations.interfaces.potemplate import IPOTemplateSet
from lp.translations.model.distroserieslanguage import DistroSeriesLanguage


def get_script():
    """Return the path to update-stats.py."""
    script = os.path.join(config.root, "cronscripts", "update-stats.py")
    assert os.path.exists(script), "%s not found" % script
    return script


class UpdateStatsTest(unittest.TestCase):
    """Test the update-stats.py script."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        switch_dbuser("statistician")

    def tearDown(self):
        # Test uses a subprocess, so force the database to be dirty
        self.layer.force_dirty_database()

    def test_basic(self):
        """Test insert and update operations to LaunchpadStatistic."""
        # Nuke some stats so we know that they are updated
        store = IStore(LaunchpadStatistic)

        # Destroy the LaunchpadStatistic entries so we can confirm they are
        # updated.
        ten_weeks_ago = UTC_NOW - Cast(timedelta(weeks=10), "interval")
        store.find(LaunchpadStatistic, name="pofile_count").remove()
        store.find(LaunchpadStatistic).set(value=-1, dateupdated=ten_weeks_ago)

        # Destroy the messagecount caches on distroseries so we can confirm
        # they are all updated.
        store.find(DistroSeries).set(messagecount=-1)

        # Delete half the entries in the DistroSeriesLanguage cache so we
        # can confirm they are created as required, and set the remainders
        # to invalid values so we can confirm they are updated.
        store.find(
            DistroSeriesLanguage,
            DistroSeriesLanguage.id > Select(Max(DistroSeriesLanguage.id) / 2),
        ).remove()
        store.find(DistroSeriesLanguage).set(
            currentcount=-1,
            updatescount=-1,
            rosettacount=-1,
            unreviewed_count=-1,
            contributorcount=-1,
            dateupdated=ten_weeks_ago,
        )

        # Update stats should create missing distroserieslanguage,
        # so remember how many there are before the run.
        num_distroserieslanguage = store.find(DistroSeriesLanguage).count()

        # Commit our changes so the subprocess can see them
        self.layer.txn.commit()

        # Run the update-stats.py script
        cmd = [get_script(), "--quiet"]
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        (stdout, empty_stderr) = process.communicate()

        # Ensure it returned a success code
        self.assertEqual(
            process.returncode,
            0,
            "update-stats.py exited with return code %d. Output was %r"
            % (process.returncode, stdout),
        )
        # With the -q option, it should produce no output if things went
        # well.
        self.assertEqual(
            stdout, "", "update-stats.py was noisy. Emitted:\n%s" % stdout
        )

        # Now confirm it did stuff it is supposed to
        self.layer.txn.abort()

        # Make sure all DistroSeries.messagecount entries are updated
        self.assertEqual(0, store.find(DistroSeries, messagecount=-1).count())

        # Make sure we have created missing DistroSeriesLanguage entries
        self.assertGreater(
            store.find(DistroSeriesLanguage).count(), num_distroserieslanguage
        )

        # Make sure existing DistroSeriesLanguage entries have been updated.
        two_days_ago = UTC_NOW - Cast(timedelta(days=2), "interval")
        for term in (
            DistroSeriesLanguage.currentcount == -1,
            DistroSeriesLanguage.updatescount == -1,
            DistroSeriesLanguage.rosettacount == -1,
            DistroSeriesLanguage.unreviewed_count == -1,
            DistroSeriesLanguage.contributorcount == -1,
            DistroSeriesLanguage.dateupdated < two_days_ago,
        ):
            self.assertEqual(
                0,
                store.find(
                    DistroSeriesLanguage,
                    DistroSeriesLanguage.language == Language.id,
                    Is(Language.visible, True),
                    term,
                ).count(),
            )

        # All LaunchpadStatistic rows should have been updated
        self.assertEqual(0, store.find(LaunchpadStatistic, value=-1).count())
        self.assertEqual(
            0,
            store.find(
                LaunchpadStatistic,
                LaunchpadStatistic.dateupdated < two_days_ago,
            ).count(),
        )

        keys = [
            "potemplate_count",
            "pofile_count",
            "pomsgid_count",
            "translator_count",
            "language_count",
            "bug_count",
            "bugtask_count",
            "people_count",
            "teams_count",
            "rosetta_translator_count",
            "products_with_potemplates",
            "projects_with_bugs",
            "products_using_malone",
            "products_using_rosetta",
            "shared_bug_count",
            "public_specification_count",
            "public_branch_count",
            "public_git_repository_count",
        ]

        for key in keys:
            value = store.find(
                LaunchpadStatistic.value, LaunchpadStatistic.name == key
            ).one()
            self.assertIsNotNone(value, "%s not updated" % key)
            self.assertGreaterEqual(value, 0, "%s is invalid" % key)


class UpdateTranslationStatsTest(unittest.TestCase):
    """Test exceptional update-stats.py rules."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Setup the Distroseries related objects for these tests."""
        self.distribution = getUtility(IDistributionSet)
        self.distroseriesset = getUtility(IDistroSeriesSet)
        self.languageset = getUtility(ILanguageSet)
        self.potemplateset = getUtility(IPOTemplateSet)

    def tearDown(self):
        """Tear down this test and recycle the database."""
        # Test uses a subprocess, so force the database to be dirty
        self.layer.force_dirty_database()

    def test_disabled_template(self):
        """Test that Distroseries stats do not include disabled templates."""
        # First, we check current values of cached statistics.

        # We get some objects we will need for this test.
        ubuntu = self.distribution["ubuntu"]
        hoary = self.distroseriesset.queryByName(ubuntu, "hoary")
        spanish = self.languageset["es"]
        spanish_hoary = hoary.getDistroSeriesLanguage(spanish)
        # We need pmount's template.
        templates = self.potemplateset.getAllByName("pmount")
        pmount_template = None
        for template in templates:
            if template.distroseries == hoary:
                pmount_template = template

        self.assertIsNotNone(pmount_template)

        # Let's calculate the statistics ourselves so we can check that cached
        # values are the right ones.
        messagecount = 0
        currentcount = 0
        for template in hoary.getCurrentTranslationTemplates():
            messagecount += template.messageCount()
            # Get the Spanish IPOFile.
            pofile = template.getPOFileByLang("es")
            if pofile is not None:
                currentcount += pofile.currentCount()
        contributor_count = hoary.getPOFileContributorsByLanguage(
            spanish
        ).count()

        # The amount of messages to translate in Hoary is the expected.
        self.assertEqual(hoary.messagecount, messagecount)

        # And the same for translations and contributors.
        self.assertEqual(spanish_hoary.currentCount(), currentcount)
        # XXX Danilo Segan 2010-08-06: we should not assert that
        # sampledata is correct. Bug #614397.
        # self.assertEqual(spanish_hoary.contributor_count, contributor_count)

        # Let's set 'pmount' template as not current for Hoary.
        pmount_template.iscurrent = False
        # And store its statistics values to validate cached values later.
        pmount_messages = pmount_template.messageCount()
        pmount_spanish_pofile = pmount_template.getPOFileByLang("es")
        pmount_spanish_translated = pmount_spanish_pofile.currentCount()

        # Commit the current transaction because the script will run in
        # another transaction and thus it won't see the changes done on this
        # test unless we commit.
        # XXX CarlosPerelloMarin 2007-01-22 bug=3989:
        # Unnecessary flush_database_updates required.
        from lp.services.database.sqlbase import flush_database_updates

        flush_database_updates()
        import transaction

        transaction.commit()

        # Run update-stats.py script to see that we don't count the
        # information in that template anymore.
        cmd = [get_script(), "--quiet"]
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        (stdout, empty_stderr) = process.communicate()

        # Ensure it returned a success code
        self.assertEqual(
            process.returncode,
            0,
            "update-stats.py exited with return code %d. Output was %r"
            % (process.returncode, stdout),
        )

        # Now confirm it did stuff it is supposed to

        # We flush the caches, so that the above defined objects gets
        # their content from the modified DB.
        from lp.services.database.sqlbase import flush_database_caches

        flush_database_caches()

        # The transaction changed, we need to refetch Storm instances.
        ubuntu = self.distribution["ubuntu"]
        hoary = self.distroseriesset.queryByName(ubuntu, "hoary")
        spanish = self.languageset["es"]
        spanish_hoary = hoary.getDistroSeriesLanguage(spanish)

        # Let's recalculate the statistics ourselved to validate what the
        # script run recalculated.
        new_messagecount = 0
        new_currentcount = 0
        for template in hoary.getCurrentTranslationTemplates():
            new_messagecount += template.messageCount()
            pofile = template.getPOFileByLang("es")
            if pofile is not None:
                new_currentcount += pofile.currentCount()

        new_contributor_count = hoary.getPOFileContributorsByLanguage(
            spanish
        ).count()

        # The amount of messages to translate in Hoary is now lower because we
        # don't count anymore pmount messages.
        self.assertEqual(hoary.messagecount, new_messagecount)
        self.assertFalse(messagecount <= new_messagecount)
        self.assertEqual(messagecount - pmount_messages, new_messagecount)

        # The amount of messages translate into Spanish is also lower now
        # because we don't count Spanish translations for pmount anymore.
        self.assertEqual(spanish_hoary.currentCount(), new_currentcount)
        self.assertFalse(currentcount <= new_currentcount)
        self.assertEqual(
            currentcount - pmount_spanish_translated, new_currentcount
        )

        # Also, there are two Spanish translators that only did contributions
        # to pmount, so they are gone now.
        self.assertEqual(
            spanish_hoary.contributor_count, new_contributor_count
        )
        self.assertFalse(contributor_count <= new_contributor_count)

    def test_english(self):
        """Test that English is handled correctly by DistroSeries.

        English exists in the POFile data, but it cannot be used by Launchpad
        since the messages that are to be translated are stored as English.
        A DistroSeriesLanguage can never be English since it represents a
        translation.
        """
        ubuntu = self.distribution["ubuntu"]
        hoary = self.distroseriesset.queryByName(ubuntu, "hoary")

        # Check that we have English data in the templates.
        moz_templates = self.potemplateset.getAllByName("pkgconf-mozilla")
        moz_template = None
        for template in moz_templates:
            if template.distroseries == hoary:
                moz_template = template
        self.assertIsNotNone(
            moz_template, "The pkgconf-mozilla template for hoary is None."
        )
        moz_english_count = moz_template.getPOFileByLang("en").messageCount()
        self.assertFalse(
            0 == moz_english_count,
            "moz_english_pofile should have messages translated",
        )

        # Run update-stats.py script to see that we don't count the
        # information in the moz_english_pofile template.
        cmd = [get_script(), "--quiet"]
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        (stdout, empty_stderr) = process.communicate()
        self.assertEqual(
            process.returncode,
            0,
            "update-stats.py exited with return code %d. Output was %r"
            % (process.returncode, stdout),
        )

        # Check that we do not have an English DistroSeriesLangauge because
        # of the moz_english_pofile template.
        english = self.languageset["en"]
        english_dsl = hoary.getDistroSeriesLanguage(english)
        self.assertEqual(
            None,
            english_dsl,
            "The English DistroSeriesLangauge must " "not exist.",
        )
