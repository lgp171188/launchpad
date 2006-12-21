
import datetime
import os
import pytz
import shutil
import tempfile
import unittest

from zope.component import getUtility

from canonical.launchpad.interfaces import (
    IEmailAddressSet, IPersonSet, IProductSet)
from canonical.launchpad.scripts import bugimport
from canonical.launchpad.scripts.bugimport import ET
from canonical.lp.dbschema import (
    BugTaskImportance, BugTaskStatus, BugAttachmentType,
    PersonCreationRationale)

from canonical.testing import LaunchpadZopelessLayer
from canonical.launchpad.ftests import login, logout


class UtilsTestCase(unittest.TestCase):
    """Tests for the various utility functions used by the importer."""

    def test_parse_date(self):
        # None and empty string parse to None
        self.assertEqual(bugimport.parse_date(None), None)
        self.assertEqual(bugimport.parse_date(''), None)
        dt = bugimport.parse_date('2006-12-01T08:00:00Z')
        self.assertEqual(dt.year, 2006)
        self.assertEqual(dt.month, 12)
        self.assertEqual(dt.day, 1)
        self.assertEqual(dt.hour, 8)
        self.assertEqual(dt.minute, 0)
        self.assertEqual(dt.second, 0)
        self.assertEqual(dt.tzinfo, pytz.timezone('UTC'))

    def test_get_enum_value(self):
        from canonical.lp.dbschema import BugTaskStatus
        self.assertEqual(bugimport.get_enum_value(BugTaskStatus,
                                                  'FIXRELEASED'),
                         BugTaskStatus.FIXRELEASED)
        self.assertRaises(bugimport.BugXMLSyntaxError,
                          bugimport.get_enum_value, BugTaskStatus,
                          'NO-SUCH-ENUM-VALUE')

    def test_get_element(self):
        node = ET.fromstring('''\
        <foo xmlns="https://launchpad.net/xmlns/2006/bugs">
          <bar>
            <baz/>
          </bar>
        </foo>''')
        self.assertEqual(bugimport.get_element(node, 'no-element'), None)
        subnode = bugimport.get_element(node, 'bar')
        self.assertNotEqual(subnode, None)
        self.assertEqual(subnode.tag,
                         '{https://launchpad.net/xmlns/2006/bugs}bar')
        subnode = bugimport.get_element(node, 'bar/baz')
        self.assertNotEqual(subnode, None)
        self.assertEqual(subnode.tag,
                         '{https://launchpad.net/xmlns/2006/bugs}baz')

    def test_get_value(self):
        node = ET.fromstring('''\
        <foo xmlns="https://launchpad.net/xmlns/2006/bugs">
          <bar>   value 1</bar>
          <tag>
            <baz>
              value 2
            </baz>
          </tag>
        </foo>''')
        self.assertEqual(bugimport.get_value(node, 'no-element'), None)
        self.assertEqual(bugimport.get_value(node, 'bar'), 'value 1')
        self.assertEqual(bugimport.get_value(node, 'tag/baz'), 'value 2')

    def test_get_all(self):
        node = ET.fromstring('''\
        <foo xmlns="https://launchpad.net/xmlns/2006/bugs">
          <bar/>
          <bar/>
          <something>
            <bar/>
          </something>
        </foo>''')
        self.assertEqual(bugimport.get_all(node, 'no-element'), [])
        # get_all() only returns the direct children
        self.assertEqual(len(bugimport.get_all(node, 'bar')), 2)
        self.assertEqual(len(bugimport.get_all(node, 'something/bar')), 1)
        # list items are bar elements:
        self.assertEqual(bugimport.get_all(node, 'bar')[0].tag,
                         '{https://launchpad.net/xmlns/2006/bugs}bar')
        

class GetPersonTestCase(unittest.TestCase):
    """Tests for the BugImporter.getPerson() method."""
    layer = LaunchpadZopelessLayer

    def test_create_person(self):
        # Test that person creation works
        person = getUtility(IPersonSet).getByEmail('foo@example.com')
        self.assertEqual(person, None)

        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle')
        personnode = ET.fromstring('''\
        <person xmlns="https://launchpad.net/xmlns/2006/bugs"
                name="foo" email="foo@example.com">Foo User</person>''')
        person = importer.getPerson(personnode)
        self.assertNotEqual(person, None)
        self.assertEqual(person.name, 'foo')
        self.assertEqual(person.displayname, 'Foo User')
        self.assertEqual(person.guessedemails.count(), 1)
        self.assertEqual(person.guessedemails[0].email,
                         'foo@example.com')
        self.assertEqual(person.creation_rationale,
                         PersonCreationRationale.BUGIMPORT)
        self.assertEqual(person.creation_comment,
            'when importing bugs for NetApplet')

    def test_create_person_conflicting_name(self):
        # we have a user called sabdfl
        person1 = getUtility(IPersonSet).getByName('sabdfl')
        self.assertNotEqual(person1, None)

        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle')
        personnode = ET.fromstring('''\
        <person xmlns="https://launchpad.net/xmlns/2006/bugs"
                name="sabdfl" email="foo@example.com">Foo User</person>''')
        person2 = importer.getPerson(personnode)
        self.assertNotEqual(person2, None)
        self.assertNotEqual(person1.id, person2.id)
        self.assertNotEqual(person2.name, 'sabdfl')

    def test_find_existing_person(self):
        person = getUtility(IPersonSet).getByEmail('foo@example.com')
        self.assertEqual(person, None)
        person, email = getUtility(IPersonSet).createPersonAndEmail(
            email='foo@example.com',
            rationale=PersonCreationRationale.OWNER_CREATED_LAUNCHPAD)
        self.assertNotEqual(person, None)

        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle')
        personnode = ET.fromstring('''\
        <person xmlns="https://launchpad.net/xmlns/2006/bugs"
                name="sabdfl" email="foo@example.com">Foo User</person>''')
        self.assertEqual(importer.getPerson(personnode), person)

    def test_nobody_person(self):
        # Test that BugImporter.getPerson() returns None where appropriate
        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle')
        self.assertEqual(importer.getPerson(None), None)
        personnode = ET.fromstring('''\
        <person xmlns="https://launchpad.net/xmlns/2006/bugs"
                name="nobody" />''')
        self.assertEqual(importer.getPerson(personnode), None)

    def test_verify_new_person(self):
        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle',
                                         verify_users=True)
        personnode = ET.fromstring('''\
        <person xmlns="https://launchpad.net/xmlns/2006/bugs"
                name="foo" email="foo@example.com">Foo User</person>''')
        person = importer.getPerson(personnode)
        self.assertNotEqual(person, None)
        self.assertNotEqual(person.preferredemail, None)
        self.assertEqual(person.preferredemail.email,
                         'foo@example.com')
        self.assertEqual(person.creation_rationale,
                         PersonCreationRationale.BUGIMPORT)
        self.assertEqual(person.creation_comment,
            'when importing bugs for NetApplet')

    def test_verify_existing_person(self):
        person = getUtility(IPersonSet).ensurePerson(
            'foo@example.com', None,
            PersonCreationRationale.OWNER_CREATED_LAUNCHPAD)
        self.assertEqual(person.preferredemail, None)

        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle',
                                         verify_users=True)
        personnode = ET.fromstring('''\
        <person xmlns="https://launchpad.net/xmlns/2006/bugs"
                name="foo" email="foo@example.com">Foo User</person>''')
        person = importer.getPerson(personnode)
        self.assertNotEqual(person.preferredemail, None)
        self.assertEqual(person.preferredemail.email,
                         'foo@example.com')

    def test_verify_doesnt_clobber_preferred_email(self):
        person = getUtility(IPersonSet).ensurePerson(
            'foo@example.com', None,
            PersonCreationRationale.OWNER_CREATED_LAUNCHPAD)
        email = getUtility(IEmailAddressSet).new('foo@preferred.com',
                                                 person.id)
        person.setPreferredEmail(email)
        self.assertEqual(person.preferredemail.email, 'foo@preferred.com')

        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle',
                                         verify_users=True)
        personnode = ET.fromstring('''\
        <person xmlns="https://launchpad.net/xmlns/2006/bugs"
                name="foo" email="foo@example.com">Foo User</person>''')
        person = importer.getPerson(personnode)
        self.assertNotEqual(person.preferredemail, None)
        self.assertEqual(person.preferredemail.email, 'foo@preferred.com')


class GetMilestoneTestCase(unittest.TestCase):
    """Tests for the BugImporter.getMilestone() method."""
    layer = LaunchpadZopelessLayer

    def test_create_milestone(self):
        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle')
        milestone = importer.getMilestone('foo-bar')
        self.assertEqual(milestone.name, 'foo-bar')
        self.assertEqual(milestone.product, product)
        self.assertEqual(milestone.productseries, product.development_focus)

    def test_use_existing_milestone(self):
        # looking up an existing milestone
        product = getUtility(IProductSet).getByName('firefox')
        one_point_zero = product.getMilestone('1.0')
        self.assertNotEqual(one_point_zero, None)
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle')
        milestone = importer.getMilestone('1.0')
        self.assertEqual(one_point_zero, milestone)


sample_bug = '''\
<bug xmlns="https://launchpad.net/xmlns/2006/bugs" id="42">
  <private>False</private>
  <security_related>True</security_related>
  <datecreated>2004-10-12T12:00:00Z</datecreated>
  <nickname>some-bug</nickname>
  <title>A test bug</title>
  <description>A modified bug description</description>
  <reporter name="foo" email="foo@example.com">Foo User</reporter>
  <status>CONFIRMED</status>
  <importance>HIGH</importance>
  <milestone>future</milestone>
  <assignee email="bar@example.com">Bar User</assignee>
  <urls>
    <url href="https://launchpad.net/">Launchpad</url>
  </urls>
  <cves>
    <cve>2005-2736</cve>
    <cve>2005-2737</cve>
  </cves>
  <tags>
    <tag>foo</tag>
    <tag>bar</tag>
  </tags>
  <subscriptions>
    <subscriber email="test@canonical.com">Sample Person</subscriber>
  </subscriptions>
  <comment>
    <sender name="foo" email="foo@example.com">Foo User</sender>
    <date>2004-10-12T12:00:00Z</date>
    <title>A test bug</title>
    <text>Original description</text>
    <attachment>
      <type>UNSPECIFIED</type>
      <filename>hello.txt</filename>
      <title>Hello</title>
      <mimetype>text/plain</mimetype>
      <contents>SGVsbG8gd29ybGQ=</contents>
    </attachment>
  </comment>
  <comment>
    <!-- anonymous comment -->
    <sender name="nobody"/>
    <date>2005-01-01T11:00:00Z</date>
    <text>A comment from an anonymous user</text>
  </comment>
  <comment>
    <sender email="mark@hbd.com">Mark Shuttleworth</sender>
    <date>2005-01-01T13:00:00Z</date>
    <text>A comment from mark about CVE-2005-2730</text>
    <attachment>
      <mimetype>application/octet-stream;key=value</mimetype>
      <contents>PGh0bWw+</contents>
    </attachment>
    <attachment>
      <type>PATCH</type>
      <filename>foo.patch</filename>
      <mimetype>text/html</mimetype>
      <contents>QSBwYXRjaA==</contents>
    </attachment>
  </comment>
</bug>'''

duplicate_bug = '''\
<bug xmlns="https://launchpad.net/xmlns/2006/bugs" id="100">
  <duplicateof>42</duplicateof>
  <datecreated>2004-10-12T12:00:00Z</datecreated>
  <title>A duplicate bug</title>
  <description>A duplicate description</description>
  <reporter name="foo" email="foo@example.com">Foo User</reporter>
  <status>CONFIRMED</status>
  <importance>LOW</importance>
  <comment>
    <sender name="foo" email="foo@example.com">Foo User</sender>
    <date>2004-10-12T12:00:00Z</date>
    <title>A duplicate bug</title>
    <text>A duplicate description</text>
  </comment>
</bug>'''

class ImportBugTestCase(unittest.TestCase):
    """Test importing of a bug from XML"""
    layer = LaunchpadZopelessLayer

    def setUp(self):
        login('bug-importer@launchpad.net')

    def tearDown(self):
        logout()

    def test_import_bug(self):
        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle',
                                         verify_users=True)
        bugnode = ET.fromstring(sample_bug)
        bug = importer.importBug(bugnode)

        self.assertNotEqual(bug, None)
        # check bug attributes
        self.assertEqual(bug.owner.preferredemail.email, 'foo@example.com')
        self.assertEqual(bug.datecreated.isoformat(),
                         '2004-10-12T12:00:00+00:00')
        self.assertEqual(bug.title, 'A test bug')
        self.assertEqual(bug.description, 'A modified bug description')
        self.assertEqual(bug.private, False)
        self.assertEqual(bug.security_related, True)
        self.assertEqual(bug.name, 'some-bug')
        self.assertEqual(bug.externalrefs.count(), 1)
        self.assertEqual(bug.externalrefs[0].url, 'https://launchpad.net/')
        self.assertEqual(bug.externalrefs[0].title, 'Launchpad')
        self.assertEqual(sorted(cve.sequence for cve in bug.cves),
                         ['2005-2730', '2005-2736', '2005-2737'])
        self.assertEqual(bug.tags, ['bar', 'foo'])
        self.assertEqual(len(bug.getDirectSubscribers()), 2)
        self.assertEqual(sorted(person.preferredemail.email
                                for person in bug.getDirectSubscribers()),
                         ['foo@example.com', 'test@canonical.com'])

        # There should only be one bug task (on netapplet):
        self.assertEqual(len(bug.bugtasks), 1)
        bugtask = bug.bugtasks[0]
        self.assertEqual(bugtask.product, product)
        self.assertEqual(bugtask.datecreated.isoformat(),
                         '2004-10-12T12:00:00+00:00')
        self.assertEqual(bugtask.importance, BugTaskImportance.HIGH)
        self.assertEqual(bugtask.status, BugTaskStatus.CONFIRMED)
        self.assertEqual(bugtask.assignee.preferredemail.email,
                         'bar@example.com')
        self.assertNotEqual(bugtask.milestone, None)
        self.assertEqual(bugtask.milestone.name, 'future')

        # there are three comments:
        self.assertEqual(bug.messages.count(), 3)
        message1 = bug.messages[0]
        message2 = bug.messages[1]
        message3 = bug.messages[2]

        # Message 1:
        self.assertEqual(message1.owner.preferredemail.email,
                         'foo@example.com')
        self.assertEqual(message1.datecreated.isoformat(),
                         '2004-10-12T12:00:00+00:00')
        self.assertEqual(message1.subject, 'A test bug')
        self.assertEqual(message1.text_contents, 'Original description')
        self.assertEqual(message1.bugattachments.count(), 1)
        attachment = message1.bugattachments[0]
        self.assertEqual(attachment.type, BugAttachmentType.UNSPECIFIED)
        self.assertEqual(attachment.title, 'Hello')
        self.assertEqual(attachment.libraryfile.filename, 'hello.txt')
        self.assertEqual(attachment.libraryfile.mimetype, 'text/plain')

        # Message 2:
        self.assertEqual(message2.owner.preferredemail.email,
                         'bug-importer@launchpad.net')
        self.assertEqual(message2.datecreated.isoformat(),
                         '2005-01-01T11:00:00+00:00')
        self.assertEqual(message2.subject, 'Re: A test bug')
        self.assertEqual(message2.text_contents,
                         'A comment from an anonymous user')

        # Message 3:
        self.assertEqual(message3.owner.preferredemail.email, 'mark@hbd.com')
        self.assertEqual(message3.datecreated.isoformat(),
                         '2005-01-01T13:00:00+00:00')
        self.assertEqual(message3.subject, 'Re: A test bug')
        self.assertEqual(message3.text_contents,
                         'A comment from mark about CVE-2005-2730')
        self.assertEqual(message3.bugattachments.count(), 2)
        # grab the attachments in the appropriate order
        [attachment1, attachment2] = list(message3.bugattachments)
        if attachment1.type == BugAttachmentType.PATCH:
            attachment1, attachment2 = attachment2, attachment1
        self.assertEqual(attachment1.type, BugAttachmentType.UNSPECIFIED)
        # default title and filename
        self.assertEqual(attachment1.title, 'unknown')
        self.assertEqual(attachment1.libraryfile.filename, 'unknown')
        # mime type guessed from content
        self.assertEqual(attachment1.libraryfile.mimetype, 'text/html')
        self.assertEqual(attachment2.type, BugAttachmentType.PATCH)
        # title defaults to filename
        self.assertEqual(attachment2.title, 'foo.patch')
        self.assertEqual(attachment2.libraryfile.filename, 'foo.patch')
        # mime type forced to text/plain because we have a patch
        self.assertEqual(attachment2.libraryfile.mimetype, 'text/plain')

    def test_duplicate_bug(self):
        # Process two bugs, the second being a duplicate of the first.
        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle',
                                         verify_users=True)
        bugnode = ET.fromstring(sample_bug)
        bug42 = importer.importBug(bugnode)
        self.assertNotEqual(bug42, None)

        bugnode = ET.fromstring(duplicate_bug)
        bug100 = importer.importBug(bugnode)
        self.assertNotEqual(bug100, None)

        self.assertEqual(bug100.duplicateof, bug42)

    def test_pending_duplicate_bug(self):
        # Same as above, but process the pending duplicate bug first.
        product = getUtility(IProductSet).getByName('netapplet')
        importer = bugimport.BugImporter(product, 'bugs.xml', 'bug-map.pickle',
                                         verify_users=True)
        bugnode = ET.fromstring(duplicate_bug)
        bug100 = importer.importBug(bugnode)
        self.assertNotEqual(bug100, None)
        self.assertTrue(42 in importer.pending_duplicates)
        self.assertEqual(importer.pending_duplicates[42], [bug100.id])

        bugnode = ET.fromstring(sample_bug)
        bug42 = importer.importBug(bugnode)
        self.assertNotEqual(bug42, None)
        # bug 42 removed from pending duplicates
        self.assertTrue(42 not in importer.pending_duplicates)

        self.assertEqual(bug100.duplicateof, bug42)        


class BugImportCacheTestCase(unittest.TestCase):
    """Test of bug mapping cache load/save routines."""
    layer = LaunchpadZopelessLayer

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_no_cache(self):
        # Test that loadCache() when no cache file exists resets the
        # bug ID map and pending duplicates lists.
        cache_filename = os.path.join(self.tmpdir, 'bug-map.pickle')
        self.assertFalse(os.path.exists(cache_filename))
        importer = bugimport.BugImporter(None, None, cache_filename)
        importer.bug_id_map = 'bogus'
        importer.pending_duplicates = 'bogus'
        importer.loadCache()
        self.assertEqual(importer.bug_id_map, {})
        self.assertEqual(importer.pending_duplicates, {})

    def test_load_cache(self):
        # Test that loadCache() restores the state set by saveCache()
        cache_filename = os.path.join(self.tmpdir, 'bug-map.pickle')
        self.assertFalse(os.path.exists(cache_filename))
        importer = bugimport.BugImporter(None, None, cache_filename)
        importer.bug_id_map = {42: 1, 100:2}
        importer.pending_duplicates = {50: [1,2]}
        importer.saveCache()
        self.assertTrue(os.path.exists(cache_filename))
        importer.bug_id_map = 'bogus'
        importer.pending_duplicates = 'bogus'
        importer.loadCache()
        self.assertEqual(importer.bug_id_map, {42: 1, 100:2})
        self.assertEqual(importer.pending_duplicates, {50: [1,2]})


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
