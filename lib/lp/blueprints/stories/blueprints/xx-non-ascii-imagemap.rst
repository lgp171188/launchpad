Non-ascii characters in specification titles are allowed.

    >>> admin_browser.open(
    ...     "http://blueprints.launchpad.test/firefox/+spec/e4x/+edit"
    ... )

    >>> admin_browser.getControl("Title").value = (
    ...     "A title with non-ascii characters \xe1\xe3"
    ... )
    >>> admin_browser.getControl("Change").click()
    >>> admin_browser.url
    'http://blueprints.launchpad.test/firefox/+spec/e4x'

And they're correctly displayed in the dependency graph imagemap.

    >>> anon_browser.open(
    ...     "http://launchpad.test/firefox/+spec/canvas/+deptreeimgtag"
    ... )
    >>> print(anon_browser.contents)
    <img ...
    <map id="deptree" name="deptree">
    <area shape="poly" ...title="Support &lt;canvas&gt; Objects" .../>
    <area shape="poly" ...title="A title with non&#45;ascii characters áã"
    .../>
    ...

