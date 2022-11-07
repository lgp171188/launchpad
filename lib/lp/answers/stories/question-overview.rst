The Launchpad Answer Tracker
============================

Launchpad has an 'Answer Tracker' built in to it. So you can have your
community answers user questions about any upstream application, or any
distribution.


Products
--------

Creating a new question is possible directly from the main page of a
product. Users simply click the 'Ask a question' buttion.

    >>> user_browser.open("http://launchpad.test/firefox")
    >>> user_browser.getLink("Ask a question").click()
    >>> print(user_browser.title)
    Ask a question about...

There is also an 'Ask a question' link on the Bugs home page of the
product:

    >>> user_browser.open("http://bugs.launchpad.test/firefox")
    >>> user_browser.getLink("Ask a question").click()
    >>> print(user_browser.title)
    Ask a question about...

The list of all the currently active questions for the product is
available from the 'Answers' facet.

    >>> browser.open("http://launchpad.test/firefox")
    >>> browser.getLink("Answers").click()

    >>> soup = find_main_content(browser.contents)
    >>> print(soup.find("h1").decode_contents())
    Questions for Mozilla Firefox

    >>> browser.getLink("Firefox loses focus and gets stuck").url
    '.../firefox/+question/4'

There is also an 'Ask a question' link to ask a new question.

    >>> browser.getLink("Ask a question").url
    'http://answers.launchpad.test/firefox/+addquestion'

There are links to some common listing of questions:

    >>> browser.getLink("Open").url
    '.../firefox/+questions?...'

    >>> browser.getLink("Answered").url
    '.../firefox/+questions?...'

    >>> browser.getLink("My questions").url
    '.../firefox/+myquestions'

Information on a particular question can be seen by browsing to the
question page.

    >>> browser.getLink("Problem showing the SVG demo on W3C site").click()
    >>> print(browser.title)
    Question #2 “Problem showing the SVG demo on W3C site” : ...

    >>> print(
    ...     find_main_content(browser.contents).find("h1").decode_contents()
    ... )
    Problem showing the SVG demo on W3C site


Distributions
-------------

Distributions have an 'Ask a question' link on the front page:

    >>> user_browser.open("http://launchpad.test/ubuntu")
    >>> user_browser.getLink("Ask a question").click()
    >>> print(user_browser.title)
    Ask a question about...

As well as on the Bugs facet home page:

    >>> user_browser.open("http://bugs.launchpad.test/ubuntu")
    >>> user_browser.getLink("Ask a question").click()
    >>> print(user_browser.title)
    Ask a question about...

The distribution home page also has a link to the 'Answers' facet:

    >>> browser.open("http://launchpad.test/ubuntu")
    >>> browser.getLink("Answers").url
    'http://answers.launchpad.test/ubuntu'

    >>> browser.getLink("Answers").click()
    >>> print(browser.title)
    Questions : Ubuntu

    >>> browser.getLink("Ask a question")
    <Link...>

On that facet, we will find the same common listings:

    >>> browser.getLink("Open").url
    '.../ubuntu/+questions?...'

    >>> browser.getLink("Answered").url
    '.../ubuntu/+questions?...'

    >>> browser.getLink("My questions").url
    '.../ubuntu/+myquestions'


Distribution Source packages
----------------------------

On a source package, the 'Ask a question' link is accessible through the
Answers facet.

    >>> browser.open("http://launchpad.test/ubuntu/+source/evolution")
    >>> browser.getLink("Answers").url
    'http://answers.launchpad.test/ubuntu/+source/evolution'

    >>> browser.getLink("Answers").click()
    >>> print(browser.title)
    Questions : evolution package : Ubuntu

    >>> browser.getLink("Ask a question").url
    '.../ubuntu/+source/evolution/+addquestion'

As are the common listings:

    >>> browser.getLink("Open").url
    '.../ubuntu/+source/evolution/+questions?...'

    >>> browser.getLink("Answered").url
    '.../ubuntu/+source/evolution/+questions?...'

    >>> browser.getLink("My questions").url
    '.../ubuntu/+source/evolution/+myquestions'

The 'Answers' facet is also available on the distribution source package
page:

    >>> browser.open("http://launchpad.test/ubuntu/+source/mozilla-firefox")
    >>> browser.getLink("Answers").url
    'http://answers.launchpad.test/ubuntu/+source/mozilla-firefox'

    >>> browser.getLink("Answers").click()
    >>> browser.title
    'Questions : mozilla-firefox package : Ubuntu'

    >>> browser.getLink("Ask a question").url
    '.../ubuntu/+source/mozilla-firefox/+addquestion'

    >>> browser.getLink("Open").url
    '.../ubuntu/+source/mozilla-firefox/+questions?...'

    >>> browser.getLink("Answered").url
    '.../ubuntu/+source/mozilla-firefox/+questions?...'

    >>> browser.getLink("My questions").url
    '.../ubuntu/+source/mozilla-firefox/+myquestions'


ProjectGroups
-------------

ProjectGroups also have the 'Latest questions' portlet and the 'Ask a
question' button on their overview page.

    >>> user_browser.open("http://launchpad.test/mozilla")

    >>> questions = find_tag_by_id(
    ...     user_browser.contents, "portlet-latest-questions"
    ... )
    >>> print(backslashreplace(extract_text(questions)))
    All questions
    Latest questions
    Problemas de Impress\xe3o no Firefox ...
    Newly installed plug-in doesn't seem to be used ...
    Firefox loses focus and gets stuck ...
    Problem showing the SVG demo on W3C site ...
    Firefox cannot render Bank Site ...

    >>> user_browser.getLink("Ask a question").click()
    >>> print(user_browser.title)
    Ask a question about...


Persons
-------

The 'Answers' facet link will display a page listing all the questions
involving a person.

    >>> browser.open("http://launchpad.test/~name16")
    >>> browser.getLink("Answers").url
    'http://answers.launchpad.test/~name16'

    >>> browser.getLink("Answers").click()
    >>> print(browser.title)
    Questions : Foo Bar

    >>> print(
    ...     find_main_content(browser.contents).find("h1").decode_contents()
    ... )
    Questions for Foo Bar

    >>> browser.getLink("Slow system").url
    '.../ubuntu/+question/7'

    # One of them is not on this batch, so we'll have to first go to the next
    # batch.

    >>> browser.getLink("Next").click()
    >>> browser.getLink("Firefox loses focus").url
    '.../firefox/+question/4'


Accessing a question directly
-----------------------------

You can access any question by its ID using the URL
http://answers.launchpad.test/questions/<id>. This URL will redirect to
the proper context where the question can be found:

    >>> browser.open("http://answers.launchpad.test/questions/1")
    >>> print(browser.url)
    http://answers.launchpad.test/firefox/+question/1

    >>> print(
    ...     find_main_content(browser.contents).find("h1").decode_contents()
    ... )
    Firefox cannot render Bank Site

This also works on the webservice.

    >>> browser.open("http://api.launchpad.test/devel/questions/1")
    >>> print(browser.url)
    http://api.launchpad.test/devel/firefox/+question/1

Asking for a non-existent question or an invalid ID will still raise a
404 though:

    >>> browser.open("http://answers.launchpad.test/questions/255")
    Traceback (most recent call last):
      ...
    zope.publisher.interfaces.NotFound: ...

    >>> browser.open("http://answers.launchpad.test/questions/bad_id")
    Traceback (most recent call last):
      ...
    zope.publisher.interfaces.NotFound: ...

Also If you access a question through the wrong context, you'll be
redirected to the question in the proper context. (For example, this is
useful after a question was retargeted.)

    >>> browser.open("http://answers.launchpad.test/ubuntu/+question/1")
    >>> print(browser.url)
    http://answers.launchpad.test/firefox/+question/1

    >>> browser.open("http://api.launchpad.test/devel/ubuntu/+question/1")
    >>> print(browser.url)
    http://api.launchpad.test/devel/firefox/+question/1

It also works with pages below that URL:

    >>> browser.open(
    ...     "http://answers.launchpad.test/ubuntu/+question/1/+history"
    ... )
    >>> print(browser.url)
    http://answers.launchpad.test/firefox/+question/1/+history

But again, an invalid ID still raises a 404:

    >>> browser.open("http://answers.launchpad.test/ubuntu/+question/255")
    Traceback (most recent call last):
      ...
    zope.publisher.interfaces.NotFound: ...

    >>> browser.open("http://answers.launchpad.test/ubuntu/+question/bad_id")
    Traceback (most recent call last):
      ...
    zope.publisher.interfaces.NotFound: ...


