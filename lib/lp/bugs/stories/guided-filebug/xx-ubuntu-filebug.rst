Ubuntu and +filebug
-------------------

When so configured, Launchpad blocks users from filing Ubuntu bugs directly
from the web interface.

We set the `ubuntu_disable_filebug` flag to true, and set the URL to redirect
to a local page (the default configuration is for a page on the Ubuntu wiki).

    >>> from lp.services.config import config
    >>> config.push('malone', '''
    ... [malone]
    ... ubuntu_disable_filebug: true
    ... ubuntu_bug_filing_url: http://launchpad.test/+tour
    ... ''')

Trying to navigate to the 'report a bug' page redirects us to the alternative
page.

    >>> user_browser.open('http://launchpad.test/ubuntu')
    >>> user_browser.getLink('Report a bug').click()
    >>> print(user_browser.url)
    http://launchpad.test/+tour/index

We can override this behaviour by adding the `no-redirect` query parameter.

    >>> user_browser.open(
    ...    'http://bugs.launchpad.test/ubuntu/+filebug?no-redirect')
    >>> print(user_browser.title)
    Report a bug : Bugs : Ubuntu

The no-redirect parameter is retained when we redirect a user to the bug
filing view of another context.

    >>> user_browser.open(
    ...    'http://bugs.launchpad.test/ubuntu/hoary/+filebug?no-redirect')
    >>> print(user_browser.url)
    http://bugs.launchpad.test/ubuntu/+filebug?no-redirect

When filing bugs directly on source packages we are also not redirected.

    >>> admin_browser.open(
    ...     'http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/'
    ...     '+filebug')
    >>> print(admin_browser.url)
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/+filebug

Ubuntu's bug supervisor doesn't get automatically redirected either.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> login('foo.bar@canonical.com')
    >>> ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
    >>> foobar = getUtility(IPersonSet).getByName('name16')
    >>> ubuntu.bug_supervisor = foobar
    >>> transaction.commit()
    >>> logout()

    >>> admin_browser.open('http://bugs.launchpad.test/ubuntu/+filebug')
    >>> print(admin_browser.title)
    Report a bug : Bugs : Ubuntu

Filing bugs with Apport also allows us to get to the bug filing interface.

    >>> import os.path
    >>> testfiles = os.path.join(config.root, 'lib/lp/bugs/tests/testfiles')
    >>> extra_filebug_data = open(
    ...     os.path.join(testfiles, 'extra_filebug_data.msg'), 'rb')
    >>> anon_browser.open('http://launchpad.test/+storeblob')
    >>> anon_browser.getControl(name='field.blob').add_file(
    ...     extra_filebug_data, 'not/important', 'not.important')
    >>> anon_browser.getControl(name='FORM_SUBMIT').click()
    >>> blob_token = six.ensure_text(
    ...     anon_browser.headers['X-Launchpad-Blob-Token'])
    >>> from lp.bugs.interfaces.apportjob import IProcessApportBlobJobSource
    >>> login('foo.bar@canonical.com')
    >>> job = getUtility(IProcessApportBlobJobSource).getByBlobUUID(
    ...     blob_token)
    >>> job.job.start()
    >>> job.run()
    >>> job.job.complete()
    >>> logout()
    >>> filebug_url = (
    ...    'http://launchpad.test/ubuntu/+source/mozilla-firefox/+filebug/'
    ...     '%s' % blob_token)
    >>> user_browser.open(
    ...     'http://launchpad.test/ubuntu/+source/mozilla-firefox/+filebug/%s'
    ...     % blob_token)
    >>> print(user_browser.url)
    http://launchpad.test/ubuntu/+source/mozilla-firefox/+filebug/...

    >>> _ = config.pop('malone')

The inline filebug form never gets redirected.

    >>> user_browser.open(
    ...     'http://bugs.launchpad.test/ubuntu/+filebug-inline-form')
    >>> print(user_browser.url)
    http://bugs.launchpad.test/ubuntu/+filebug-inline-form

Neither does the show-similar-bugs view.

    >>> user_browser.open(
    ...     'http://bugs.launchpad.test/ubuntu/'
    ...     '+filebug-show-similar?title=testing')
    >>> print(user_browser.url)
    http://bugs.launchpad.test/ubuntu/+filebug-show-similar?title=testing
