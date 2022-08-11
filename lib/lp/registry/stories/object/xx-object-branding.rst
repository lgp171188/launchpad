Branding
========

Several objects in Launchpad can have aspects of their branding customised.
Specifically, you can set various combinations of an icon, for listings, a
logo, for page headings, and a mugshot, which is a large brand for the
object's homepage.

Most objects allow you to edit all three of these branding items. However,
for IPerson and ISprint, we do not currently allow the customisation of the
icon, as we think this will create too much noise in the UI.

    >>> from lp.testing.branding import set_branding

Team branding
-------------

    >>> browser = setupBrowser(auth='Basic no-priv@canonical.com:test')
    >>> browser.open('http://launchpad.test/~ubuntu-team/+branding')
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> browser = setupBrowser(auth='Basic mark@example.com:test')
    >>> browser.open('http://launchpad.test/~ubuntu-team')
    >>> browser.url
    'http://launchpad.test/~ubuntu-team'
    >>> browser.getLink('Change details').click()
    >>> browser.getLink('Change branding').click()
    >>> browser.url
    'http://launchpad.test/~ubuntu-team/+branding'

    >>> browser.getControl(name='field.icon.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.icon_current_img').get('src'))
    /@@/team
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    /@@/team-logo
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    /@@/team-mugshot

    >>> set_branding(browser)

    >>> browser.getControl('Change Branding').click()

Here we see the updated values.

    >>> browser.url
    'http://launchpad.test/~ubuntu-team'
    >>> browser.getLink('Change details').click()
    >>> browser.getLink('Change branding').click()

    >>> browser.getControl(name='field.icon.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.icon_current_img').get('src'))
    http://.../icon.png
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    http://.../logo.png
    >>> browser.getControl(name='field.mugshot.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    http://.../mugshot.png


Distribution branding
---------------------

    >>> browser = setupBrowser(auth='Basic no-priv@canonical.com:test')
    >>> browser.open('http://launchpad.test/kubuntu/+edit')
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> browser = setupBrowser(auth='Basic mark@example.com:test')
    >>> browser.open('http://launchpad.test/kubuntu')
    >>> browser.url
    'http://launchpad.test/kubuntu'
    >>> browser.getLink('Change details').click()
    >>> browser.url
    'http://launchpad.test/kubuntu/+edit'

    >>> browser.getControl(name='field.icon.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.icon_current_img').get('src'))
    /@@/distribution
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    /@@/distribution-logo
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    /@@/distribution-mugshot

    >>> set_branding(browser)

    >>> browser.getControl('Change', index=3).click()

Here we see the updated values.

    >>> browser.url
    'http://launchpad.test/kubuntu'
    >>> browser.getLink('Change details').click()

    >>> browser.getControl(name='field.icon.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.icon_current_img').get('src'))
    http://.../icon.png
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    http://.../logo.png
    >>> browser.getControl(name='field.mugshot.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    http://.../mugshot.png


ProjectGroup branding
---------------------

    >>> browser = setupBrowser(auth='Basic no-priv@canonical.com:test')
    >>> browser.open('http://launchpad.test/mozilla/+branding')
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> browser = setupBrowser(auth='Basic mark@example.com:test')
    >>> browser.open('http://launchpad.test/mozilla')
    >>> browser.url
    'http://launchpad.test/mozilla'
    >>> browser.getLink('Change details').click()
    >>> browser.getLink('Change branding').click()
    >>> browser.url
    'http://launchpad.test/mozilla/+branding'

    >>> browser.getControl(name='field.icon.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.icon_current_img').get('src'))
    /@@/project
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    /@@/project-logo
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    /@@/project-mugshot

    >>> set_branding(browser)

    >>> browser.getControl('Change Branding').click()

Here we see the updated values.

    >>> browser.url
    'http://launchpad.test/mozilla'
    >>> browser.getLink('Change details').click()
    >>> browser.getLink('Change branding').click()

    >>> browser.getControl(name='field.icon.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.icon_current_img').get('src'))
    http://.../icon.png
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    http://.../logo.png
    >>> browser.getControl(name='field.mugshot.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    http://.../mugshot.png


Product branding
----------------

    >>> browser = setupBrowser(auth='Basic no-priv@canonical.com:test')
    >>> browser.open('http://launchpad.test/jokosher/+branding')
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> browser = setupBrowser(auth='Basic mark@example.com:test')
    >>> browser.open('http://launchpad.test/jokosher')
    >>> browser.url
    'http://launchpad.test/jokosher'
    >>> browser.getLink('Change details').click()
    >>> browser.url
    'http://launchpad.test/jokosher/+edit'
    >>> browser.getLink('Cancel').click()
    >>> browser.getLink('Change branding').click()
    >>> browser.url
    'http://launchpad.test/jokosher/+branding'

    >>> browser.getControl(name='field.icon.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.icon_current_img').get('src'))
    /@@/product
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    /@@/product-logo
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    /@@/product-mugshot

    >>> set_branding(browser)

    >>> browser.getControl('Change Branding').click()

Here we see the updated values.

    >>> browser.url
    'http://launchpad.test/jokosher'
    >>> browser.getLink('Change branding').click()

    >>> browser.getControl(name='field.icon.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.icon_current_img').get('src'))
    http://.../icon.png
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    http://.../logo.png
    >>> browser.getControl(name='field.mugshot.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    http://.../mugshot.png


Sprint branding
---------------

Again, for Sprints, we have not exposed icon editing through the UI.

    >>> login('test@canonical.com')
    >>> _ = factory.makeSprint(name='futurista')
    >>> logout()

    >>> browser = setupBrowser(auth='Basic no-priv@canonical.com:test')
    >>> browser.open('http://launchpad.test/sprints/futurista/+branding')
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> browser = setupBrowser(auth='Basic mark@example.com:test')
    >>> browser.open('http://launchpad.test/sprints/futurista')
    >>> browser.url
    'http://launchpad.test/sprints/futurista'
    >>> browser.getLink('Change branding').click()
    >>> browser.url
    'http://launchpad.test/sprints/futurista/+branding'

    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    /@@/meeting-logo
    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    /@@/meeting-mugshot

    >>> set_branding(browser, icon=False)

    >>> browser.getControl('Change Branding').click()

Here we see the updated values.

    >>> browser.url
    'http://launchpad.test/sprints/futurista'
    >>> browser.getLink('Change branding').click()

    >>> browser.getControl(name='field.logo.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.logo_current_img').get('src'))
    http://.../logo.png
    >>> browser.getControl(name='field.mugshot.action').value
    ['keep']
    >>> print(find_tag_by_id(
    ...     browser.contents, 'field.mugshot_current_img').get('src'))
    http://.../mugshot.png
