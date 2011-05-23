# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views which export vocabularies as JSON for widgets."""

__metaclass__ = type

__all__ = [
    'branch_to_vocabularyjson',
    'default_vocabularyjson_adapter',
    'HugeVocabularyJSONView',
    'IPickerEntry',
    'person_to_vocabularyjson',
    'sourcepackagename_to_vocabularyjson',
    ]

import re
import simplejson

from lazr.restful.interfaces import IWebServiceClientRequest
from zope.app.form.interfaces import MissingInputError
from zope.app.schema.vocabulary import IVocabularyFactory
from zope.component import (
    adapter,
    getUtility,
    )
from zope.component.interfaces import ComponentLookupError
from zope.interface import (
    Attribute,
    implementer,
    implements,
    Interface,
    )
from zope.security.interfaces import Unauthorized

from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.interfaces import NoCanonicalUrl
from canonical.launchpad.webapp.publisher import canonical_url
from lp.app.browser.tales import ObjectImageDisplayAPI
from canonical.launchpad.webapp.vocabulary import IHugeVocabulary
from lp.app.errors import UnexpectedFormData
from lp.code.interfaces.branch import IBranch
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.sourcepackagename import ISourcePackageName
from lp.registry.model.pillaraffiliation import IHasAffiliation
from lp.registry.model.sourcepackagename import getSourcePackageDescriptions

# XXX: EdwinGrubbs 2009-07-27 bug=405476
# This limits the output to one line of text, since the sprite class
# cannot clip the background image effectively for vocabulary items
# with more than single line description below the title.
MAX_DESCRIPTION_LENGTH = 120


class IPickerEntry(Interface):
    """Additional fields that the vocabulary doesn't provide.

    These fields are needed by the Picker Ajax widget."""
    description = Attribute('Description')
    image = Attribute('Image URL')
    # An item's icon indicates its type (eg person, team).
    css = Attribute('Icon CSS Class')
    # An item can also have a badge which is displayed after the title.
    css_badge = Attribute('Badge CSS Class')


class PickerEntry:
    """See `IPickerEntry`."""
    implements(IPickerEntry)

    def __init__(self, description=None, image=None, css=None, api_uri=None):
        self.description = description
        self.image = image
        self.css = css


@adapter(Interface)
class DefaultPickerEntryAdapter(object):
    """Adapts Interface to IPickerEntry."""

    implements(IPickerEntry)
    
    def __init__(self, context):
        self.context = context

    def getPickerEntry(self, associated_object):
        """ Construct a PickerEntry for the context of this adaptor.

        The associated_object represents the context for which the picker is
        being rendered. eg a picker used to select a bug task assignee will
        have associated_object set to the bug task.
        """
        extra = PickerEntry()
        if hasattr(self.context, 'summary'):
            extra.description = self.context.summary
        display_api = ObjectImageDisplayAPI(self.context)
        extra.css = display_api.sprite_css()
        if extra.css is None:
            extra.css = 'sprite bullet'
        return extra


@adapter(IPerson)
class PersonPickerEntryAdapter(DefaultPickerEntryAdapter):
    """Adapts IPerson to IPickerEntry."""

    def getPickerEntry(self, associated_object):
        person = self.context
        extra = super(PersonPickerEntryAdapter, self).getPickerEntry(
            associated_object)
        # Display the person's Launchpad id next to their name.
        extra.title = "%s (~%s)" % (person.displayname, person.name)

        # If the person is affiliated with the associated_object then we can
        # display a badge.
        badge_name = IHasAffiliation(
            associated_object).getAffiliationBadge(person)
        if badge_name is not None:
            extra.image = "/@@/%s" % badge_name
        if person.preferredemail is not None:
            try:
                extra.description = person.preferredemail.email
            except Unauthorized:
                extra.description = '<email address hidden>'
    
        def ircnick_display_text(ircid):
            # First we shorten the full irc network to just the core network
            # name. eg irc.freenode.net -> freenode
            network = ircid.network
            irc_match = re.search(r'irc\.(.*)\..*', network)
            if irc_match:
                network = irc_match.group(1)
            # Then we return something like nic@network
            return "%s@%s" % (ircid.nickname, network)
    
        # We will display the person's irc nic(s) after their email address in
        # the description text.
        irc_nicks = None
        if person.ircnicknames:
            irc_nicks = ", ".join(
                [ircnick_display_text(ircid)for ircid in person.ircnicknames])
        if irc_nicks:
            extra.description = "%s (%s)" % (extra.description, irc_nicks)
        return extra


@adapter(IBranch)
class BranchPickerEntryAdapter(DefaultPickerEntryAdapter):
    """Adapts IBranch to IPickerEntry."""
    
    def getPickerEntry(self, associated_object):
        branch = self.context
        extra = super(BranchPickerEntryAdapter, self).getPickerEntry(
            associated_object)
        extra.description = branch.bzr_identity
        return extra


@adapter(ISourcePackageName)
class SourcePackageNamePickerEntryAdapter(DefaultPickerEntryAdapter):
    """Adapts ISourcePackageName to IPickerEntry."""

    def getPickerEntry(self, associated_object):
        sourcepackagename = self.context
        extra = super(
            SourcePackageNamePickerEntryAdapter, self).getPickerEntry(
                associated_object)
        descriptions = getSourcePackageDescriptions([sourcepackagename])
        extra.description = descriptions.get(
            sourcepackagename.name, "Not yet built")
        return extra


class HugeVocabularyJSONView:
    """Export vocabularies as JSON.

    This was needed by the Picker widget, but could be
    useful for other AJAX widgets.
    """
    DEFAULT_BATCH_SIZE = 10

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        name = self.request.form.get('name')
        if name is None:
            raise MissingInputError('name', '')

        search_text = self.request.form.get('search_text')
        if search_text is None:
            raise MissingInputError('search_text', '')

        try:
            factory = getUtility(IVocabularyFactory, name)
        except ComponentLookupError:
            raise UnexpectedFormData(
                'Unknown vocabulary %r' % name)

        vocabulary = factory(self.context)

        if IHugeVocabulary.providedBy(vocabulary):
            matches = vocabulary.searchForTerms(search_text)
            total_size = matches.count()
        else:
            matches = list(vocabulary)
            total_size = len(matches)

        batch_navigator = BatchNavigator(matches, self.request)

        result = []
        for term in batch_navigator.currentBatch():
            entry = dict(value=term.token, title=term.title)
            # The canonical_url without just the path (no hostname) can
            # be passed directly into the REST PATCH call.
            api_request = IWebServiceClientRequest(self.request)
            try:
                entry['api_uri'] = canonical_url(
                    term.value, request=api_request,
                    path_only_if_possible=True)
            except NoCanonicalUrl:
                # The exception is caught, because the api_url is only
                # needed for inplace editing via a REST call. The
                # form picker doesn't need the api_url.
                entry['api_uri'] = 'Could not find canonical url.'
            picker_entry = IPickerEntry(term.value).getPickerEntry(
                self.context)
            # The PickEntry adaptor may override the default title.
            if (hasattr(picker_entry, 'title') and
                picker_entry.title is not None):
                entry['title'] = picker_entry.title
            if picker_entry.description is not None:
                if len(picker_entry.description) > MAX_DESCRIPTION_LENGTH:
                    entry['description'] = (
                        picker_entry.description[:MAX_DESCRIPTION_LENGTH-3]
                        + '...')
                else:
                    entry['description'] = picker_entry.description
            if picker_entry.image is not None:
                entry['image'] = picker_entry.image
            if picker_entry.css is not None:
                entry['css'] = picker_entry.css
            result.append(entry)

        self.request.response.setHeader('Content-type', 'application/json')
        return simplejson.dumps(dict(total_size=total_size, entries=result))
