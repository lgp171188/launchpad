Bug heat on bug page
====================

Bug heat appears on the bug index page:

    >>> anon_browser.open('http://bugs.launchpad.test/firefox/+bug/1')
    >>> content = find_main_content(anon_browser.contents)
    >>> print(content.find('a', href='/+help-bugs/bug-heat.html'))
    <a class="sprite flame" href="/+help-bugs/bug-heat.html"
       target="help">0</a>
