Changing a person's profile picture
===================================

Users can change their profile picture on their Edit page.

Note that we have chosen not to expose the ability to customise a user's icon
or logo.

    >>> browser = setupBrowser(auth='Basic mark@example.com:test')
    >>> browser.open('http://launchpad.test/~mark')
    >>> browser.url
    'http://launchpad.test/~mark'
    >>> browser.getLink('Change details').click()
    >>> browser.url
    'http://launchpad.test/~mark/+edit'

    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    /@@/person-mugshot

    >>> from lp.testing.branding import set_branding
    >>> set_branding(browser, icon=False, logo=False)

    >>> browser.getControl('Save Changes').click()

Here we see the updated values.

    >>> browser.url
    'http://launchpad.test/~mark'
    >>> browser.getLink('Change details').click()
    >>> browser.url
    'http://launchpad.test/~mark/+edit'

    >>> browser.getControl(name='field.mugshot.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    http://.../mugshot.png

