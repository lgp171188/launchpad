# Copyright 2009 Canonical Ltd.  All rights reserved.

from canonical.launchpad.windmill.testing import lpuser

from windmill.authoring import WindmillTestClient

WAIT_PAGELOAD = u'30000'
WAIT_ELEMENT_COMPLETE = u'30000'
WAIT_CHECK_CHANGE = u'1000'
FILEBUG_URL = 'http://launchpad.dev:8085/firefox/+filebug'
DUPLICATE_BUG_DIV = u'//div[@id="details-for-bug-4"]'
DUPLICATE_BUG_EXPANDER = u'//img[@id="bug-details-expander-bug-4"]'
BUG_NOT_REPORTED_BUTTON = u'//input[@id="bug-not-already-reported"]'
FILEBUG_FORM = u'//div[@id="bug_reporting_form"]'


def test_duplicate_finder():
    """Test the +filebug duplicate finder.

    The duplicate finder should show a simple view of possible
    duplicates for a bug, with an expander that allows the user to view
    more information if they wish.
    """
    client = WindmillTestClient("Duplicate bug finder test")

    lpuser.SAMPLE_PERSON.ensure_login(client)

    # Go to the +filebug page for Firefox
    client.open(url=FILEBUG_URL)
    client.waits.forPageLoad(timeout=WAIT_PAGELOAD)

    # Ensure the "title" field has finished loading, then enter a simple
    # title and hit search.
    client.waits.forElement(
        xpath=u'//input[@id="field.title"]', timeout=u'8000')
    client.type(text=u'problem', id=u'field.title')
    client.click(xpath=u'//input[@id="field.actions.search"]')
    client.waits.forPageLoad(timeout=WAIT_PAGELOAD)

    # The details div for the duplicate bug should not be shown.
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_DIV, validator='style.display|none')

    # The expander for the duplicate should be collapsed.
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_EXPANDER, validator='src|/@@/treeCollapsed')

    # Clicking on the expander will expand it and show the details div.
    client.click(xpath=DUPLICATE_BUG_EXPANDER)
    client.waits.sleep(milliseconds=WAIT_CHECK_CHANGE)
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_EXPANDER, validator='src|/@@/treeExpanded')
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_DIV, validator='style.display|block')

    # Clicking the expander again will hide the details div and collapse
    # the expander.
    client.click(xpath=DUPLICATE_BUG_EXPANDER)
    client.waits.sleep(milliseconds=WAIT_CHECK_CHANGE)
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_EXPANDER, validator='src|/@@/treeCollapsed')
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_DIV, validator='style.display|none')

    # Clicking it yet again will reopen it.
    client.click(xpath=DUPLICATE_BUG_EXPANDER)
    client.waits.sleep(milliseconds=WAIT_CHECK_CHANGE)
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_EXPANDER, validator='src|/@@/treeExpanded')
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_DIV, validator='style.display|block')

    # Clicking "No, I need to file a new bug" will collapse the
    # duplicate details and expander and will show the filebug form.
    client.click(xpath=BUG_NOT_REPORTED_BUTTON)
    client.waits.sleep(milliseconds=WAIT_CHECK_CHANGE)
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_EXPANDER, validator='src|/@@/treeCollapsed')
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_DIV, validator='style.display|none')
    client.asserts.assertProperty(
        xpath=FILEBUG_FORM, validator='style.display|block')

    # Clicking the duplicate expander again will collapse the filebug
    # form and expand the duplicate.
    client.click(xpath=DUPLICATE_BUG_EXPANDER)
    client.waits.sleep(milliseconds=WAIT_CHECK_CHANGE)
    client.asserts.assertProperty(
        xpath=FILEBUG_FORM, validator='style.display|none')
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_EXPANDER, validator='src|/@@/treeExpanded')
    client.asserts.assertProperty(
        xpath=DUPLICATE_BUG_DIV, validator='style.display|block')
