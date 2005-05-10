# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

from zope.interface import Interface, Attribute
from canonical.launchpad.interfaces.rawfiledata import ICanAttachRawFileData
from canonical.launchpad.interfaces.rosettastats import IRosettaStats

__metaclass__ = type

__all__ = ('IPOFileSet', 'IPOFile', 'IEditPOFile')

class IPOFileSet(Interface):
    """A set of POFile."""

    def getPOFilesPendingImport():
        """Return a list of PO files that have data to be imported."""


class IPOFile(IRosettaStats, ICanAttachRawFileData):
    """A PO File."""

    id = Attribute("This PO file's id.")

    potemplate = Attribute("This PO file's template.")

    language = Attribute("Language of this PO file.")

    title = Attribute("The PO file's title.")

    description = Attribute("PO file description.")

    topcomment = Attribute("The main comment for this .po file.")

    header = Attribute("The header of this .po file.")

    fuzzyheader = Attribute("Whether the header is fuzzy or not.")

    lasttranslator = Attribute("The last person that translated a string here.")

    license = Attribute("The license under this translation is done.")

    lastparsed = Attribute("Last time this pofile was parsed.")

    owner = Attribute("The owner for this pofile.")

    pluralforms = Attribute("The number of plural forms this PO file has.")

    variant = Attribute("The language variant for this PO file.")

    filename = Attribute("The name of the file that was imported")

    latest_sighting = Attribute("""Of all the translation sightings belonging
        to PO messages sets belonging to this PO file, return the one which
        was most recently modified (greatest datelastactive), or None if
        there are no sightings belonging to this PO file.""")

    def __len__():
        """Returns the number of current IPOMessageSets in this PO file."""

    def translatedCount():
        """
        Returns the number of message sets which this PO file has current
        translations for.
        """

    def translated():
        """
        Return an iterator over translated message sets in this PO file.
        """

    def untranslatedCount():
        """
        Return the number of messages which this PO file has no translation
        for.
        """

    def untranslated():
        """
        Return an iterator over untranslated message sets in this PO file.
        """

    # Invariant: translatedCount() + untranslatedCount() = __len__()
    # XXX: add a test for this

    def __iter__():
        """Return an iterator over Current IPOMessageSets in this PO file."""

    def messageSet(key, onlyCurrent=False):
        """Extract one or several POMessageSets from this template.

        If the key is a string or a unicode object, returns the
        IPOMsgSet in this template that has a primary message ID
        with the given text.

        If the key is a slice, returns the message IDs by sequence within the
        given slice.

        If onlyCurrent is True, then get only current message sets.
        """

    def __getitem__(msgid):
        """Same as messageSet(), with onlyCurrent=True.
        """

    def messageSetsNotInTemplate():
        """
        Return an iterator over message sets in this PO file that do not
        correspond to a message set in the template; eg, the template
        message set has sequence=0.
        """

    def hasMessageID(msgid):
        """Check whether a message set with the given message ID exists within
        this PO file."""

    def pendingImport():
        """Gives all pofiles that have a rawfile pending of import into
        Rosetta."""

    def getContributors():
        """Returns the list of persons that have an active contribution inside
        this POFile."""


class IEditPOFile(IPOFile):
    """Edit interface for a PO File."""

    def expireAllMessages():
        """Mark our of our message sets as not current (sequence=0)"""

    def updateStatistics():
        """Update the statistics fields - rosettaCount, updatesCount and
        currentCount - from the messages currently known.
        Return a tuple (rosettaCount, updatesCount, currentCount)."""

    def createMessageSetFromMessageSet(potmsgset):
        """Creates in the database a new message set.

        Returns the newly created message set.
        """

    def createMessageSetFromText(text):
        """Creates in the database a new message set.

        Similar to createMessageSetFromMessageSet, but takes a text object
        (unicode or string) rather than a POT message Set.

        Returns the newly created message set.
        """
