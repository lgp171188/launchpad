# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

from datetime import timedelta

from zope.interface import Interface, Attribute
from zope.schema import (
    Bool, Choice, Datetime, Field, Int, Object, Text, TextLine)
from zope.security.interfaces import Unauthorized
from lazr.enum import DBEnumeratedType, DBItem, EnumeratedType, Item

from canonical.launchpad import _
from canonical.launchpad.fields import PersonChoice
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat)
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.productseries import IProductSeries

from lazr.restful.interface import copy_field
from lazr.restful.fields import Reference
from lazr.restful.declarations import (call_with,
    collection_default_content, exported, export_as_webservice_collection,
    export_as_webservice_entry, export_read_operation,
    export_write_operation, operation_parameters,
    operation_returns_entry, operation_returns_collection_of,
    REQUEST_USER, webservice_error)
from lp.translations.interfaces.translationcommonformat import (
    TranslationImportExportBaseException)

__metaclass__ = type

__all__ = [
    'TranslationImportQueueConflictError',
    'ITranslationImportQueueEntry',
    'ITranslationImportQueue',
    'IEditTranslationImportQueueEntry',
    'IHasTranslationImports',
    'RosettaImportStatus',
    'SpecialTranslationImportTargetFilter',
    'TranslationFileType',
    'translation_import_queue_entry_age',
    'UserCannotSetTranslationImportStatus',
    ]


class TranslationImportQueueConflictError(
                                    TranslationImportExportBaseException):
    """A new entry cannot be inserted into the queue because it
    conflicts with existing entries."""


class UserCannotSetTranslationImportStatus(Unauthorized):
    """User not permitted to change status.

    Raised when a user tries to transition to a new status who doesn't
    have the necessary permissions.
    """
    webservice_error(401) # HTTP Error: 'Unauthorized'


class RosettaImportStatus(DBEnumeratedType):
    """Rosetta Import Status

    Define the status of an import on the Import queue. It could have one
    of the following states: approved, imported, deleted, failed, needs_review
    or blocked.
    """

    APPROVED = DBItem(1, """
        Approved

        The entry has been approved by a Rosetta Expert or was able to be
        approved by our automatic system and is waiting to be imported.
        """)

    IMPORTED = DBItem(2, """
        Imported

        The entry has been imported.
        """)

    DELETED = DBItem(3, """
        Deleted

        The entry has been removed before being imported.
        """)

    FAILED = DBItem(4, """
        Failed

        The entry import failed.
        """)

    NEEDS_REVIEW = DBItem(5, """
        Needs Review

        A Rosetta Expert needs to review this entry to decide whether it will
        be imported and where it should be imported.
        """)

    BLOCKED = DBItem(6, """
        Blocked

        The entry has been blocked to be imported by a Rosetta Expert.
        """)

    NEEDS_INFORMATION = DBItem(7, """
        Needs Information

        The reviewer needs more information before this entry can be approved.
        """)


# Some time spans in days.
DAYS_IN_MONTH = 30
DAYS_IN_HALF_YEAR = 366 / 2


# Period after which entries with certain statuses are culled from the
# queue.
translation_import_queue_entry_age = {
    RosettaImportStatus.DELETED: timedelta(days=3),
    RosettaImportStatus.FAILED: timedelta(days=DAYS_IN_MONTH),
    RosettaImportStatus.IMPORTED: timedelta(days=3),
    RosettaImportStatus.NEEDS_INFORMATION: timedelta(days=14),
    RosettaImportStatus.NEEDS_REVIEW: timedelta(days=DAYS_IN_HALF_YEAR),
}


class SpecialTranslationImportTargetFilter(DBEnumeratedType):
    """Special "meta-targets" to filter the queue view by."""

    PRODUCT = DBItem(1, """
        Any project

        Any project registered in Launchpad.
        """)

    DISTRIBUTION = DBItem(2, """
        Any distribution

        Any distribution registered in Launchpad.
        """)


class IHasTranslationImports(Interface):
    """An entity on which a translation import queue entry is attached.

    Examples include an IProductSeries, ISourcePackage, IDistroSeries and
    IPerson.
    """
    export_as_webservice_entry(
        singular_name='object_with_translation_imports',
        plural_name='objects_with_translation_imports')

    def getFirstEntryToImport():
        """Return the first entry of the queue ready to be imported."""

    def getTranslationImportQueueEntries(imports_status=None,
                                         file_extension=None):
        """Return entries in the translation import queue for this entity.

        :arg import_status: RosettaImportStatus DB Schema entry.
        :arg file_extension: String with the file type extension, usually 'po'
            or 'pot'.

        If one of both of 'import_status' or 'file_extension' are given, the
        returned entries are filtered based on those values.
        """


class ITranslationImportQueueEntry(Interface):
    """An entry of the Translation Import Queue."""
    export_as_webservice_entry(
        singular_name='translation_import_queue_entry',
        plural_name='translation_import_queue_entries')

    id = exported(Int(title=_('The entry ID'), required=True, readonly=True))

    path = exported(
        TextLine(
            title=_("Path"),
            description=_(
                "The path to this file inside the source tree. Includes the"
                " filename."),
            required=True))

    importer = exported(
        PersonChoice(
            title=_("Uploader"),
            required=True,
            readonly=True,
            description=_(
                "The person that uploaded this file to Launchpad."),
            vocabulary="ValidOwner"),
        exported_as="uploader")

    dateimported = exported(
        Datetime(
            title=_("The timestamp when this queue entry was created."),
            required=True,
            readonly=True),
        exported_as="date_created")

    productseries = exported(
        Object(
            title=_("Series"),
            required=False,
            readonly=True,
            schema=IProductSeries))

    distroseries = exported(
        Object(
            title=_("Series"),
            required=False,
            readonly=True,
            schema=IDistroSeries))

    sourcepackagename = Choice(
        title=_("Source Package Name"),
        description=_(
            "The source package from where this entry comes."),
        required=False,
        vocabulary="SourcePackageName")

    is_published = Bool(
        title=_("This import comes from a published file"),
        description=_(
            "If checked, this import will be handled as already published."),
        required=True,
        default=False)

    content = Attribute(
        "An ILibraryFileAlias reference with the file content. Must not be"
        " None.")

    format = exported(
        Choice(
            title=_('The file format of the import.'),
            vocabulary=TranslationFileFormat,
            required=True,
            readonly=True))

    status = exported(
        Choice(
            title=_("The status of the import."),
            values=RosettaImportStatus.items,
            required=True,
            readonly=True))

    date_status_changed = exported(
        Datetime(
            title=_("The timestamp when the status was changed."),
            required=True))

    is_targeted_to_ubuntu = Attribute(
        "True if this entry is to be imported into the Ubuntu distribution.")

    sourcepackage = exported(
        Object(
            schema=ISourcePackage,
            title=_("The sourcepackage associated with this entry."),
            readonly=True))

    guessed_potemplate = Attribute(
        "The IPOTemplate that we can guess this entry could be imported into."
        " None if we cannot guess it.")

    import_into = Attribute("The Object where this entry will be imported. Is"
        " None if we don't know where to import it.")

    pofile = Field(
        title=_("The IPOfile where this entry should be imported."),
        required=False)

    potemplate = Field(
        title=_("The IPOTemplate associated with this entry."),
        description=_("The IPOTemplate associated with this entry. If path"
        " notes a .pot file, it should be used as the place where this entry"
        " will be imported, if it's a .po file, it indicates the template"
        " associated with tha translation."),
        required=False)

    error_output = exported(
        Text(
            title=_("Error output"),
            description=_("Output from most recent import attempt."),
            required=False,
            readonly=True))

    def canAdmin(roles):
        """Check if the user can administer this entry."""

    def canEdit(roles):
        """Check if the user can edit this entry."""

    def canSetStatus(new_status, user):
        """Check if the user can set this new status."""

    @call_with(user=REQUEST_USER)
    @operation_parameters(new_status=copy_field(status))
    @export_write_operation()
    def setStatus(new_status, user):
        """Transition to a new status if possible.

        :param new_status: Status to transition to.
        :param user: The user that is doing the transition.
        """

    def setErrorOutput(output):
        """Set `error_output` string."""

    def addWarningOutput(output):
        """Optionally add warning output to `error_output`.

        This may not do everything you expect of it.  Read the code if
        you need certainty.
        """

    def getGuessedPOFile():
        """Return an IPOFile that we think this entry should be imported into.

        Return None if we cannot guess it."""

    def getFileContent():
        """Return the imported file content as a stream."""

    def getTemplatesOnSameDirectory():
        """Return import queue entries stored on the same directory as self.

        The returned entries will be only .pot entries.
        """

    def getElapsedTimeText():
        """Return a string representing elapsed time since we got the file.

        The returned string is like:
            '2 days 3 hours 10 minutes ago' or 'just requested'
        """


class ITranslationImportQueue(Interface):
    """A set of files to be imported into Rosetta."""
    export_as_webservice_collection(ITranslationImportQueueEntry)

    def __iter__():
        """Iterate over all entries in the queue."""

    def __getitem__(id):
        """Return the ITranslationImportQueueEntry with the given id.

        If there is not entries with that id, the NotFoundError exception is
        raised.
        """

    def countEntries():
        """Return the number of `TranslationImportQueueEntry` records."""

    def addOrUpdateEntry(path, content, is_published, importer,
        sourcepackagename=None, distroseries=None, productseries=None,
        potemplate=None, pofile=None, format=None):
        """Return a new or updated entry of the import queue.

        :arg path: is the path, with the filename, of the file imported.
        :arg content: is the file content.
        :arg is_published: indicates if the imported file is already published
            by upstream.
        :arg importer: is the person that did the import.
        :arg sourcepackagename: is the link of this import with source
            package.
        :arg distroseries: is the link of this import with a distribution.
        :arg productseries: is the link of this import with a product branch.
        :arg potemplate: is the link of this import with an IPOTemplate.
        :arg pofile: is the link of this import with an IPOFile.
        :arg format: a TranslationFileFormat.
        :return: the entry, or None if processing failed.

        The entry is either for a sourcepackage or a productseries, so
        only one of them can be specified.
        """

    def addOrUpdateEntriesFromTarball(content, is_published, importer,
        sourcepackagename=None, distroseries=None, productseries=None,
        potemplate=None, filename_filter=None, approver_factory=None):
        """Add all .po or .pot files from the tarball at :content:.

        :arg content: is a tarball stream.
        :arg is_published: indicates if the imported file is already published
            by upstream.
        :arg importer: is the person that did the import.
        :arg sourcepackagename: is the link of this import with source
            package.
        :arg distroseries: is the link of this import with a distribution.
        :arg productseries: is the link of this import with a product branch.
        :arg potemplate: is the link of this import with an IPOTemplate.
        :arg approver_factory: is a factory that can be called to create an
            approver.  The method invokes the approver on any queue entries
            that it creates. If this is None, no approval is performed.
        :return: A tuple of the number of successfully processed files and a
            list of those filenames that could not be processed correctly.

        The entries are either for a sourcepackage or a productseries, so
        only one of them can be specified.
        """

    def get(id):
        """Return the ITranslationImportQueueEntry with the given id or None.
        """

    @collection_default_content()
    @operation_parameters(
        import_status=copy_field(ITranslationImportQueueEntry['status']))
    @operation_returns_collection_of(ITranslationImportQueueEntry)
    @export_read_operation()
    def getAllEntries(target=None, import_status=None, file_extensions=None):
        """Return all entries this import queue has.

        :arg target: IPerson, IProduct, IProductSeries, IDistribution,
            IDistroSeries or ISourcePackage the import entries are attached to
            or None to get all entries available.
        :arg import_status: RosettaImportStatus entry.
        :arg file_extensions: Sequence of filename suffixes to match, usually
            'po' or 'pot'.

        If any of target, status or file_extension are given, the returned
        entries are filtered based on those values.
        """

    @export_read_operation()
    @operation_parameters(target=Reference(schema=IHasTranslationImports))
    @operation_returns_entry(ITranslationImportQueueEntry)
    def getFirstEntryToImport(target=None):
        """Return the first entry of the queue ready to be imported.

        :param target: IPerson, IProduct, IProductSeries, IDistribution,
            IDistroSeries or ISourcePackage the import entries are attached to
            or None to get all entries available.
        """

    @export_read_operation()
    @operation_parameters(
        status=copy_field(ITranslationImportQueueEntry['status']))
    @operation_returns_collection_of(IHasTranslationImports)
    def getRequestTargets(status=None):
        """List `Product`s and `DistroSeries` with pending imports.

        :arg status: Filter by `RosettaImportStatus`.

        All returned items will implement `IHasTranslationImports`.
        """

    def executeOptimisticApprovals(txn=None):
        """Try to approve Needs-Review entries.

        :arg txn: Optional transaction manager.  If given, will be
            committed regularly.

        This method moves all entries that we know where should they be
        imported from the Needs Review status to the Accepted one.
        """

    def executeOptimisticBlock(txn=None):
        """Try to move entries from the Needs Review status to Blocked one.

        :arg txn: Optional transaction manager.  If given, will be
            committed regularly.

        This method moves uploaded translations for Blocked templates to
        the Blocked status as well.  This lets you block a template plus
        all its present or future translations in one go.

        :return: The number of items blocked.
        """

    def cleanUpQueue():
        """Remove old entries in terminal states.

        This "garbage-collects" entries from the queue based on their
        status (e.g. Deleted and Imported ones) and how long they have
        been in that status.

        :return: The number of entries deleted.
        """

    def remove(entry):
        """Remove the given :entry: from the queue."""


class TranslationFileType(EnumeratedType):
    """The different types of translation files that can be imported."""

    UNSPEC = Item("""
        <Please specify>

        Not yet specified.
        """)

    POT = Item("""
        Template

        A translation template file.
        """)

    PO = Item("""
        Translations

        A translation data file.
        """)


class IEditTranslationImportQueueEntry(Interface):
    """Set of widgets needed to moderate an entry on the imports queue."""

    file_type = Choice(
        title=_("File Type"),
        description=_(
            "The type of the file being imported."),
        required=True,
        vocabulary = TranslationFileType)

    path = TextLine(
        title=_("Path"),
        description=_(
            "The path to this file inside the source tree."),
        required=True)

    sourcepackagename = Choice(
        title=_("Source Package Name"),
        description=_(
            "The source package where this entry will be imported."),
        required=True,
        vocabulary="SourcePackageName")

    name = TextLine(
        title=_("Name"),
        description=_(
            "For templates only: "
            "The name of this PO template, for example "
            "'evolution-2.2'. Each translation template has a "
            "unique name in its package."),
        required=False)

    translation_domain = TextLine(
        title=_("Translation domain"),
        description=_(
            "For templates only: "
            "The translation domain for a translation template. "
            "Used with PO file format when generating MO files for inclusion "
            "in language pack or MO tarball exports."),
        required=False)

    languagepack = Bool(
        title=_("Include translations for this template in language packs?"),
        description=_(
            "For templates only: "
            "Check this box if this template is part of a language pack so "
            "its translations should be exported that way."),
        required=True,
        default=False)

    potemplate = Choice(
        title=_("Template"),
        description=_(
            "For translations only: "
            "The template that this translation is based on. "
            "The template has to be uploaded first."),
        required=False,
        vocabulary="TranslationTemplate")

    potemplate_name = TextLine(
        title=_("Template name"),
        description=_(
            "For translations only: "
            "Enter the template name if it does not appear "
            "in the list above."),
        required=False)

    language = Choice(
        title=_("Language"),
        required=True,
        description=_(
            "For translations only: "
            "The language this PO file translates to."),
        vocabulary="Language")
