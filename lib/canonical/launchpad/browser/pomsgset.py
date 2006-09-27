# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'POMsgSetIndexView',
    'POMsgSetView',
    'POMsgSetPageView',
    'POMsgSetFacets',
    'POMsgSetAppMenus',
    'POMsgSetSubmissions',
    'POMsgSetZoomedView',
    ]

import re
import operator
import gettextpo
from math import ceil
from xml.sax.saxutils import escape as xml_escape

from zope.app.form import CustomWidgetFactory
from zope.app.form.utility import setUpWidgets
from zope.app.form.browser import DropdownWidget
from zope.app.form.interfaces import IInputWidget
from zope.component import getUtility, getView
from zope.interface import implements

from canonical.cachedproperty import cachedproperty
from canonical.launchpad import helpers
from canonical.launchpad.interfaces import (
    UnexpectedFormData, IPOMsgSet, TranslationConstants, NotFoundError,
    ILanguageSet, IPOFileAlternativeLanguage, IPOMsgSetSubmissions)
from canonical.launchpad.webapp import (
    StandardLaunchpadFacets, ApplicationMenu, Link, LaunchpadView,
    canonical_url)
from canonical.launchpad.webapp import urlparse
from canonical.launchpad.webapp.batching import BatchNavigator


#
# Translation-related formatting functions
#

def contract_rosetta_tabs(text):
    """Replace Rosetta representation of tab characters with their native form."""
    return helpers.text_replaced(text, {'[tab]': '\t', r'\[tab]': '[tab]'})


def expand_rosetta_tabs(unicode_text):
    """Replace tabs with their Rosetta representation."""
    return helpers.text_replaced(unicode_text, {u'\t': u'[tab]', u'[tab]': ur'\[tab]'})


def msgid_html(text, flags, space=TranslationConstants.SPACE_CHAR,
               newline=TranslationConstants.NEWLINE_CHAR):
    r"""Convert a message ID to a HTML representation."""
    lines = []

    # Replace leading and trailing spaces on each line with special markup.
    for line in xml_escape(text).split('\n'):
        # Pattern:
        # - group 1: zero or more spaces: leading whitespace
        # - group 2: zero or more groups of (zero or
        #   more spaces followed by one or more non-spaces): maximal string
        #   which doesn't begin or end with whitespace
        # - group 3: zero or more spaces: trailing whitespace
        match = re.match('^( *)((?: *[^ ]+)*)( *)$', line)

        if match:
            lines.append(
                space * len(match.group(1)) +
                match.group(2) +
                space * len(match.group(3)))
        else:
            raise AssertionError(
                "A regular expression that should always match didn't.")

    if 'c-format' in flags:
        # Replace c-format sequences with marked-up versions. If there is a
        # problem parsing the c-format sequences on a particular line, that
        # line is left unformatted.
        for i in range(len(lines)):
            formatted_line = ''

            try:
                segments = parse_cformat_string(lines[i])
            except UnrecognisedCFormatString:
                continue

            for segment in segments:
                type, content = segment

                if type == 'interpolation':
                    formatted_line += ('<code>%s</code>' % content)
                elif type == 'string':
                    formatted_line += content

            lines[i] = formatted_line

    # Replace newlines and tabs with their respective representations.
    html = expand_rosetta_tabs(newline.join(lines))
    html = helpers.text_replaced(html, {
        '[tab]': TranslationConstants.TAB_CHAR,
        r'\[tab]': TranslationConstants.TAB_CHAR_ESCAPED
        })
    return html


def convert_newlines_to_web_form(unicode_text):
    """Convert an Unicode text from any newline style to the one used on web
    forms, that's the Windows style ('\r\n')."""

    assert isinstance(unicode_text, unicode), (
        "The given text must be unicode instead of %s" % type(unicode_text))

    if unicode_text is None:
        return None
    elif u'\r\n' in unicode_text:
        # The text is already using the windows newline chars
        return unicode_text
    elif u'\n' in unicode_text:
        return helpers.text_replaced(unicode_text, {u'\n': u'\r\n'})
    else:
        return helpers.text_replaced(unicode_text, {u'\r': u'\r\n'})


def count_lines(text):
    '''Count the number of physical lines in a string. This is always at least
    as large as the number of logical lines in a string.'''
    CHARACTERS_PER_LINE = 50
    count = 0

    for line in text.split('\n'):
        if len(line) == 0:
            count += 1
        else:
            count += int(ceil(float(len(line)) / CHARACTERS_PER_LINE))

    return count


def parse_cformat_string(string):
    """Parse a printf()-style format string into a sequence of interpolations
    and non-interpolations."""

    # The sequence '%%' is not counted as an interpolation. Perhaps splitting
    # into 'special' and 'non-special' sequences would be better.

    # This function works on the basis that s can be one of three things: an
    # empty string, a string beginning with a sequence containing no
    # interpolations, or a string beginning with an interpolation.

    segments = []
    end = string
    plain_re = re.compile('(%%|[^%])+')
    interpolation_re = re.compile('%[^diouxXeEfFgGcspmn]*[diouxXeEfFgGcspmn]')

    while end:
        # Check for a interpolation-less prefix.

        match = plain_re.match(end)

        if match:
            segment = match.group(0)
            segments.append(('string', segment))
            end = end[len(segment):]
            continue

        # Check for an interpolation sequence at the beginning.

        match = interpolation_re.match(end)

        if match:
            segment = match.group(0)
            segments.append(('interpolation', segment))
            end = end[len(segment):]
            continue

        # Give up.
        raise UnrecognisedCFormatString(string)

    return segments

#
# Exceptions and helper classes
#

class UnrecognisedCFormatString(ValueError):
    """Exception raised when a string containing C format sequences can't be
    parsed."""


class POTMsgSetBatchNavigator(BatchNavigator):

    def __init__(self, results, request, start=0, size=1):
        """Constructs a BatchNavigator instance.

        results is an iterable of results. request is the web request
        being processed. size is a default batch size which the callsite
        can choose to provide.
        """
        schema, netloc, path, parameters, query, fragment = (
            urlparse(str(request.URL)))

        # For safety, delete the start and batch variables, if they
        # appear in the URL. The situation in which 'start' appears
        # today is when the alternative language form is posted back and
        # includes it.
        if 'start' in request:
            del request.form['start']
        if 'batch' in request.form:
            del request.form['batch']
        # 'path' will be like: 'POTURL/LANGCODE/POTSEQUENCE/+translate' and
        # we are interested on the POTSEQUENCE.
        self.start_path, pot_sequence, self.page = path.rsplit('/', 2)
        try:
            # The URLs we use to navigate thru POTMsgSet objects start with 1,
            # while the batching machinery starts with 0, that's why we need
            # to remove '1'.
            start_value = int(pot_sequence) - 1
        except ValueError:
            start_value = start

        # This batch navigator class only supports batching of 1 element.
        size = 1

        BatchNavigator.__init__(self, results, request, start_value, size)

    def generateBatchURL(self, batch):
        """Return a custom batch URL for IPOMsgSet's views."""
        url = ""
        if batch is None:
            return url

        assert batch.size == 1, 'The batch size must be 1.'

        sequence = batch.startNumber()
        url = '/'.join([self.start_path, str(sequence), self.page])
        qs = self.request.environment.get('QUERY_STRING', '')
        # cleanQueryString ensures we get rid of any bogus 'start' or
        # 'batch' form variables we may have received via the URL.
        qs = self.cleanQueryString(qs)
        if qs:
            # There are arguments that we should preserve.
            url = '%s?%s' % (url, qs)
        return url


class CustomDropdownWidget(DropdownWidget):

    def _div(self, cssClass, contents, **kw):
        """Render the select widget without the div tag."""
        return contents

#
# Standard UI classes
#

class POMsgSetFacets(StandardLaunchpadFacets):
    usedfor = IPOMsgSet
    defaultlink = 'translations'
    enable_only = ['overview', 'translations']

    def _parent_url(self):
        """Return the URL of the thing the PO template of this PO file is
        attached to.
        """
        potemplate = self.context.pofile.potemplate
        if potemplate.distrorelease:
            source_package = potemplate.distrorelease.getSourcePackage(
                potemplate.sourcepackagename)
            return canonical_url(source_package)
        else:
            return canonical_url(potemplate.productseries)

    def overview(self):
        target = self._parent_url()
        text = 'Overview'
        return Link(target, text)

    def translations(self):
        target = '+translate'
        text = 'Translations'
        return Link(target, text)


class POMsgSetAppMenus(ApplicationMenu):
    usedfor = IPOMsgSet
    facet = 'translations'
    links = ['overview', 'translate', 'switchlanguages',
             'upload', 'download', 'viewtemplate']

    def overview(self):
        text = 'Overview'
        return Link('../', text)

    def translate(self):
        text = 'Translate many'
        return Link('../+translate', text, icon='languages')

    def switchlanguages(self):
        text = 'Switch Languages'
        return Link('../../', text, icon='languages')

    def upload(self):
        text = 'Upload a File'
        return Link('../+upload', text, icon='edit')

    def download(self):
        text = 'Download'
        return Link('../+export', text, icon='download')

    def viewtemplate(self):
        text = 'View Template'
        return Link('../../', text, icon='languages')

#
# Views
#

class POMsgSetIndexView:
    """A view to forward to the translation form."""

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        """Redirect to the translation form."""
        url = '%s/%s' % (canonical_url(self.context), '+translate')
        self.request.response.redirect(url)


class BaseTranslationView(LaunchpadView):
    """XXX"""

    # There will never be 100 plural forms.  Usually, we'll be iterating
    # over just two or three.
    MAX_PLURAL_FORMS = 100

    class TabIndex:
        """XXX"""
        def __init__(self):
            self.index = 0

        def next(self):
            self.index += 1
            return self.index

    def initialize(self):
        assert self.pofile, "Child class must define self.pofile"

        if not self.pofile.canEditTranslations(self.user):
            # The user is not an official translator, we should show a
            # warning.
            self.request.response.addWarningNotification("""
                You are not an official translator for this file. You
                can still make suggestions, and your translations will
                be stored and reviewed for acceptance later by the
                designated translators.""")

        self.redirecting = False
        self.tabindex = self.TabIndex()
        # XXX: describe how these work
        self.form_posted_translations = {}
        self.form_posted_needsreview = {}

        if not self.has_plural_form_information:
            # Cannot translate this IPOFile without the plural form
            # information. Show the info to add it to our system.
            self.request.response.addErrorNotification("""
            <p>
            Rosetta can&#8217;t handle the plural items in this file, because it
            doesn&#8217;t yet know how plural forms work for %s.
            </p>
            <p>
            To fix this, please e-mail the <a
            href="mailto:rosetta-users@lists.ubuntu.com">Rosetta users mailing list</a>
            with this information, preferably in the format described in the
            <a href="https://wiki.ubuntu.com/RosettaFAQ">Rosetta FAQ</a>.
            </p>
            <p>
            This only needs to be done once per language. Thanks for helping Rosetta.
            </p>
            """ % self.pofile.language.englishname)
            return

        self._initializeAltLanguage()

        # XXX: why here, because of redirect in process_form
        self._initializeBatching()
        self.start = self.batchnav.start
        self.size = self.batchnav.currentBatch().size

        self._process_form()

    #
    # API Hooks
    #

    def _initializeBatching(self):
        """XXX"""
        raise NotImplementedError

    def _submit_translations(self):
        """XXX"""
        raise NotImplementedError

    #
    # Helper methods that should be used for POMsgSetView.prepare() and
    # _submit_translations().
    #

    def _store_translations(self, pomsgset):
        """XXX"""
        self._extract_form_posted_translations(pomsgset)
        translations = self.form_posted_translations[pomsgset]
        if not translations:
            # A post with no content -- nothing to be done. I'm not sure
            # this could be an UnexpectedFormData..
            return None
        is_fuzzy = self.form_posted_needsreview.get(pomsgset, False)

        try:
            pomsgset.updateTranslationSet(person=self.user,
                new_translations=translations, fuzzy=is_fuzzy, published=False)
        except gettextpo.error, e:
            # Save the error message gettext gave us to show it to the
            # user.
            return str(e)
        else:
            return None

    def _prepareView(self, pomsgset_view, pomsgset, error):
        """XXX"""
        # XXX: we should try and assert this method is not called before _process_form
        if self.form_posted_translations.has_key(pomsgset):
            translations = self.form_posted_translations[pomsgset]
        else:
            translations = pomsgset.active_texts
        if self.form_posted_needsreview.has_key(pomsgset):
            is_fuzzy = self.form_posted_needsreview[pomsgset]
        else:
            is_fuzzy = pomsgset.isfuzzy
        pomsgset_view.prepare(translations, is_fuzzy, error, self.tabindex,
                              self.second_lang_code)

    #
    # Internals
    #

    def _initializeAltLanguage(self):
        """XXX"""
        initial_values = {}
        second_lang_code = self.request.form.get("field.alternative_language")
        if second_lang_code:
            if isinstance(second_lang_code, list):
                raise UnexpectedFormData("You specified more than one alternative "
                                         "languages; only one is currently "
                                         "supported.")
            try:
                alternative_language = getUtility(ILanguageSet)[second_lang_code]
            except NotFoundError:
                pass
            else:
                initial_values['alternative_language'] = alternative_language

        self.alternative_language_widget = CustomWidgetFactory(CustomDropdownWidget)
        setUpWidgets(
            self, IPOFileAlternativeLanguage, IInputWidget,
            names=['alternative_language'], initial=initial_values)

        if not second_lang_code and self.pofile.language.alt_suggestion_language:
            # If there's a standard suggested language and no other
            # language was provided, show it off.
            # XXX: this is actually half-wrong, since it will appear
            # selected in the dropdown in subsequent pages. We'd need to
            # store the alternate_language separately to deal with
            # this..
            second_lang_code = self.pofile.language.alt_suggestion_language.code

        # We store second_lang_code for use in hidden inputs in the
        # other forms in the translation pages.
        self.second_lang_code = second_lang_code

    @property
    def has_plural_form_information(self):
        """Return whether we know the plural forms for this language."""
        if self.pofile.potemplate.hasPluralMessage():
            return self.pofile.language.pluralforms is not None
        # If there are no plural forms, we assume that we have the
        # plural form information for this language.
        return True

    def _process_form(self):
        if self.request.method != 'POST' or self.user is None:
            # The form was not submitted or the user is not logged in.
            return
        self._submit_translations()

    def _extract_form_posted_translations(self, pomsgset):
        """Parse the form submitted to the translation widget looking for
        translations.

        Store the new translations at self.form_posted_translations and its
        status at self.form_posted_needsreview.

        In this method, we look for various keys in the form, and use them as
        follows:

        - 'msgset_ID' to know if self is part of the submitted form. If it
          isn't found, we stop parsing the form and return.
        - 'msgset_ID_LANGCODE_translation_PLURALFORM': Those will be the
          submitted translations and we will have as many entries as plural
          forms the language self.context.language has.
        - 'msgset_ID_LANGCODE_needsreview': If present, will note that the
          'needs review' flag has been set for the given translations.

        In all those form keys, 'ID' is the ID of the POTMsgSet.
        """
        potmsgset_ID = pomsgset.potmsgset.id
        language_code = pomsgset.pofile.language.code

        msgset_ID = 'msgset_%d' % potmsgset_ID
        if msgset_ID not in self.request.form:
            # If this form does not have data about the msgset id, then
            # do nothing at all.
            return

        msgset_ID_LANGCODE_needsreview = 'msgset_%d_%s_needsreview' % (
            potmsgset_ID, language_code)

        self.form_posted_needsreview[pomsgset] = (
            msgset_ID_LANGCODE_needsreview in self.request.form)

        # Note the trailing underscore: we append the plural form number later.
        msgset_ID_LANGCODE_translation_ = 'msgset_%d_%s_translation_' % (
            potmsgset_ID, language_code)

        # Extract the translations from the form, and store them in
        # self.form_posted_translations. We try plural forms in turn,
        # starting at 0.
        for pluralform in xrange(self.MAX_PLURAL_FORMS):
            msgset_ID_LANGCODE_translation_PLURALFORM = '%s%s' % (
                msgset_ID_LANGCODE_translation_, pluralform)
            if msgset_ID_LANGCODE_translation_PLURALFORM not in self.request.form:
                # Stop when we reach the first plural form which is
                # missing from the form.
                break

            raw_value = self.request.form[msgset_ID_LANGCODE_translation_PLURALFORM]
            value = contract_rosetta_tabs(raw_value)

            if not self.form_posted_translations.has_key(pomsgset):
                self.form_posted_translations[pomsgset] = {}
            self.form_posted_translations[pomsgset][pluralform] = value
        else:
            raise AssertionError("More than 100 plural forms were submitted!")

    #
    # Redirection
    #

    def _buildRedirectParams(self):
        parameters = {}
        if self.second_lang_code:
            parameters['field.alternative_language'] = self.second_lang_code
        return parameters

    def _redirect(self, new_url):
        """Redirect to the given url adding the selected filtering rules."""
        assert new_url is not None, ('The new URL cannot be None.')
        if not new_url:
            new_url = str(self.request.URL)
            if self.request.get('QUERY_STRING'):
                new_url += '?%s' % self.request.get('QUERY_STRING')
        self.redirecting = True

        parameters = self._buildRedirectParams()
        params_str = '&'.join(
            ['%s=%s' % (key, value) for key, value in parameters.items()])
        if params_str:
            if '?' not in new_url:
                new_url += '?'
            else:
                new_url += '&'
            new_url += params_str

        self.request.response.redirect(new_url)

    def _redirectToNextPage(self):
        # update the statistics for this po file
        # XXX: performance issue?
        self.pofile.updateStatistics()

        next_url = self.batchnav.nextBatchURL()
        if next_url is None or next_url == '':
            # We are already at the end of the batch, forward to the
            # first one.
            next_url = self.batchnav.firstBatchURL()
        if next_url is None:
            # Stay in whatever URL we are atm.
            next_url = ''
        self._redirect(next_url)

    def render(self):
        if self.redirecting:
            return u''
        else:
            return LaunchpadView.render(self)


class POMsgSetPageView(BaseTranslationView):
    """A view for the page that renders a single translation."""
    __used_for__ = IPOMsgSet
    def initialize(self):
        self.pofile = self.context.pofile
        # XXX: describe
        self.error = None
        BaseTranslationView.initialize(self)
        self.pomsgset_view = getView(self.context, "+translate-one-zoomed",
                                     self.request)
        self._prepareView(self.pomsgset_view, self.context, self.error)

    #
    # BaseTranslationView API
    #

    def _initializeBatching(self):
        # Setup the batching for this page.
        self.batchnav = POTMsgSetBatchNavigator(self.pofile.potemplate.getPOTMsgSets(),
                                                self.request, size=1)

    def _submit_translations(self):
        """Handle a form submission for the translation form.

        The form contains translations, some of which will be unchanged, some
        of which will be modified versions of old translations and some of
        which will be new. Returns a dictionary mapping sequence numbers to
        submitted message sets, where each message set will have information
        on any validation errors it has.
        """
        self.error = self._store_translations(self.context)

        # This page is being rendered as a single message view.
        if self.error:
            self.request.response.addErrorNotification(
                "There is an error in the translation you provided. "
                "Please correct it before continuing.")
        else:
            self._redirectToNextPage()


class POMsgSetView(LaunchpadView):
    """Holds all data needed to show an IPOMsgSet.

    This view class could be used directly or as part of the POFileView class
    in which case, we would have up to 100 instances of this class using the
    same information at self.form.
    """

    __used_for__ = IPOMsgSet

    # self.translations
    # self.error
    # self.sec_lang
    # self.second_lang_potmsgset
    # self.msgids
    # self.submission_blocks
    # self.translation_range

    def prepare(self, translations, is_fuzzy, error, tabindex, second_lang_code):
        self.translations = translations
        self.error = error
        self.is_fuzzy = is_fuzzy
        self.tabindex = tabindex

        # Set up alternative language variables. These could be 
        self.sec_lang = None
        self.second_lang_potmsgset = None
        if second_lang_code is not None:
            potemplate = self.context.pofile.potemplate
            second_lang_pofile = potemplate.getPOFileByLang(second_lang_code)
            if second_lang_pofile:
                self.sec_lang = second_lang_pofile.language
                msgid = self.context.potmsgset.primemsgid_.msgid
                try:
                    self.second_lang_potmsgset = second_lang_pofile[msgid].potmsgset
                except NotFoundError:
                    pass

    def initialize(self):
        # XXX: to avoid the use of python in the view, we'd need objects
        # to hold the data representing a pomsgset translation for a
        # plural form.
        # XXX: document this builds translations, msgids and suggestions
        self.msgids = helpers.shortlist(self.context.potmsgset.getPOMsgIDs())
        assert len(self.msgids) > 0, (
            'Found a POTMsgSet without any POMsgIDSighting')

        self.submission_blocks = {}
        # XXX: s/translation_range/pluralform_indexes/
        self.translation_range = range(len(self.translations))
        for index in self.translation_range:
            wiki, elsewhere, suggested, alt_submissions = self._buildAllSubmissions(index)
            self.submission_blocks[index] = [wiki, elsewhere, suggested, alt_submissions]

    def _buildAllSubmissions(self, index):
        active = set([self.translations[index]])
        wiki = set(self.context.getWikiSubmissions(index))
        current = set(self.context.getCurrentSubmissions(index))
        suggested = set(self.context.getSuggestedSubmissions(index))

        if self.is_multi_line:
            title = "Suggestions"
        else:
            title = "Suggestion"
        wiki = wiki - current - suggested - active
        wiki = self._buildSubmissions(title, wiki)

        elsewhere = current - suggested - active
        elsewhere = self._buildSubmissions("Used elsewhere", elsewhere)

        suggested = self._buildSubmissions("Suggested elsewhere", suggested) 

        if self.second_lang_potmsgset is None:
            alt_submissions = []
            title = None
        else:
            alt_submissions = self.second_lang_potmsgset.getCurrentSubmissions(
                self.sec_lang, index)
            title = self.sec_lang.englishname

        alt_submissions = self._buildSubmissions(title, alt_submissions)
        return wiki, elsewhere, suggested, alt_submissions

    def _buildSubmissions(self, title, submissions):
        submissions = sorted(submissions, key=operator.attrgetter("datecreated"),
                             reverse=True)
        return POMsgSetSubmissions(title, submissions[:self.max_entries],
                                   self.is_multi_line, self.max_entries)

    def generateNextTabIndex(self):
        """Return the tab index value to navigate the form."""
        self._table_index_value += 1
        return self._table_index_value

    def getTranslation(self, index):
        """Return the active translation for the pluralform 'index'.

        There are as many translations as the plural form information defines
        for that language/pofile. If one of those translations does not
        exists, it will have a None value. If the potmsgset is not a plural
        form one, we only have one entry.
        """
        if index in self.translation_range:
            translation = self.translations[index]
            # We store newlines as '\n', '\r' or '\r\n', depending on the
            # msgid but forms should have them as '\r\n' so we need to change
            # them before showing them.
            if translation is not None:
                return convert_newlines_to_web_form(translation)
            else:
                return None
        else:
            raise IndexError('Translation out of range')

    #
    # Display-related methods
    #

    @cachedproperty
    def is_plural(self):
        """Return whether there are plural forms."""
        return len(self.msgids) > 1

    @cachedproperty
    def max_lines_count(self):
        """Return the max number of lines a multiline entry will have

        It will never be bigger than 12.
        """
        if self.is_plural:
            singular_lines = count_lines(
                self.msgids[TranslationConstants.SINGULAR_FORM].msgid)
            plural_lines = count_lines(
                self.msgids[TranslationConstants.PLURAL_FORM].msgid)
            lines = max(singular_lines, plural_lines)
        else:
            lines = count_lines(
                self.msgids[TranslationConstants.SINGULAR_FORM].msgid)

        return min(lines, 12)

    @cachedproperty
    def is_multi_line(self):
        """Return whether the singular or plural msgid have more than one line.
        """
        return self.max_lines_count > 1

    @cachedproperty
    def sequence(self):
        """Return the position number of this potmsgset."""
        return self.context.potmsgset.sequence

    @cachedproperty
    def msgid(self):
        """Return a msgid string prepared to render in a web page."""
        msgid = self.msgids[TranslationConstants.SINGULAR_FORM].msgid
        return msgid_html(msgid, self.context.potmsgset.flags())

    @property
    def msgid_plural(self):
        """Return a msgid plural string prepared to render as a web page.

        If there is no plural form, return None.
        """
        if self.is_plural:
            msgid = self.msgids[TranslationConstants.PLURAL_FORM].msgid
            return msgid_html(msgid, self.context.potmsgset.flags())
        else:
            return None

    # XXX 20060915 mpt: Detecting tabs, newlines, and leading/trailing spaces
    # is being done one way here, and another way in the functions above.
    @property
    def msgid_has_tab(self):
        """Determine whether any of the messages contain tab characters."""
        for msgid in self.msgids:
            if '\t' in msgid.msgid:
                return True
        return False

    @property
    def msgid_has_newline(self):
        """Determine whether any of the messages contain newline characters."""
        for msgid in self.msgids:
            if '\n' in msgid.msgid:
                return True
        return False

    @property
    def msgid_has_leading_or_trailing_space(self):
        """Determine whether any messages contain leading or trailing spaces."""
        for msgid in self.msgids:
            for line in msgid.msgid.splitlines():
                if line.startswith(' ') or line.endswith(' '):
                    return True
        return False

    @property
    def source_comment(self):
        """Return the source code comments for this IPOMsgSet."""
        return self.context.potmsgset.sourcecomment

    @property
    def comment(self):
        """Return the translator comments for this IPOMsgSet."""
        return self.context.commenttext

    @property
    def file_references(self):
        """Return the file references for this IPOMsgSet."""
        return self.context.potmsgset.filereferences

    @cachedproperty
    def zoom_url(self):
        """Return the URL where we should from the zoom icon."""
        # XXX: preserve second_lang_code and other form parameters?
        return '/'.join([canonical_url(self.context), '+translate'])

    @cachedproperty
    def zoom_alt(self):
        return 'View all details of this message'

    @cachedproperty
    def zoom_icon(self):
        return '/@@/zoom-in'

    @cachedproperty
    def max_entries(self):
        """Return the max number of entries to show as suggestions.

        If there is no limit, we return None.
        """
        return 3


class POMsgSetZoomedView(POMsgSetView):
    """XXX"""
    @cachedproperty
    def zoom_url(self):
        # We are viewing this class directly from an IPOMsgSet, we should
        # point to the parent batch of messages.
        # XXX: preserve second_lang_code and other form parameters?
        pofile_batch_url = '+translate?start=%d' % (self.sequence - 1)
        return '/'.join([canonical_url(self.context.pofile), pofile_batch_url])

    @cachedproperty
    def zoom_alt(self):
        return 'Return to multiple messages view.'

    @cachedproperty
    def zoom_icon(self):
        return '/@@/zoom-out'

    @cachedproperty
    def max_entries(self):
        return None


class POMsgSetSubmissions(LaunchpadView):
    """XXX"""
    implements(IPOMsgSetSubmissions)
    def __init__(self, title, submissions, is_multi_line, max_entries):
        self.title = title
        self.submissions = submissions
        self.is_multi_line = is_multi_line
        self.max_entries = max_entries

