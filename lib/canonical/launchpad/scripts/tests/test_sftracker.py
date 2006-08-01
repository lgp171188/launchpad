# Copyright 2006 Canonical Ltd.  All rights reserved.

__metaclass__ = type

from cStringIO import StringIO
import datetime
import sys
import unittest

import pytz
from zope.component import getUtility
from canonical.launchpad.interfaces import (
    IEmailAddressSet, ILaunchpadCelebrities, IPersonSet, IProductSet)
from canonical.launchpad.scripts import sftracker
from canonical.lp.dbschema import (
    BugTaskImportance, BugTaskStatus, BugAttachmentType)

from canonical.functional import ZopelessLayer
from canonical.launchpad.ftests.harness import LaunchpadZopelessTestSetup
from canonical.librarian.ftests.harness import LibrarianTestSetup

item_data = r"""
<item id="1278591">
    <assigned_to>Thomas Ries</assigned_to>
    <attachment file_id="147710">
      <content_disposition>attachment; filename=siproxd.patch</content_disposition>
      <content_length>1327</content_length>
      <content_type>application/octet-stream</content_type>
      <date>2005-09-01 02:35</date>
      <description>Patch to include Proxy-Authenticate in response</description>
      <etag>"jpd--1645707516.1327"</etag>
      <link>/tracker/download.php?group_id=60374&amp;atid=493974&amp;file_id=147710&amp;aid=1278591</link>
      <sender>nobody</sender>
      <title>siproxd.patch</title>
      <data encoding="base64">
LS0tIGF1dGguYy5vcmlnCTIwMDUtMDEtMDggMTE6MDU6MTIuMDAwMDAwMDAwICswMTAwCisrKyBh
dXRoLmMJMjAwNS0wOS0wMSAxMToyNjowOC4wMDAwMDAwMDAgKzAyMDAKQEAgLTkxLDcgKzkxLDcg
QEAKICAqCVNUU19TVUNDRVNTCiAgKglTVFNfRkFJTFVSRQogICovCi1pbnQgYXV0aF9pbmNsdWRl
X2F1dGhycShzaXBfdGlja2V0X3QgKnRpY2tldCkgeworaW50IGF1dGhfaW5jbHVkZV9hdXRocnEo
b3NpcF9tZXNzYWdlX3QgKnNpcG1zZykgewogICAgb3NpcF9wcm94eV9hdXRoZW50aWNhdGVfdCAq
cF9hdXRoOwogICAgY2hhciAqcmVhbG09TlVMTDsKIApAQCAtMTEyLDcgKzExMiw3IEBACg==
</data>
    </attachment><category>General</category>
    <closed_by>tries</closed_by>
    <comment>
      <date>2005-10-01 08:14</date>
      <description>Date: 2005-10-01 08:14
Sender: tries
Logged In: YES
user_id=438614

Thanks, &amp;amp; &amp;amp;quot;
I applied the included patch. Will be available in version
0.5.12 or use the "daily snapshot" where is is
included.

/Thomas</description>
      <sender>tries</sender>
      <sender_user_id>438614</sender_user_id>
    </comment><date_closed>2005-10-01 08:14</date_closed>
    <date_last_updated>2005-10-01 08:14</date_last_updated>
    <date_submitted>2005-09-01 02:35</date_submitted>
    <description>When siproxd is used with authentication (eg.
proxy_auth_pwfile defined) it does not set
'Proxy-Authenticate' header in 407 code response.
Looking into code we can see that funtion
'auth_include_authrq' is used against 'ticket' whereas
we send 'response' back to the client. Modyfying code
to use response instead ticket solves the problem (see
attached patch) Add a Comment:</description>
    <group>siproxd-0.5.x</group>
    <item_id>1278591</item_id>
    <last_updated_by>tries - Comment added</last_updated_by>
    <number_of_attachments>1</number_of_attachments>
    <number_of_comments>1</number_of_comments>
    <priority>5</priority>
    <resolution>Fixed</resolution>
    <status>Closed</status>
    <submitted_by>Nobody/Anonymous - nobody</submitted_by>
    <summary>Proxy-Authenticate header not included in response</summary>
    <title>Proxy-Authenticate header not included in response</title>
  </item>
"""
summary_data = r"""
<item id="1278591"><assigned_to>tries</assigned_to><description>Proxy-Authenticate header not included in response</description><link>/tracker/index.php?func=detail&amp;aid=1278591&amp;group_id=60374&amp;atid=493974</link><priority>5</priority><status>Closed</status><submitted_by>nobody</submitted_by><timestamp>* 2005-09-01 02:35</timestamp><tracker>493974</tracker></item>
"""

UTC = pytz.timezone('UTC')


class TrackerItemLoaderTestCase(unittest.TestCase):

    def test_parse_tracker_item(self):
        item_node = sftracker.ET.parse(StringIO(item_data)).getroot()
        summary_node = sftracker.ET.parse(StringIO(summary_data)).getroot()
        item = sftracker.TrackerItem(item_node, summary_node)

        self.assertEqual(item.url,
                         'http://sourceforge.net/tracker/index.php?'
                         'func=detail&aid=1278591&group_id=60374&atid=493974')
        self.assertEqual(item.item_id, '1278591')
        self.assertEqual(item.reporter, 'nobody')
        self.assertEqual(item.assignee, 'tries')
        self.assertEqual(item.datecreated,
                         datetime.datetime(2005, 9, 1, 9, 35, tzinfo=UTC))
        self.assertEqual(item.title,
                         'Proxy-Authenticate header not included in response')
        self.assertEqual(item.category, 'General')
        self.assertEqual(item.group, 'siproxd-0.5.x')
        self.assertEqual(item.priority, '5')
        self.assertEqual(item.status, 'Closed')
        self.assertEqual(item.resolution, 'Fixed')
        self.assertTrue(item.description.startswith(
            'When siproxd is used with authentication'))

        self.assertEqual(len(item.comments), 2)
        self.assertEqual(item.comments[0][0],
                         datetime.datetime(2005, 9, 1, 9, 35, tzinfo=UTC))
        self.assertEqual(item.comments[0][1], 'nobody')
        self.assertTrue(item.comments[0][2].startswith(
            'When siproxd is used with authentication'))
        self.assertEqual(item.comments[1][0],
                         datetime.datetime(2005, 10, 1, 15, 14, tzinfo=UTC))
        self.assertEqual(item.comments[1][1], 'tries')
        self.assertTrue(item.comments[1][2].startswith('Thanks, & &quot;'))

        self.assertEqual(len(item.attachments), 1)
        self.assertEqual(item.attachments[0].filename, 'siproxd.patch')
        self.assertEqual(item.attachments[0].title,
                         'Patch to include Proxy-Authenticate in response')
        self.assertEqual(item.attachments[0].sender, 'nobody')
        self.assertEqual(item.attachments[0].date,
                         datetime.datetime(2005, 9, 1, 9, 35, tzinfo=UTC))
        self.assertEqual(item.attachments[0].is_patch, True)
        self.assertTrue(item.attachments[0].data.startswith(
            '--- auth.c.orig\t2005-01-08 11:05:12.000000000 +0100\n'))

        self.assertEqual(item.lp_status, BugTaskStatus.FIXRELEASED)
        self.assertEqual(item.lp_importance, BugTaskImportance.MEDIUM)


class SanitiseNameTestCase(unittest.TestCase):

    def test_sanitise_name(self):
        self.assertEqual(sftracker.sanitise_name('foobar'), 'foobar')
        self.assertEqual(sftracker.sanitise_name('Python 2.4'), 'python-2.4')
        self.assertEqual(sftracker.sanitise_name('Core (C Code)'),
                         'core-c-code')
        self.assertEqual(sftracker.sanitise_name('python-2.4'), 'python-2.4')
        self.assertEqual(sftracker.sanitise_name('1.0'), 'x-1.0')


class PersonMappingTestCase(unittest.TestCase):

    layer = ZopelessLayer

    def setUp(self):
        self.zopeless = LaunchpadZopelessTestSetup()
        self.zopeless.setUp()

    def tearDown(self):
        self.zopeless.tearDown()

    def test_create_person(self):
        # Test that person creation works
        person = getUtility(IPersonSet).getByEmail('foo@users.sourceforge.net')
        self.assertEqual(person, None)

        importer = sftracker.TrackerImporter(None)
        person = importer.person('foo')
        self.assertNotEqual(person, None)
        self.assertEqual(person.guessedemails.count(), 1)
        self.assertEqual(person.guessedemails[0].email,
                         'foo@users.sourceforge.net')

    def test_find_existing_person(self):
        person = getUtility(IPersonSet).getByEmail('foo@users.sourceforge.net')
        self.assertEqual(person, None)
        person = getUtility(IPersonSet).ensurePerson(
            'foo@users.sourceforge.net', None)
        self.assertNotEqual(person, None)

        importer = sftracker.TrackerImporter(None)
        self.assertEqual(importer.person('foo'), person)

    def test_nobody_person(self):
        # Test that TrackerImporter.person() returns None where appropriate
        importer = sftracker.TrackerImporter(None)
        self.assertEqual(importer.person(None), None)
        self.assertEqual(importer.person(''), None)
        self.assertEqual(importer.person('nobody'), None)

    def test_verify_new_person(self):
        importer = sftracker.TrackerImporter(None, verify_users=True)
        person = importer.person('foo')
        self.assertNotEqual(person, None)
        self.assertNotEqual(person.preferredemail, None)
        self.assertEqual(person.preferredemail.email,
                         'foo@users.sourceforge.net')

    def test_verify_existing_person(self):
        person = getUtility(IPersonSet).ensurePerson(
            'foo@users.sourceforge.net', None)
        self.assertEqual(person.preferredemail, None)

        importer = sftracker.TrackerImporter(None, verify_users=True)
        person = importer.person('foo')
        self.assertNotEqual(person.preferredemail, None)
        self.assertEqual(person.preferredemail.email,
                         'foo@users.sourceforge.net')

    def test_verify_doesnt_clobber_preferred_email(self):
        person = getUtility(IPersonSet).ensurePerson(
            'foo@users.sourceforge.net', None)
        email = getUtility(IEmailAddressSet).new('foo@example.com', person.id)
        person.setPreferredEmail(email)
        self.assertEqual(person.preferredemail.email, 'foo@example.com')

        importer = sftracker.TrackerImporter(None, verify_users=True)
        person = importer.person('foo')
        self.assertNotEqual(person.preferredemail, None)
        self.assertEqual(person.preferredemail.email, 'foo@example.com')


class TrackerItemImporterTestCase(unittest.TestCase):
    
    layer = ZopelessLayer

    def setUp(self):
        self.zopeless = LaunchpadZopelessTestSetup()
        self.zopeless.setUp()
        self.librarian = LibrarianTestSetup()
        self.librarian.setUp()

    def tearDown(self):
        self.librarian.tearDown()
        self.zopeless.tearDown()

    def test_import_item(self):
        item_node = sftracker.ET.parse(StringIO(item_data)).getroot()
        summary_node = sftracker.ET.parse(StringIO(summary_data)).getroot()
        item = sftracker.TrackerItem(item_node, summary_node)

        # import against some product.
        product = getUtility(IProductSet).getByName('netapplet')
        importer = sftracker.TrackerImporter(product)
        bug = importer.importTrackerItem(item)
        bugtask = bug.bugtasks[0]

        self.assertEqual(bug.name, 'sf1278591')
        # bugs submitted anonymously map to the bug importer
        self.assertEqual(bug.owner,
                         getUtility(ILaunchpadCelebrities).bug_importer)
        self.assertEqual(bug.title,
                         'Proxy-Authenticate header not included in response')
        self.assertEqual(bug.datecreated,
                         datetime.datetime(2005, 9, 1, 9, 35, tzinfo=UTC))
        self.assertEqual(bug.tags, ['general'])

        self.assertEqual(bugtask.product, product)
        self.assertNotEqual(bugtask.assignee, None)
        self.assertEqual(bugtask.assignee.guessedemails[0].email,
                         'tries@users.sourceforge.net')
        self.assertEqual(bugtask.importance, BugTaskImportance.MEDIUM)
        self.assertEqual(bugtask.status, BugTaskStatus.FIXRELEASED)
        self.assertNotEqual(bugtask.milestone, None)
        self.assertEqual(bugtask.milestone.name, 'siproxd-0.5.x')

        self.assertEqual(bug.messages.count(), 2)
        comment1, comment2 = bug.messages
        self.assertEqual(comment1.owner,
                         getUtility(ILaunchpadCelebrities).bug_importer)
        self.assertEqual(comment1.datecreated,
                         datetime.datetime(2005, 9, 1, 9, 35, tzinfo=UTC))
        self.assertTrue(comment1.text_contents.startswith(
            'When siproxd is used with authentication'))

        self.assertEqual(comment2.owner.guessedemails[0].email,
                         'tries@users.sourceforge.net')
        self.assertEqual(comment2.datecreated,
                         datetime.datetime(2005, 10, 1, 15, 14, tzinfo=UTC))
        self.assertTrue(comment2.text_contents.startswith('Thanks, & &quot;'))

        self.assertEqual(comment1.bugattachments.count(), 1)
        attachment = comment1.bugattachments[0]
        self.assertEqual(attachment.bug, bug)
        self.assertEqual(attachment.type, BugAttachmentType.PATCH)
        self.assertEqual(attachment.title,
                         'Patch to include Proxy-Authenticate in response')
        self.assertEqual(attachment.libraryfile.filename, 'siproxd.patch')
        self.assertEqual(attachment.libraryfile.mimetype, 'text/plain')

        self.assertEqual(bug.externalrefs.count(), 1)
        self.assertEqual(bug.externalrefs[0].url,
                         'http://sourceforge.net/tracker/index.php?'
                         'func=detail&aid=1278591&group_id=60374&atid=493974')
        self.assertEqual(bug.externalrefs[0].title, 'SF #1278591')

        self.assertEqual(bug.activity.count(), 1)
        self.assertEqual(bug.activity[0].person,
                         getUtility(ILaunchpadCelebrities).bug_importer)
        self.assertEqual(bug.activity[0].whatchanged, 'bug')
        self.assertEqual(bug.activity[0].message,
                         'Imported SF tracker item #1278591')

        
def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
