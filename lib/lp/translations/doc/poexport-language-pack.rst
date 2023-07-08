Language Pack Exports
=====================

Launchpad has a way to export all distribution series translations in a
tarball to provide language packs.

Some initialization tasks:

    >>> from datetime import datetime, timezone
    >>> import transaction
    >>> from lp.testing import login
    >>> from lp.services.helpers import bytes_to_tarfile
    >>> from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    >>> from lp.translations.scripts.language_pack import export_language_pack
    >>> from lp.services.database.sqlbase import flush_database_caches
    >>> from lp.services.librarian.interfaces.client import ILibrarianClient
    >>> rosetta_experts = getUtility(ILaunchpadCelebrities).rosetta_experts
    >>> login("daf@canonical.com")

    >>> from lp.services.log.logger import BufferLogger

This is handy for examining the tar files that are generated.

    >>> def get_name(entry):
    ...     """For sorting: get tar entry's name."""
    ...     return entry.name
    ...

    >>> def examine_tarfile(tarfile):
    ...     """Summarize the contents of a tar file."""
    ...     for member in sorted(tarfile.getmembers(), key=get_name):
    ...         if not member.isreg():
    ...             # Not a regular file.  No size to print.
    ...             size = "-"
    ...         else:
    ...             size = len(tarfile.extractfile(member).readlines())
    ...         print("| %5s | %s" % (size, member.name))
    ...


Base language pack export using Librarian
-----------------------------------------

When a new language pack export is requested, you can select to use the
Librarian to store the language pack. That is noted with output_file set
to None.

    >>> logger = BufferLogger()
    >>> language_pack = export_language_pack(
    ...     distribution_name="ubuntu",
    ...     series_name="hoary",
    ...     component="main",
    ...     force_utf8=True,
    ...     output_file=None,
    ...     logger=logger,
    ... )
    >>> transaction.commit()

Check that the log looks ok.

    >>> print(logger.getLogBuffer())
    DEBUG Selecting PO files for export
    INFO  Number of PO files to export: 12
    DEBUG Exporting PO file ... (1/12)
    DEBUG Exporting PO file ... (2/12)
    ...
    INFO  Adding timestamp file
    INFO  Adding mapping file
    INFO  Done.
    DEBUG Upload complete, file alias: ...

    # Get the generated tarball.

    >>> tarfile = bytes_to_tarfile(language_pack.file.read())

The tarball has the right members.

    >>> for member in tarfile.getmembers():
    ...     print(member.name)
    ...
    rosetta-hoary
    ...
    rosetta-hoary/es
    rosetta-hoary/es/LC_MESSAGES
    rosetta-hoary/es/LC_MESSAGES/pmount.po
    ...
    rosetta-hoary/timestamp.txt
    rosetta-hoary/mapping.txt

Directory permissions allow correct use of those directories:

    >>> directory = tarfile.getmember("rosetta-hoary")
    >>> print("0o%o" % directory.mode)
    0o755

And one of the included .po files look like what we expected.

    >>> fh = tarfile.extractfile(
    ...     "rosetta-hoary/es/LC_MESSAGES/evolution-2.2.po"
    ... )
    >>> print(fh.readline().decode())
    # traducción de es.po al Spanish


Base language pack export using Librarian with date limits
----------------------------------------------------------

Launchpad is also able to generate a tarball of all files for a
distribution series that only includes translation files which have been
changed since a certain date.

First we need to set up some data to test with, and for this we need
some DB classes.

    >>> import io
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.model.sourcepackagename import SourcePackageName
    >>> from lp.translations.model.potemplate import POTemplate

Get hold of a person.

    >>> mark = getUtility(IPersonSet).getByName("mark")
    >>> print(mark.displayname)
    Mark Shuttleworth

Get the Grumpy distro series.

    >>> series = getUtility(IDistributionSet)["ubuntu"].getSeries("grumpy")

Get a source package name to go with our distro series.

    >>> spn = SourcePackageName.byName("evolution")

Put a dummy file in the Librarian required by the new template we are
creating.

    >>> contents = b"# Test PO template."
    >>> file_alias = getUtility(ILibrarianClient).addFile(
    ...     name="test.po",
    ...     size=len(contents),
    ...     file=io.BytesIO(contents),
    ...     contentType="application/x-po",
    ... )

Get some dates.

    >>> d2000_01_01 = datetime(year=2000, month=1, day=1, tzinfo=timezone.utc)
    >>> d2000_01_02 = datetime(year=2000, month=1, day=2, tzinfo=timezone.utc)
    >>> d2000_01_03 = datetime(year=2000, month=1, day=3, tzinfo=timezone.utc)

Create a PO template and put a single message set in it.

    >>> pot_header = "Content-Type: text/plain; charset=UTF-8\n"
    >>> template = POTemplate(
    ...     name="test",
    ...     translation_domain="test",
    ...     distroseries=series,
    ...     sourcepackagename=spn,
    ...     owner=mark,
    ...     languagepack=True,
    ...     path="po/test.pot",
    ...     header=pot_header,
    ... )
    >>> potmsgset = template.createMessageSetFromText("blah", None)
    >>> item = potmsgset.setSequence(template, 1)

We set the template last update date to the oldest date we are going to
play with, so it doesn't affect translations export.

    >>> template.date_last_updated = d2000_01_01

Create a Spanish PO file, with an active translation submission created
on 2000/01/01.

    >>> pofile_es = template.newPOFile("es")
    >>> translations = {0: "blah (es)"}
    >>> new_translation_message = factory.makeCurrentTranslationMessage(
    ...     pofile_es, potmsgset, mark, translations=translations
    ... )
    >>> pofile_es.date_changed = d2000_01_01

Create a Welsh PO file, with an active translation submission created on
2000/01/03.

    >>> pofile_cy = template.newPOFile("cy")
    >>> translations = {0: "blah (cy)"}
    >>> new_translation_message = factory.makeCurrentTranslationMessage(
    ...     pofile_cy, potmsgset, mark, translations=translations
    ... )
    >>> pofile_cy.date_changed = d2000_01_03
    >>> transaction.commit()

First, export without any existing base language pack: should get both
PO files.

    >>> print(series.language_pack_base)
    None

    >>> logger = BufferLogger()
    >>> flush_database_caches()
    >>> language_pack = export_language_pack(
    ...     distribution_name="ubuntu",
    ...     series_name="grumpy",
    ...     component=None,
    ...     force_utf8=True,
    ...     output_file=None,
    ...     logger=logger,
    ... )
    >>> transaction.commit()

Check that the log looks ok.

    >>> print(logger.getLogBuffer())
    DEBUG Selecting PO files for export
    INFO  Number of PO files to export: 2
    DEBUG Exporting PO file ... (1/2)
    DEBUG Exporting PO file ... (2/2)
    INFO  Adding timestamp file
    INFO  Adding mapping file
    INFO  Done.
    DEBUG Upload complete, file alias: ...
    INFO  Registered the language pack.

    # Get the generated tarball.

    >>> tarfile = bytes_to_tarfile(language_pack.file.read())
    >>> examine_tarfile(tarfile)
    |     - | rosetta-grumpy
    |     - | rosetta-grumpy/cy
    |     - | rosetta-grumpy/cy/LC_MESSAGES
    |    21 | rosetta-grumpy/cy/LC_MESSAGES/test.po
    |     - | rosetta-grumpy/es
    |     - | rosetta-grumpy/es/LC_MESSAGES
    |    21 | rosetta-grumpy/es/LC_MESSAGES/test.po
    |     1 | rosetta-grumpy/mapping.txt
    |     1 | rosetta-grumpy/timestamp.txt

Check the files look OK.

    >>> fh = tarfile.extractfile("rosetta-grumpy/es/LC_MESSAGES/test.po")
    >>> print(fh.read().decode("UTF-8"))
    # Spanish translation for evolution
    # Copyright (c) ... Rosetta Contributors and Canonical Ltd ...
    # This file is distributed under the same license as the evolution pack...
    # FIRST AUTHOR <EMAIL@ADDRESS>, ...
    #
    msgid ""
    msgstr ""
    "Project-Id-Version: evolution\n"
    "Report-Msgid-Bugs-To: FULL NAME <EMAIL@ADDRESS>\n"
    "POT-Creation-Date: ...\n"
    "PO-Revision-Date: ...\n"
    "Last-Translator: Mark Shuttleworth <mark@example.com>\n"
    "Language-Team: Spanish <es@li.org>\n"
    "MIME-Version: 1.0\n"
    "Content-Type: text/plain; charset=UTF-8\n"
    "Content-Transfer-Encoding: 8bit\n"
    "X-Launchpad-Export-Date: ...-...-... ...:...+...\n"
    "X-Generator: Launchpad (build ...)\n"
    <BLANKLINE>
    msgid "blah"
    msgstr "blah (es)"

    >>> fh = tarfile.extractfile("rosetta-grumpy/cy/LC_MESSAGES/test.po")
    >>> print(fh.read().decode("UTF-8"))
    # Welsh translation for evolution
    # Copyright (c) ... Rosetta Contributors and Canonical Ltd ...
    # This file is distributed under the same license as the evolution pack...
    # FIRST AUTHOR <EMAIL@ADDRESS>, ...
    #
    msgid ""
    msgstr ""
    "Project-Id-Version: evolution\n"
    "Report-Msgid-Bugs-To: FULL NAME <EMAIL@ADDRESS>\n"
    "POT-Creation-Date: ...\n"
    "PO-Revision-Date: ...\n"
    "Last-Translator: Mark Shuttleworth <mark@example.com>\n"
    "Language-Team: Welsh <cy@li.org>\n"
    "MIME-Version: 1.0\n"
    "Content-Type: text/plain; charset=UTF-8\n"
    "Content-Transfer-Encoding: 8bit\n"
    "X-Launchpad-Export-Date: ...-...-... ...:...+...\n"
    "X-Generator: Launchpad (build ...)\n"
    <BLANKLINE>
    msgid "blah"
    msgstr "blah (cy)"

We set this language pack as the base package for the distroseries. Next
export will be a delta based on that one.

    >>> series.language_pack_base = language_pack

This is needed to make the PO export cache work, since it uses the
Librarian.

    >>> transaction.commit()

Then, export with a date limit: we should only get the second PO file.
The way to set date limits is setting when the base language pack was
exported, thus, we set it and request an update export, which means we
should get only files that were updated after 2000-01-02.

    >>> series.language_pack_base.date_exported = d2000_01_02
    >>> transaction.commit()
    >>> language_pack = export_language_pack(
    ...     distribution_name="ubuntu",
    ...     series_name="grumpy",
    ...     component=None,
    ...     force_utf8=True,
    ...     output_file=None,
    ...     logger=logger,
    ... )
    >>> transaction.commit()

    # Get the generated tarball.

    >>> tarfile = bytes_to_tarfile(language_pack.file.read())

Now, there is only one file exported for the 'test' domain, the one that
had the modification date after the last generated language pack.

    >>> examine_tarfile(tarfile)
    |     - | rosetta-grumpy
    |     - | rosetta-grumpy/cy
    |     - | rosetta-grumpy/cy/LC_MESSAGES
    |    21 | rosetta-grumpy/cy/LC_MESSAGES/test.po
    |     1 | rosetta-grumpy/mapping.txt
    |     1 | rosetta-grumpy/timestamp.txt

There is another situation where a translation file is exported again as
part of a language pack update, even without being changed.  It is re-
exported if its template has been changed since the last language pack
was produced.

The latest template change is noted in IPOTemplate.date_last_updated. An
update to the template causes that field to be updated, so that the next
export will include all its translations as well.

    >>> template.date_last_updated = datetime.now(timezone.utc)

    # Save changes.

    >>> transaction.commit()

We export a language pack with changes relative to a base language pack
that was exported on 2000-01-03:

    >>> series.language_pack_base.date_exported = d2000_01_03
    >>> flush_database_caches()
    >>> language_pack = export_language_pack(
    ...     distribution_name="ubuntu",
    ...     series_name="grumpy",
    ...     component=None,
    ...     force_utf8=True,
    ...     output_file=None,
    ...     logger=logger,
    ... )
    >>> transaction.commit()

The Spanish translation has not changed since 2000-01-03, but the
template has.  That's why we get both translations:

    >>> tarfile = bytes_to_tarfile(language_pack.file.read())
    >>> examine_tarfile(tarfile)
    |     - | rosetta-grumpy
    |     - | rosetta-grumpy/cy
    |     - | rosetta-grumpy/cy/LC_MESSAGES
    |    21 | rosetta-grumpy/cy/LC_MESSAGES/test.po
    |     - | rosetta-grumpy/es
    |     - | rosetta-grumpy/es/LC_MESSAGES
    |    21 | rosetta-grumpy/es/LC_MESSAGES/test.po
    |     1 | rosetta-grumpy/mapping.txt
    |     1 | rosetta-grumpy/timestamp.txt


Script arguments and concurrency
--------------------------------

The language-pack-exporter script requires two arguments to run: the
distribution name, and series name. The script promptly exits if the
number of command-line arguments is wrong.

    >>> import subprocess
    >>> def get_subprocess(command):
    ...     return subprocess.Popen(
    ...         command,
    ...         stdin=subprocess.PIPE,
    ...         stdout=subprocess.PIPE,
    ...         stderr=subprocess.PIPE,
    ...         universal_newlines=True,
    ...     )
    ...

    >>> proc = get_subprocess(["cronscripts/language-pack-exporter.py"])
    >>> (out, err) = proc.communicate()
    >>> print(err)
    Traceback (most recent call last):
     ...
    lp.services.scripts.base.LaunchpadScriptFailure:
    Wrong number of arguments: should include distribution and series name.

    >>> proc.returncode
    1

The script runs when 'ubuntu' and 'hoary' are passed as the distribution
and series names.

Several instances of the language-pack-exporter script can be run
concurrently so long as each instance is exporting a different
combination of distribution and series. LaunchpadScript instanced uses
the lockfilename to prevent the script from running concurrently.
RosettaLangPackExporter incorporates the distribution and series names
into the lockfilename to allow multiple exports to run concurrently for
different distribution and series combinations.

    >>> proc = get_subprocess(
    ...     ["cronscripts/language-pack-exporter.py", "ubuntu", "hoary"]
    ... )
    >>> (out, err) = proc.communicate()
    >>> print(err)
    INFO    Setting lockfile name to
            launchpad-language-pack-exporter__ubuntu__hoary.lock.
    INFO    Creating lockfile:
        /var/lock/launchpad-language-pack-exporter__ubuntu__hoary.lock
    INFO    Exporting translations for series hoary of distribution ubuntu.
    INFO    Number of PO files to export: 12
    INFO    Adding timestamp file
    INFO    Adding mapping file
    INFO    Done.
    INFO    Registered the language pack.

    >>> print(out)
    <BLANKLINE>

    >>> proc.returncode
    0
