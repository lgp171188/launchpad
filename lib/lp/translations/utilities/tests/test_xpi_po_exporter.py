# Copyright 2009-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from textwrap import dedent

import transaction
from fixtures import MonkeyPatch
from zope.component import getAdapter, getUtility
from zope.interface import implementer
from zope.interface.verify import verifyObject
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.product import IProductSet
from lp.testing import TestCase
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import LaunchpadZopelessLayer
from lp.translations.enums import RosettaImportStatus
from lp.translations.interfaces.potemplate import IPOTemplateSet
from lp.translations.interfaces.translationcommonformat import (
    ITranslationFileData,
)
from lp.translations.interfaces.translationexporter import (
    ITranslationFormatExporter,
)
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat,
)
from lp.translations.interfaces.translationimporter import (
    ITranslationFormatImporter,
    ITranslationImporter,
)
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue,
)
from lp.translations.interfaces.translations import TranslationConstants
from lp.translations.utilities.translation_common_format import (
    TranslationFileData,
    TranslationMessageData,
)
from lp.translations.utilities.translation_export import ExportFileStorage
from lp.translations.utilities.xpi_header import XpiHeader
from lp.translations.utilities.xpi_po_exporter import XPIPOExporter

# Hardcoded representations of what used to be found in
# lib/lp/translations/utilities/tests/firefox-data/.  We no longer have real
# XPI import code, so we pre-parse the messages.
test_xpi_header = dedent(
    """\
    <?xml version="1.0"?>
    <RDF xmlns="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:em="http://www.mozilla.org/2004/em-rdf#">
      <Description about="urn:mozilla:install-manifest"
                   em:id="langpack-en-US@firefox.mozilla.org"
                   em:name="English U.S. (en-US) Language Pack"
                   em:version="2.0"
                   em:type="8"
                   em:creator="Danilo Šegan">
        <em:contributor>Данило Шеган</em:contributor>
        <em:contributor>Carlos Perelló Marín &lt;carlos@canonical.com&gt;</em:contributor>

        <em:targetApplication>
          <Description>
            <em:id>{ec8030f7-c20a-464f-9b0e-13a3a9e97384}</em:id><!-- firefox -->
            <em:minVersion>2.0</em:minVersion>
            <em:maxVersion>2.0.0.*</em:maxVersion>
          </Description>
        </em:targetApplication>
      </Description>
    </RDF>
"""  # noqa: E501
)
test_xpi_messages = [
    (
        "foozilla.menu.title",
        "main/subdir/test2.dtd",
        "jar:chrome/en-US.jar!/subdir/test2.dtd",
        "MENU",
        " This is a DTD file inside a subdirectory\n",
    ),
    (
        "foozilla.menu.accesskey",
        "main/subdir/test2.dtd",
        "jar:chrome/en-US.jar!/subdir/test2.dtd",
        "M",
        dedent(
            """\
        Select the access key that you want to use. These have
        to be translated in a way that the selected character is
        present in the translated string of the label being
        referred to, for example 'i' in 'Edit' menu item in
        English. If a translation already exists, please don't
        change it if you are not sure about it. Please find the
        context of the key from the end of the 'Located in' text
        below.
        """
        ),
    ),
    (
        "foozilla.menu.commandkey",
        "main/subdir/test2.dtd",
        "jar:chrome/en-US.jar!/subdir/test2.dtd",
        "m",
        dedent(
            """\
        Select the shortcut key that you want to use. It
        should be translated, but often shortcut keys (for
        example Ctrl + KEY) are not changed from the original. If
        a translation already exists, please don't change it if
        you are not sure about it. Please find the context of
        the key from the end of the 'Located in' text below.
        """
        ),
    ),
    (
        "foozilla_something",
        "main/subdir/test2.properties",
        "jar:chrome/en-US.jar!/subdir/test2.properties:6",
        "SomeZilla",
        dedent(
            """\
        Translators, what you are seeing now is a lovely,
        awesome, multiline comment aimed at you directly
        from the streets of a .properties file
        """
        ),
    ),
    (
        "foozilla.name",
        "main/test1.dtd",
        "jar:chrome/en-US.jar!/test1.dtd",
        "FooZilla!",
        None,
    ),
    (
        "foozilla.play.fire",
        "main/test1.dtd",
        "jar:chrome/en-US.jar!/test1.dtd",
        "Do you want to play with fire?",
        " Translators, don't play with fire!\n",
    ),
    (
        "foozilla.play.ice",
        "main/test1.dtd",
        "jar:chrome/en-US.jar!/test1.dtd",
        "Play with ice?",
        " This is just a comment, not a comment for translators\n",
    ),
    (
        "foozilla.title",
        "main/test1.properties",
        "jar:chrome/en-US.jar!/test1.properties:1",
        "FooZilla Zilla Thingy",
        None,
    ),
    (
        "foozilla.happytitle",
        "main/test1.properties",
        "jar:chrome/en-US.jar!/test1.properties:3",
        "http://foozillingy.happy.net/",
        "Translators, if you're older than six, don't translate this\n",
    ),
    (
        "foozilla.nocomment",
        "main/test1.properties",
        "jar:chrome/en-US.jar!/test1.properties:4",
        "No Comment",
        "(Except this one)\n",
    ),
    (
        "foozilla.utf8",
        "main/test1.properties",
        "jar:chrome/en-US.jar!/test1.properties:5",
        "\u0414\u0430\u043d=Day",
        None,
    ),
]


class FakeXPIMessage(TranslationMessageData):
    """Simulate an XPI translation message."""

    def __init__(self, key, chrome_path, file_and_line, value, last_comment):
        super().__init__()
        self.msgid_singular = key
        self.context = chrome_path
        self.file_references = "%s(%s)" % (file_and_line, key)
        value = value.strip()
        self.addTranslation(TranslationConstants.SINGULAR_FORM, value)
        self.singular_text = value
        self.source_comment = last_comment


@implementer(ITranslationFormatImporter)
class FakeXPIImporter:
    """Simulate an XPI import.  We no longer have real XPI import code."""

    def getFormat(self, file_contents):
        """See `ITranslationFormatImporter`."""
        return TranslationFileFormat.XPI

    priority = 0
    content_type = "application/zip"
    file_extensions = [".xpi"]
    template_suffix = "en-US.xpi"
    uses_source_string_msgids = True

    def parse(self, translation_import_queue_entry):
        """See `ITranslationFormatImporter`.

        This takes a `TranslationImportQueueEntry` to satisfy the interface,
        but ignores it and returns hardcoded data instead.
        """
        translation_file = TranslationFileData()
        translation_file.header = XpiHeader(test_xpi_header)
        translation_file.messages = [
            FakeXPIMessage(*message) for message in test_xpi_messages
        ]
        return translation_file

    def getHeaderFromString(self, header_string):
        """See `ITranslationFormatImporter`.

        This takes a header string to satisfy the interface, but ignores it
        and returns hardcoded data instead.
        """
        return XpiHeader(test_xpi_header)


class XPIPOExporterTestCase(TestCase):
    """Class test for gettext's .po file exports"""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()

        self.translation_exporter = XPIPOExporter()

        # Get the importer.
        self.importer = getUtility(IPersonSet).getByName("mark")

        # Get the Firefox template.
        firefox_product = getUtility(IProductSet).getByName("firefox")
        firefox_productseries = firefox_product.getSeries("trunk")
        firefox_potemplate_subset = getUtility(IPOTemplateSet).getSubset(
            productseries=firefox_productseries
        )
        self.firefox_template = firefox_potemplate_subset.new(
            name="firefox",
            translation_domain="firefox",
            path="en-US.xpi",
            owner=self.importer,
        )

    def _compareExpectedAndExported(self, expected_file, exported_file):
        """Compare an export with a previous export that is correct.

        :param expected_file: buffer with the expected file content.
        :param export_file: buffer with the output file content.
        """
        expected_lines = [line.strip() for line in expected_file.split("\n")]
        # Remove time bombs in tests.
        exported_lines = [
            line.strip()
            for line in exported_file.split("\n")
            if (
                not line.startswith('"X-Launchpad-Export-Date:')
                and not line.startswith('"POT-Creation-Date:')
                and not line.startswith('"X-Generator: Launchpad')
            )
        ]

        for number, expected_line in enumerate(expected_lines):
            self.assertEqual(expected_line, exported_lines[number])

    def setUpTranslationImportQueueForTemplate(self):
        """Return an ITranslationImportQueueEntry for testing purposes."""
        # Install a fake XPI importer, since we no longer have real XPI
        # import code.
        fake_xpi_importer = FakeXPIImporter()
        self.useFixture(
            MonkeyPatch(
                "lp.translations.utilities.translation_import.importers",
                {TranslationFileFormat.XPI: fake_xpi_importer},
            )
        )
        # Temporarily reinstall the translation importer without a security
        # proxy.  This avoids problems getting attributes of
        # FakeXPIImporter, which has no Zope permissions defined.
        self.useFixture(
            ZopeUtilityFixture(
                removeSecurityProxy(getUtility(ITranslationImporter)),
                ITranslationImporter,
            )
        )

        # Attach it to the import queue.
        translation_import_queue = getUtility(ITranslationImportQueue)
        by_maintainer = True
        entry = translation_import_queue.addOrUpdateEntry(
            self.firefox_template.path,
            b"dummy",
            by_maintainer,
            self.importer,
            productseries=self.firefox_template.productseries,
            potemplate=self.firefox_template,
        )

        # We must approve the entry to be able to import it.
        entry.setStatus(
            RosettaImportStatus.APPROVED,
            getUtility(ILaunchpadCelebrities).rosetta_experts,
        )
        # The file data is stored in the Librarian, so we have to commit the
        # transaction to make sure it's stored properly.
        transaction.commit()

        # Prepare the import queue to handle a new .xpi import.
        (subject, body) = self.firefox_template.importFromQueue(entry)

        # The status is now IMPORTED:
        self.assertEqual(entry.status, RosettaImportStatus.IMPORTED)

    def test_Interface(self):
        """Check whether the object follows the interface."""
        self.assertTrue(
            verifyObject(
                ITranslationFormatExporter, self.translation_exporter
            ),
            "XPIPOExporter doesn't follow the interface",
        )

    def test_XPITemplateExport(self):
        """Check a standard export from an XPI file."""
        # Prepare the import queue to handle a new .xpi import.
        self.setUpTranslationImportQueueForTemplate()

        translation_file_data = getAdapter(
            self.firefox_template, ITranslationFileData, "all_messages"
        )
        storage = ExportFileStorage()
        self.translation_exporter.exportTranslationFile(
            translation_file_data, storage
        )

        expected_template = dedent(
            """
            #, fuzzy
            msgid ""
            msgstr ""
            "<?xml version=\\"1.0\\"?>\\n"
            "<RDF xmlns=\\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\\"\\n"
            "     xmlns:em=\\"http://www.mozilla.org/2004/em-rdf#\\">\\n"
            "  <Description about=\\"urn:mozilla:install-manifest\\"\\n"
            "               em:id=\\"langpack-en-US@firefox.mozilla.org\\"\\n"
            "               em:name=\\"English U.S. (en-US) Language Pack\\"\\n"
            "               em:version=\\"2.0\\"\\n"
            "               em:type=\\"8\\"\\n"
            "               em:creator=\\"Danilo Šegan\\">\\n"
            "    <em:contributor>Данило Шеган</em:contributor>\\n"
            "    <em:contributor>Carlos Perelló Marín "
            "&lt;carlos@canonical.com&gt;</em:contributor>\\n"
            "\\n"
            "    <em:targetApplication>\\n"
            "      <Description>\\n"
            "        <em:id>{ec8030f7-c20a-464f-9b0e-13a3a9e97384}</em:id><!-- firefox --"
            ">\\n"
            "        <em:minVersion>2.0</em:minVersion>\\n"
            "        <em:maxVersion>2.0.0.*</em:maxVersion>\\n"
            "      </Description>\\n"
            "    </em:targetApplication>\\n"
            "  </Description>\\n"
            "</RDF>\\n"

            #.  This is a DTD file inside a subdirectory
            #: jar:chrome/en-US.jar!/subdir/test2.dtd(foozilla.menu.title)
            msgctxt "main/subdir/test2.dtd"
            msgid "MENU"
            msgstr ""

            #. Select the access key that you want to use. These have
            #. to be translated in a way that the selected character is
            #. present in the translated string of the label being
            #. referred to, for example 'i' in 'Edit' menu item in
            #. English. If a translation already exists, please don't
            #. change it if you are not sure about it. Please find the
            #. context of the key from the end of the 'Located in' text
            #. below.
            #: jar:chrome/en-US.jar!/subdir/test2.dtd(foozilla.menu.accesskey)
            msgctxt "main/subdir/test2.dtd"
            msgid "M"
            msgstr ""

            #. Select the shortcut key that you want to use. It
            #. should be translated, but often shortcut keys (for
            #. example Ctrl + KEY) are not changed from the original. If
            #. a translation already exists, please don't change it if
            #. you are not sure about it. Please find the context of
            #. the key from the end of the 'Located in' text below.
            #: jar:chrome/en-US.jar!/subdir/test2.dtd(foozilla.menu.commandkey)
            msgctxt "main/subdir/test2.dtd"
            msgid "m"
            msgstr ""

            #. Translators, what you are seeing now is a lovely,
            #. awesome, multiline comment aimed at you directly
            #. from the streets of a .properties file
            #: jar:chrome/en-US.jar!/subdir/test2.properties:6(foozilla_something)
            msgctxt "main/subdir/test2.properties"
            msgid "SomeZilla"
            msgstr ""

            #: jar:chrome/en-US.jar!/test1.dtd(foozilla.name)
            msgctxt "main/test1.dtd"
            msgid "FooZilla!"
            msgstr ""

            #.  Translators, don't play with fire!
            #: jar:chrome/en-US.jar!/test1.dtd(foozilla.play.fire)
            msgctxt "main/test1.dtd"
            msgid "Do you want to play with fire?"
            msgstr ""

            #.  This is just a comment, not a comment for translators
            #: jar:chrome/en-US.jar!/test1.dtd(foozilla.play.ice)
            msgctxt "main/test1.dtd"
            msgid "Play with ice?"
            msgstr ""

            #: jar:chrome/en-US.jar!/test1.properties:1(foozilla.title)
            msgctxt "main/test1.properties"
            msgid "FooZilla Zilla Thingy"
            msgstr ""

            #. Translators, if you're older than six, don't translate this
            #: jar:chrome/en-US.jar!/test1.properties:3(foozilla.happytitle)
            msgctxt "main/test1.properties"
            msgid "http://foozillingy.happy.net/"
            msgstr ""

            #. (Except this one)
            #: jar:chrome/en-US.jar!/test1.properties:4(foozilla.nocomment)
            msgctxt "main/test1.properties"
            msgid "No Comment"
            msgstr ""

            #: jar:chrome/en-US.jar!/test1.properties:5(foozilla.utf8)
            msgctxt "main/test1.properties"
            msgid "Дан=Day"
            msgstr ""
            """  # noqa: E501
        ).strip()

        output = storage.export().read().decode("utf-8")
        self._compareExpectedAndExported(expected_template, output)
