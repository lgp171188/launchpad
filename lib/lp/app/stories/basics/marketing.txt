Launchpad tour
==============

From Launchpad's front page, you can access the tour.

    >>> browser.open('http://launchpad.test/')
    >>> tour_link = browser.getLink('Take the tour')
    >>> print(tour_link.url)
    http://launchpad.test/+tour
    >>> tour_link.click()
    >>> print(browser.title)
    Launchpad tour
    >>> print(browser.url)
    http://launchpad.test/+tour/index

The tour is circular. Clicking the Next button repeatedly will bring you
back to the tour start.

    >>> def take_the_tour(steps_taken=0):
    ...     browser.getLink(id='btnNext').click()
    ...     print(browser.url)
    ...     if browser.url != 'http://launchpad.test/+tour/index':
    ...         if steps_taken >= 20:
    ...             raise RuntimeError('Never ending tour!')
    ...         take_the_tour(steps_taken=steps_taken+1)
    >>> take_the_tour()
    http://launchpad.test/+tour/bugs
    http://launchpad.test/+tour/branch-hosting-tracking
    http://launchpad.test/+tour/translation
    http://launchpad.test/+tour/community
    http://launchpad.test/+tour/ppa
    http://launchpad.test/+tour/community-support
    http://launchpad.test/+tour/api
    http://launchpad.test/+tour/feature-tracking
    http://launchpad.test/+tour/release-management
    http://launchpad.test/+tour/join-launchpad
    http://launchpad.test/+tour/index

The images from the tour are retrieved relative to +tour.

    >>> browser.open('http://launchpad.test/+tour/images/home/main-image.jpg')
    >>> browser.open('http://launchpad.test/+tour/images/btn-next.png')

But the source directory isn't available:

    >>> browser.open(
    ...     'http://launchpad.test/+tour/source/code-hosting_SVG.svg')
    Traceback (most recent call last):
      ...
    zope.publisher.interfaces.NotFound: ...


+about compatibility
--------------------

Each application used to have an introduction living at +about, this is
now redirected to the relevant tour page.

    >>> browser.open('http://launchpad.test/+about')
    >>> print(browser.url)
    http://launchpad.test/+tour/index

    >>> browser.open('http://code.launchpad.test/+about')
    >>> print(browser.url)
    http://launchpad.test/+tour/branch-hosting-tracking

    >>> browser.open('http://bugs.launchpad.test/+about')
    >>> print(browser.url)
    http://launchpad.test/+tour/bugs

    >>> browser.open('http://blueprints.launchpad.test/+about')
    >>> print(browser.url)
    http://launchpad.test/+tour/feature-tracking

    >>> browser.open('http://translations.launchpad.test/+about')
    >>> print(browser.url)
    http://launchpad.test/+tour/translation

    >>> browser.open('http://answers.launchpad.test/+about')
    >>> print(browser.url)
    http://launchpad.test/+tour/community-support


+tour compatibility
-------------------

Similarly, each application has their +tour redirecting to their proper
tour page.

    >>> browser.open('http://launchpad.test/+tour')
    >>> print(browser.url)
    http://launchpad.test/+tour/index

    >>> browser.open('http://code.launchpad.test/+tour')
    >>> print(browser.url)
    http://launchpad.test/+tour/branch-hosting-tracking

    >>> browser.open('http://bugs.launchpad.test/+tour')
    >>> print(browser.url)
    http://launchpad.test/+tour/bugs

    >>> browser.open('http://blueprints.launchpad.test/+tour')
    >>> print(browser.url)
    http://launchpad.test/+tour/feature-tracking

    >>> browser.open('http://translations.launchpad.test/+tour')
    >>> print(browser.url)
    http://launchpad.test/+tour/translation

    >>> browser.open('http://answers.launchpad.test/+tour')
    >>> print(browser.url)
    http://launchpad.test/+tour/community-support


+faq compatibility
------------------

Each application also had a +faq link, that link is also redirected to
the appropriate tour page.

    >>> browser.open('http://code.launchpad.test/+faq')
    >>> print(browser.url)
    http://launchpad.test/+tour/branch-hosting-tracking

    >>> browser.open('http://bugs.launchpad.test/+faq')
    >>> print(browser.url)
    http://launchpad.test/+tour/bugs

    >>> browser.open('http://blueprints.launchpad.test/+faq')
    >>> print(browser.url)
    http://launchpad.test/+tour/feature-tracking

    >>> browser.open('http://translations.launchpad.test/+faq')
    >>> print(browser.url)
    http://launchpad.test/+tour/translation

    >>> browser.open('http://answers.launchpad.test/+faq')
    >>> print(browser.url)
    http://launchpad.test/+tour/community-support


Links to tour on application main page
--------------------------------------

Each application home page features a 'Take a tour' button that brings
the user to the appropriate tour page.


Code
....

    >>> browser.open('http://code.launchpad.test')
    >>> tour_link = browser.getLink('Take a tour')
    >>> print(tour_link.url)
    http://launchpad.test/+tour/branch-hosting-tracking
    >>> tour_link.click()


Bugs
....

    >>> browser.open('http://bugs.launchpad.test')
    >>> tour_link = browser.getLink('take a tour')
    >>> print(tour_link.url)
    http://bugs.launchpad.test/+tour
    >>> tour_link.click()


Blueprints
..........

    >>> browser.open('http://blueprints.launchpad.test')
    >>> tour_link = browser.getLink('Take a tour')
    >>> print(tour_link.url)
    http://launchpad.test/+tour/feature-tracking
    >>> tour_link.click()


Translations
............

    >>> browser.open('http://translations.launchpad.test')
    >>> tour_link = browser.getLink('Take a tour')
    >>> print(tour_link.url)
    http://launchpad.test/+tour/translation
    >>> tour_link.click()


Answers
.......

    >>> browser.open('http://answers.launchpad.test')
    >>> tour_link = browser.getLink('Take a tour')
    >>> print(tour_link.url)
    http://launchpad.test/+tour/community-support
    >>> tour_link.click()
