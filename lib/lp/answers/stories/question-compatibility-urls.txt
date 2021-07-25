Backward Compatible URLs
========================

The Answer Tracker was renamed from the old Technical Support Tracker.
As part of that rename many URLs were changed to reflect the new
terminology. We provide redirect from the old names to the new ones.

Answer Contact Page
-------------------

    >>> user_browser.open('http://launchpad.test/firefox/+support-contact')
    >>> print(user_browser.url)
    http://answers.launchpad.test/firefox/+answer-contact

Add Question Page
-----------------

    >>> user_browser.open('http://launchpad.test/firefox/+addticket')
    >>> print(user_browser.url)
    http://answers.launchpad.test/firefox/+addquestion

    >>> user_browser.open('http://launchpad.test/mozilla/+addticket')
    >>> print(user_browser.url)
    http://answers.launchpad.test/mozilla/+addquestion

My Questions Page
-----------------

    >>> user_browser.open('http://launchpad.test/firefox/+mytickets')
    >>> print(user_browser.url)
    http://answers.launchpad.test/firefox/+myquestions

Questions Listing
-----------------

    >>> browser.open('http://launchpad.test/firefox/+tickets')
    >>> print(browser.url)
    http://answers.launchpad.test/firefox/+questions

Question Page
-------------

    >>> browser.open('http://launchpad.test/firefox/+ticket/1')
    >>> print(browser.url)
    http://answers.launchpad.test/firefox/+question/1

    >>> browser.open('http://api.launchpad.test/devel/firefox/+ticket/1')
    >>> print(browser.url)
    http://api.launchpad.test/devel/firefox/+question/1

Person Questions Listing
------------------------

    >>> browser.open('http://launchpad.test/~name12/+tickets')
    >>> print(browser.url)
    http://answers.launchpad.test/~name12/+questions

    >>> browser.open('http://launchpad.test/~name12/+answeredtickets')
    >>> print(browser.url)
    http://answers.launchpad.test/~name12/+answeredquestions

    >>> browser.open('http://launchpad.test/~name12/+assignedtickets')
    >>> print(browser.url)
    http://answers.launchpad.test/~name12/+assignedquestions

    >>> browser.open('http://launchpad.test/~name12/+commentedtickets')
    >>> print(browser.url)
    http://answers.launchpad.test/~name12/+commentedquestions

    >>> browser.open('http://launchpad.test/~name12/+createdtickets')
    >>> print(browser.url)
    http://answers.launchpad.test/~name12/+createdquestions

    >>> browser.open('http://launchpad.test/~name12/+needattentiontickets')
    >>> print(browser.url)
    http://answers.launchpad.test/~name12/+needattentionquestions

    >>> browser.open('http://launchpad.test/~name12/+subscribedtickets')
    >>> print(browser.url)
    http://answers.launchpad.test/~name12/+subscribedquestions


Unsupported questions
---------------------

The Unsupported View is irrelevant. The question search page provides
links to the +by-language pages that have unsolved questions.

    >>> browser.open('http://launchpad.test/ubuntu/+unsupported')
    >>> print(browser.url)
    http://answers.launchpad.test/ubuntu/+questions


Enumeration changes in search URLs
----------------------------------

The switch from dbschema to lazr based enums changed the values of
status and sort from titles to uppercase tokens in the search URLs.
For instance 'by status' became 'STATUS', and 'Needs information'
became 'NEEDSINFO'. The old values are used in incoming links,
bookmarks, and the firefox-launchpad plugin; the old values must
continue to work.

    >>> old_sort = 'by+status'
    >>> old_status = 'Needs+information'
    >>> url = ('http://answers.launchpad.test/ubuntu/+questions'
    ...        '?field.sort=%s&field.sort-empty-marker=1'
    ...        '&field.language=en&field.language-empty-marker=1'
    ...        '&field.search_text=&field.actions.search=Search'
    ...        '&field.status=%s&field.status-empty-marker=1')
    >>> browser.open(url % (old_sort, old_status))
    >>> print(browser.title)
    Questions : Ubuntu
    >>> browser.getControl(name='field.sort').displayValue
    ['by status']

Using the new values returns the same page.

    >>> new_sort = 'STATUS'
    >>> new_status = 'NEEDSINFO'
    >>> browser.open(url % (new_sort, new_status))
    >>> print(browser.title)
    Questions : Ubuntu
    >>> browser.getControl(name='field.sort').displayValue
    ['by status']
