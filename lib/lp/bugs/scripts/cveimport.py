# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A set of functions related to the ability to parse the XML CVE database,
extract details of known CVE entries, and ensure that all of the known
CVE's are fully registered in Launchpad."""

import gzip
import io
import time

import defusedxml.ElementTree as ElementTree
import requests
import six
from zope.component import getUtility
from zope.event import notify
from zope.interface import implementer
from zope.lifecycleevent import ObjectModifiedEvent

from lp.bugs.interfaces.cve import CveStatus, ICveSet
from lp.services.config import config
from lp.services.looptuner import ITunableLoop, LoopTuner
from lp.services.scripts.base import (
    LaunchpadCronScript,
    LaunchpadScriptFailure,
)
from lp.services.timeout import override_timeout, urlfetch

CVEDB_NS = "{http://cve.mitre.org/cve/downloads/1.0}"


def getText(elem):
    """Get the text content of the given element"""
    text = six.ensure_text(elem.text or "")
    for e in elem:
        text += getText(e)
        if e.tail:
            text += six.ensure_text(e.tail)
    return text.strip()


def handle_references(cve_node, cve, log):
    """Handle the references on the given CVE xml DOM.

    This function is passed an XML dom representing a CVE, and a CVE
    database object. It looks for Refs in the XML data structure and ensures
    that those are correctly represented in the database.

    It will try to find a relevant reference, and if so, update it. If
    not, it will create a new reference.  Finally, it removes any old
    references that it no longer sees in the official CVE database.
    It will return True or False, indicating whether or not the cve was
    modified in the process.
    """
    modified = False
    # we make a copy of the references list because we will be removing
    # items from it, to see what's left over
    old_references = set(cve.references)
    new_references = set()

    # work through the refs in the xml dump
    for ref_node in cve_node.findall(".//%sref" % CVEDB_NS):
        refsrc = six.ensure_text(ref_node.get("source"))
        refurl = ref_node.get("url")
        if refurl is not None:
            refurl = six.ensure_text(refurl)
        reftxt = getText(ref_node)
        # compare it to each of the known references
        was_there_previously = False
        for ref in old_references:
            if (
                ref.source == refsrc
                and ref.url == refurl
                and ref.content == reftxt
            ):
                # we have found a match, remove it from the old list
                was_there_previously = True
                new_references.add(ref)
                break
        if not was_there_previously:
            log.info(
                "Creating new %s reference for %s" % (refsrc, cve.sequence)
            )
            ref = cve.createReference(refsrc, reftxt, url=refurl)
            new_references.add(ref)
            modified = True
    # now, if there are any refs in old_references that are not in
    # new_references, then we need to get rid of them
    for ref in sorted(
        old_references, key=lambda a: (a.source, a.content, a.url)
    ):
        if ref not in new_references:
            log.info(
                "Removing %s reference for %s" % (ref.source, cve.sequence)
            )
            cve.removeReference(ref)
            modified = True

    return modified


def update_one_cve(cve_node, log):
    """Update the state of a single CVE item."""
    # get the sequence number
    sequence = six.ensure_text(cve_node.get("seq"))
    # establish its status
    status = six.ensure_text(cve_node.get("type"))
    # get the description
    description = getText(cve_node.find(CVEDB_NS + "desc"))
    if not description:
        log.debug("No description for CVE-%s" % sequence)
    if status == "CAN":
        new_status = CveStatus.CANDIDATE
    elif status == "CVE":
        new_status = CveStatus.ENTRY
    else:
        log.error("Unknown status %s for CVE-%s" % (status, sequence))
        return
    # find or create the CVE entry in the db
    cveset = getUtility(ICveSet)
    cve = cveset[sequence]
    if cve is None:
        cve = cveset.new(sequence, description, new_status)
        log.info("CVE-%s created" % sequence)
    # update the CVE if needed
    modified = False
    if cve.status != new_status:
        log.info(
            "CVE-%s changed from %s to %s"
            % (cve.sequence, cve.status.title, new_status.title)
        )
        cve.status = new_status
        modified = True
    if cve.description != description:
        log.info("CVE-%s updated description" % cve.sequence)
        cve.description = description
        modified = True
    # make sure we have copies of all the references.
    if handle_references(cve_node, cve, log):
        modified = True
    # trigger an event if modified
    if modified:
        notify(ObjectModifiedEvent(cve))
    return


@implementer(ITunableLoop)
class CveUpdaterTunableLoop:
    """An `ITunableLoop` for updating CVEs."""

    total_updated = 0

    def __init__(self, cves, transaction, logger, offset=0):
        self.cves = cves
        self.transaction = transaction
        self.logger = logger
        self.offset = offset
        self.total_updated = 0

    def isDone(self):
        """See `ITunableLoop`."""
        return self.offset is None

    def __call__(self, chunk_size):
        """Retrieve a batch of CVEs and update them.

        See `ITunableLoop`.
        """
        chunk_size = int(chunk_size)

        self.logger.debug("More %d" % chunk_size)

        start = self.offset
        end = self.offset + chunk_size

        self.transaction.begin()

        cve_batch = self.cves[start:end]
        self.offset = None
        for cve in cve_batch:
            start += 1
            self.offset = start
            update_one_cve(cve, self.logger)
            self.total_updated += 1

        self.logger.debug("Committing.")
        self.transaction.commit()


class CVEUpdater(LaunchpadCronScript):
    def add_my_options(self):
        """Parse command line arguments."""
        self.parser.add_option(
            "-f",
            "--cvefile",
            dest="cvefile",
            default=None,
            help="An XML file containing the CVE database.",
        )
        self.parser.add_option(
            "-u",
            "--cveurl",
            dest="cveurl",
            default=config.cveupdater.cve_db_url,
            help="The URL for the XML CVE database.",
        )

    def main(self):
        self.logger.info("Initializing...")
        if self.options.cvefile is not None:
            try:
                with open(self.options.cvefile) as f:
                    cve_db = f.read()
            except OSError:
                raise LaunchpadScriptFailure(
                    "Unable to open CVE database in %s" % self.options.cvefile
                )
        elif self.options.cveurl is not None:
            cve_db = self.fetchCVEURL(self.options.cveurl)
        else:
            raise LaunchpadScriptFailure("No CVE database file or URL given.")

        # Start analysing the data.
        start_time = time.time()
        self.logger.info("Processing CVE XML...")
        self.processCVEXML(cve_db)
        finish_time = time.time()
        self.logger.info(
            "%d seconds to update database." % (finish_time - start_time)
        )

    def fetchCVEURL(self, url):
        """Fetch CVE data from a URL, decompressing if necessary."""
        self.logger.info("Downloading CVE database from %s..." % url)
        try:
            with override_timeout(config.cveupdater.timeout):
                # Command-line options are trusted, so allow file://
                # URLs to ease testing.
                response = urlfetch(url, use_proxy=True, allow_file=True)
        except requests.RequestException:
            raise LaunchpadScriptFailure(
                "Unable to connect for CVE database %s" % url
            )

        cve_db = response.content
        self.logger.info("%d bytes downloaded." % len(cve_db))
        # requests will normally decompress this automatically, but that
        # might not be the case if we're given a file:// URL to a gzipped
        # file.
        if cve_db[:2] == b"\037\213":  # gzip magic
            cve_db = gzip.GzipFile(fileobj=io.BytesIO(cve_db)).read()
        return cve_db

    def processCVEXML(self, cve_xml):
        """Process the CVE XML file.

        :param cve_xml: The CVE XML as a string.
        """
        dom = ElementTree.fromstring(cve_xml, forbid_dtd=True)
        items = dom.findall(CVEDB_NS + "item")
        if len(items) == 0:
            raise LaunchpadScriptFailure("No CVEs found in XML file.")
        self.logger.info("Updating database...")

        # We use Looptuner to control the ideal number of CVEs
        # processed in each transaction, during at least 2 seconds.
        loop = CveUpdaterTunableLoop(items, self.txn, self.logger)
        loop_tuner = LoopTuner(loop, 2)
        loop_tuner.run()
