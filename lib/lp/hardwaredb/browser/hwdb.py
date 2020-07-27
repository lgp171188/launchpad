# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'HWDBApplicationNavigation',
    'HWDBFingerprintSetView',
    'HWDBPersonSubmissionsView',
    'HWDBSubmissionTextView',
    ]

from textwrap import dedent

from zope.browserpage import ViewPageTemplateFile
from zope.component import getUtility
from zope.interface import implementer
from zope.publisher.interfaces.browser import IBrowserPublisher

from lp.app.errors import NotFoundError
from lp.hardwaredb.interfaces.hwdb import (
    IHWDBApplication,
    IHWDeviceClassSet,
    IHWDeviceSet,
    IHWDriverSet,
    IHWSubmissionDeviceSet,
    IHWSubmissionSet,
    IHWVendorIDSet,
    )
from lp.services.webapp import (
    LaunchpadView,
    Navigation,
    stepthrough,
    )
from lp.services.webapp.batching import BatchNavigator
from lp.services.webapp.interfaces import ILaunchBag


class HWDBPersonSubmissionsView(LaunchpadView):
    """View class for preseting HWDB submissions by a person."""

    @property
    def label(self):
        return 'Hardware submissions for %s' % (self.context.title,)

    @property
    def page_title(self):
        return "Hardware Database submissions by %s" % (self.context.title,)

    def getAllBatched(self):
        """Return the list of HWDB submissions made by this person."""
        hw_submissionset = getUtility(IHWSubmissionSet)
        submissions = hw_submissionset.getByOwner(self.context, self.user)
        return BatchNavigator(submissions, self.request)

    def userIsOwner(self):
        """Return true, if self.context == self.user"""
        return self.context == self.user


class HWDBSubmissionTextView(LaunchpadView):
    """Renders a HWDBSubmission in parseable text."""
    def render(self):
        data = {}
        data["date_created"] = self.context.date_created
        data["date_submitted"] = self.context.date_submitted
        data["format"] = self.context.format.name

        dar = self.context.distroarchseries
        if dar:
            data["distribution"] = dar.distroseries.distribution.name
            data["distribution_series"] = dar.distroseries.version
            data["architecture"] = dar.architecturetag
        else:
            data["distribution"] = "(unknown)"
            data["distribution_series"] = "(unknown)"
            data["architecture"] = "(unknown)"

        data["system_fingerprint"] = (
            self.context.system_fingerprint.fingerprint)
        data["url"] = self.context.raw_submission.http_url

        return dedent("""
            Date-Created: %(date_created)s
            Date-Submitted: %(date_submitted)s
            Format: %(format)s
            Distribution: %(distribution)s
            Distribution-Series: %(distribution_series)s
            Architecture: %(architecture)s
            System: %(system_fingerprint)s
            Submission URL: %(url)s""" % data)


class HWDBApplicationNavigation(Navigation):
    """Navigation class for HWDBSubmissionSet."""

    usedfor = IHWDBApplication

    @stepthrough('+submission')
    def traverse_submission(self, name):
        user = getUtility(ILaunchBag).user
        submission = getUtility(IHWSubmissionSet).getBySubmissionKey(
            name, user=user)
        return submission

    @stepthrough('+fingerprint')
    def traverse_hwdb_fingerprint(self, name):
        return HWDBFingerprintSetView(self.context, self.request, name)

    @stepthrough('+device')
    def traverse_device(self, id):
        try:
            id = int(id)
        except ValueError:
            raise NotFoundError('invalid value for ID: %r' % id)
        return getUtility(IHWDeviceSet).getByID(id)

    @stepthrough('+deviceclass')
    def traverse_device_class(self, id):
        try:
            id = int(id)
        except ValueError:
            raise NotFoundError('invalid value for ID: %r' % id)
        return getUtility(IHWDeviceClassSet).get(id)

    @stepthrough('+driver')
    def traverse_driver(self, id):
        try:
            id = int(id)
        except ValueError:
            raise NotFoundError('invalid value for ID: %r' % id)
        return getUtility(IHWDriverSet).getByID(id)

    @stepthrough('+submissiondevice')
    def traverse_submissiondevice(self, id):
        try:
            id = int(id)
        except ValueError:
            raise NotFoundError('invalid value for ID: %r' % id)
        return getUtility(IHWSubmissionDeviceSet).get(id)

    @stepthrough('+hwvendorid')
    def traverse_hw_vendor_id(self, id):
        try:
            id = int(id)
        except ValueError:
            raise NotFoundError('invalid value for ID: %r' % id)
        return getUtility(IHWVendorIDSet).get(id)


@implementer(IBrowserPublisher)
class HWDBFingerprintSetView(LaunchpadView):
    """View class for lists of HWDB submissions for a system fingerprint."""
    label = page_title = "Hardware Database submissions for a fingerprint"

    template = ViewPageTemplateFile(
        '../templates/hwdb-fingerprint-submissions.pt')

    def __init__(self, context,  request, system_name):
        LaunchpadView.__init__(self, context, request)
        self.system_name = system_name

    def getAllBatched(self):
        """A BatchNavigator instance with the submissions."""
        submissions = getUtility(IHWSubmissionSet).getByFingerprintName(
            self.system_name, self.user)
        return BatchNavigator(submissions, self.request)

    def browserDefault(self, request):
        """See `IBrowserPublisher`."""
        return self, ()

    def showOwner(self, submission):
        """Check if the owner can be shown in the list.
        """
        return (submission.owner is not None
                and (submission.contactable
                     or (submission.owner == self.user)))
