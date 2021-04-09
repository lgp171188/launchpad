# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import re

import requests
from six.moves.urllib.parse import (
    parse_qs,
    urlparse,
    urlunparse,
    )
import transaction
from zope.component import (
    getMultiAdapter,
    getUtility,
    )
from zope.publisher.interfaces import NotFound
from zope.security.interfaces import Unauthorized

from lp.bugs.browser.bugattachment import BugAttachmentFileNavigation
from lp.services.config import config
from lp.services.librarian.interfaces import ILibraryFileAliasWithParent
from lp.services.webapp.interfaces import (
    ILaunchBag,
    OAuthPermission,
    )
from lp.services.webapp.publisher import RedirectionView
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import (
    api_url,
    login_person,
    logout,
    TestCaseWithFactory,
    )
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.pages import (
    LaunchpadWebServiceCaller,
    webservice_for_person,
    )


class TestAccessToBugAttachmentFiles(TestCaseWithFactory):
    """Tests of traversal to and access of files of bug attachments."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestAccessToBugAttachmentFiles, self).setUp()
        self.bug_owner = self.factory.makePerson()
        getUtility(ILaunchBag).clear()
        login_person(self.bug_owner)
        self.bug = self.factory.makeBug(owner=self.bug_owner)
        self.bugattachment = self.factory.makeBugAttachment(
            owner=self.bug_owner, bug=self.bug, filename='foo.txt',
            data=b'file content')

    def test_traversal_to_lfa_of_bug_attachment(self):
        # Traversing to the URL provided by a ProxiedLibraryFileAlias of a
        # bug attachament returns a RedirectionView.
        request = LaunchpadTestRequest()
        request.setTraversalStack(['foo.txt'])
        navigation = BugAttachmentFileNavigation(
            self.bugattachment, request)
        view = navigation.publishTraverse(request, '+files')
        self.assertIsInstance(view, RedirectionView)

    def test_traversal_to_lfa_of_bug_attachment_wrong_filename(self):
        # If the filename provided in the URL does not match the
        # filename of the LibraryFileAlias, a NotFound error is raised.
        request = LaunchpadTestRequest()
        request.setTraversalStack(['nonsense'])
        navigation = BugAttachmentFileNavigation(self.bugattachment, request)
        self.assertRaises(
            NotFound, navigation.publishTraverse, request, '+files')

    def test_access_to_unrestricted_file(self):
        # Requests of unrestricted files are redirected to Librarian URLs.
        request = LaunchpadTestRequest()
        request.setTraversalStack(['foo.txt'])
        navigation = BugAttachmentFileNavigation(
            self.bugattachment, request)
        view = navigation.publishTraverse(request, '+files')
        mo = re.match(r'^http://.*/\d+/foo.txt$', view.target)
        self.assertIsNot(None, mo)

    def test_access_to_restricted_file(self):
        # Requests of restricted files are redirected to librarian URLs
        # with tokens.
        lfa_with_parent = getMultiAdapter(
            (self.bugattachment.libraryfile, self.bugattachment),
            ILibraryFileAliasWithParent)
        lfa_with_parent.restricted = True
        self.bug.setPrivate(True, self.bug_owner)
        transaction.commit()
        request = LaunchpadTestRequest()
        request.setTraversalStack(['foo.txt'])
        navigation = BugAttachmentFileNavigation(self.bugattachment, request)
        view = navigation.publishTraverse(request, '+files')
        mo = re.match(
            r'^https://.*.restricted.*/\d+/foo.txt\?token=.*$', view.target)
        self.assertIsNot(None, mo)

    def test_access_to_restricted_file_unauthorized(self):
        # If a user cannot access the bug attachment itself, they cannot
        # access the restricted Librarian file either.
        lfa_with_parent = getMultiAdapter(
            (self.bugattachment.libraryfile, self.bugattachment),
            ILibraryFileAliasWithParent)
        lfa_with_parent.restricted = True
        self.bug.setPrivate(True, self.bug_owner)
        transaction.commit()
        user = self.factory.makePerson()
        login_person(user)
        self.assertRaises(Unauthorized, getattr, self.bugattachment, 'title')
        request = LaunchpadTestRequest()
        request.setTraversalStack(['foo.txt'])
        navigation = BugAttachmentFileNavigation(self.bugattachment, request)
        self.assertRaises(
            Unauthorized, navigation.publishTraverse, request, '+files')


class TestWebserviceAccessToBugAttachmentFiles(TestCaseWithFactory):
    """Tests access to bug attachments via the webservice."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestWebserviceAccessToBugAttachmentFiles, self).setUp()
        self.bug_owner = self.factory.makePerson()
        getUtility(ILaunchBag).clear()
        login_person(self.bug_owner)
        self.bug = self.factory.makeBug(owner=self.bug_owner)
        self.factory.makeBugAttachment(
            bug=self.bug, filename='foo.txt', data=b'file content')
        self.bug_url = api_url(self.bug)

    def test_anon_access_to_public_bug_attachment(self):
        # Attachments of public bugs can be accessed by anonymous users.
        logout()
        webservice = LaunchpadWebServiceCaller(
            'test', '', default_api_version='devel')
        ws_bug = self.getWebserviceJSON(webservice, self.bug_url)
        ws_bug_attachment = self.getWebserviceJSON(
            webservice, ws_bug['attachments_collection_link'])['entries'][0]
        response = webservice.get(ws_bug_attachment['data_link'])
        self.assertEqual(303, response.status)
        response = requests.get(response.getHeader('Location'))
        response.raise_for_status()
        self.assertEqual(b'file content', response.content)

    def test_user_access_to_private_bug_attachment(self):
        # Users having access to private bugs can also read attachments
        # of these bugs.
        self.bug.setPrivate(True, self.bug_owner)
        other_user = self.factory.makePerson()
        webservice = webservice_for_person(
            self.bug_owner, permission=OAuthPermission.READ_PRIVATE)
        ws_bug = self.getWebserviceJSON(webservice, self.bug_url)
        ws_bug_attachment = self.getWebserviceJSON(
            webservice, ws_bug['attachments_collection_link'])['entries'][0]
        response = webservice.get(ws_bug_attachment['data_link'])
        self.assertEqual(303, response.status)

        # The Librarian URL has, for our test case, the form
        # "https://NNNN.restricted.launchpad.test:PORT/NNNN/foo.txt?token=..."
        # where NNNN and PORT are integers.
        parsed_url = urlparse(response.getHeader('Location'))
        self.assertEqual('https', parsed_url.scheme)
        mo = re.search(
            r'^i\d+\.restricted\..+:\d+$', parsed_url.netloc)
        self.assertIsNot(None, mo, parsed_url.netloc)
        mo = re.search(r'^/\d+/foo\.txt$', parsed_url.path)
        self.assertIsNot(None, mo)
        params = parse_qs(parsed_url.query)
        self.assertEqual(['token'], list(params))

        # Our test environment does not support wildcard DNS.  Work around
        # this.
        librarian_netloc = '%s:%d' % (
            config.librarian.download_host, config.librarian.download_port)
        url = urlunparse(
            ('http', librarian_netloc, parsed_url.path, parsed_url.params,
             parsed_url.query, parsed_url.fragment))
        response = requests.get(url, headers={'Host': parsed_url.netloc})
        response.raise_for_status()
        self.assertEqual(b'file content', response.content)

        # If a user which cannot access the private bug itself tries to
        # to access the attachment, we deny its existence.
        other_webservice = webservice_for_person(
            other_user, permission=OAuthPermission.READ_PRIVATE)
        response = other_webservice.get(ws_bug_attachment['data_link'])
        self.assertEqual(404, response.status)
