===============================
The base-layout master template
===============================

The base-layout master template defines macros that control the layout
of the page. Any page can use these layout options by including

    metal:use-macro="view/macro:page/<layout>"

in the root element of the page template. The base layout template uses the
YUI grid classes for positioning.

    >>> from lp.services.webapp.publisher import LaunchpadView
    >>> from lp.services.webapp.servers import LaunchpadTestRequest
    >>> from zope.browserpage import ViewPageTemplateFile

    >>> user = factory.makePerson(name="waffles")
    >>> request = LaunchpadTestRequest(
    ...     SERVER_URL="http://launchpad.test", PATH_INFO="/~waffles/+layout"
    ... )
    >>> request.setPrincipal(user)

The view can define the template's title in the page_title property.

    >>> class MainSideView(LaunchpadView):
    ...     """A simple view to test base-layout."""
    ...
    ...     __launchpad_facetname__ = "overview"
    ...     template = ViewPageTemplateFile("../tests/testfiles/main-side.pt")
    ...     page_title = "Test base-layout: main_side"
    ...

The main_side layout uses all the defined features of the base-layout
template. The example template uses the epilogue, main, and side
slots. The global search and the applications tabs are present. The
main and side content are positioned using the "yui-t4", "yui-main",
"yui-b", and "yui-b side" classes.

    >>> from lp.testing.pages import find_tag_by_id

    >>> view = MainSideView(user, request)
    >>> html = view.render()
    >>> print(html)
    <!DOCTYPE html>
    ...
      <!--
        Facet name: overview
        Page type: main_side
        Has global search: True
        Has application tabs: True
        Has side portlets: True
    ...

The main_only layout excludes the side slot, the main and epilogue slots are
rendered. The global search and the applications tabs are present. The
YUI Grid "yui-t4" and "yui-b side" divs are not rendered, allowing the main
content to take up all the horizontal space.

    >>> class MainOnlyView(LaunchpadView):
    ...     """A simple view to test base-layout."""
    ...
    ...     __launchpad_facetname__ = "overview"
    ...     template = ViewPageTemplateFile("../tests/testfiles/main-only.pt")
    ...     page_title = "Test base-layout: main_only"
    ...

    >>> view = MainOnlyView(user, request)
    >>> html = view.render()
    >>> print(html)
    <!DOCTYPE html>
    ...
      <!--
        Facet name: overview
        Page type: main_only
        Has global search: True
        Has application tabs: True
        Has side portlets: False
    ...

The searchless template is intended for pages that provide search in the main
content area, so the global search is not needed. The epilogue and main
slots are rendered, as are the application tabs.

    >>> class SearchlessView(LaunchpadView):
    ...     """A simple view to test base-layout."""
    ...
    ...     __launchpad_facetname__ = "overview"
    ...     template = ViewPageTemplateFile(
    ...         "../tests/testfiles/searchless.pt"
    ...     )
    ...     page_title = "Test base-layout: searchless"
    ...

    >>> view = SearchlessView(user, request)
    >>> html = view.render()
    >>> print(html)
    <!DOCTYPE html>
    ...
    ...
      <!--
        Facet name: overview
        Page type: searchless
        Has global search: False
        Has application tabs: True
        Has side portlets: False
    ...


Page Diagnostics
----------------

The page includes a comment after the body with diagnostic information.

    >>> print(html[html.index("</body>") + 7 :])
    <!--
      Facet name: overview
      Page type: searchless
      Has global search: False
      Has application tabs: True
      Has side portlets: False
      At least ... queries... issued in ... seconds
      Features: {...}
      r...
    -->
    ...

Page Headings
-------------

The example layouts all used the heading slot to define a heading for their
test. The template controlled the heading.

    >>> content = find_tag_by_id(view.render(), "maincontent")
    >>> print(content.h1)
    <h1>Heading</h1>


Page Footers
------------

    >>> class BugsMainSideView(MainSideView):
    ...     """A simple view to test base-layout."""
    ...
    ...     __launchpad_facetname__ = "bugs"
    ...
    >>> bugs_request = LaunchpadTestRequest(
    ...     SERVER_URL="http://bugs.launchpad.test",
    ...     PATH_INFO="/~waffles/+layout",
    ... )
    >>> bugs_request.setPrincipal(user)
    >>> view = BugsMainSideView(user, bugs_request)
    >>> footer = find_tag_by_id(html, "footer")
    >>> for tag in footer.find_all("a"):
    ...     print(tag.string, tag["href"])
    ...
    None http://launchpad.test/
    Take the tour http://launchpad.test/+tour
    Read the guide https://help.launchpad.net/
    Canonical Ltd. http://canonical.com/
    Terms of use http://launchpad.test/legal
    Data privacy https://www.ubuntu.com/legal/dataprivacy
    Contact Launchpad Support /feedback
    Blog http://blog.launchpad.net/
    Careers https://canonical.com/careers
    System status https://ubuntu.social/@launchpadstatus
    Get the code! https://documentation.ubuntu.com/launchpad/


Public and private presentation
-------------------------------

The base-layout master templates uses the fmt:global-css formatter to
add the 'public' or 'private' CSS class to the body tag.

When the context is private, the 'private' class is added to the body's class
attribute.

    >>> from lp.registry.interfaces.person import PersonVisibility

    >>> login("admin@canonical.com")
    >>> team = factory.makeTeam(
    ...     owner=user,
    ...     name="a-private-team",
    ...     visibility=PersonVisibility.PRIVATE,
    ... )
    >>> view = MainOnlyView(team, request)
    >>> body = find_tag_by_id(view.render(), "document")
    >>> print(" ".join(body["class"]))
    tab-overview
        main_only
        private
        yui3-skin-sam

When the context is public, the 'public' class is in the class attribute.

    >>> login(ANONYMOUS)
    >>> team = factory.makeTeam(owner=user, name="a-public-team")
    >>> view = MainOnlyView(team, request)
    >>> body = find_tag_by_id(view.render(), "document")
    >>> print(" ".join(body["class"]))
    tab-overview main_only public yui3-skin-sam


Notifications
-------------

Notifications are displayed between the breadcrumbs and the page content.

    >>> request.response.addInfoNotification("I cannot do that Dave.")
    >>> view = MainOnlyView(user, request)
    >>> body_tag = find_tag_by_id(view.render(), "maincontent")
    >>> print(str(body_tag))
    <div ... id="maincontent">
      ...
      <div id="request-notifications">
        <div class="informational message">I cannot do that Dave.</div>
      </div>
      <div class="top-portlet">
      ...

For ajax requests to form views, notifications are added to the response
headers.

    >>> from lp.app.browser.launchpadform import action, LaunchpadFormView
    >>> from zope.interface import Interface
    >>> class FormView(LaunchpadFormView):
    ...     """A simple view to test notifications."""
    ...
    ...     class schema(Interface):
    ...         """A default schema."""
    ...
    ...     @action("Test", name="test")
    ...     def test_action(self, action, data):
    ...         pass
    ...

    >>> extra = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
    >>> request = LaunchpadTestRequest(
    ...     method="POST", form={"field.actions.test": "Test"}, **extra
    ... )
    >>> request.response.addInfoNotification("I cannot do that Dave.")
    >>> view = FormView(user, request)
    >>> view.initialize()
    >>> print(request.response.getHeader("X-Lazr-Notifications"))
    [[20, "I cannot do that Dave."]]
