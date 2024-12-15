Bug Reporting Guidelines, Acknowledgement Messages and Description Templates
=====================================================

Some helpful explanatory text - guidelines - and a pre-defined bug description
template can be set for distributions, product groups, products, and source
packages, as well as an acknowledgement message that is displayed when a bug
has been filed.

    >>> contexts = [
    ...     ("Ubuntu", "ubuntu", "+edit"),
    ...     ("Mozilla", "mozilla", "+edit"),
    ...     ("Firefox", "firefox", "+configure-bugtracker"),
    ...     ("alsa-utils in Ubuntu", "ubuntu/+source/alsa-utils", "+edit"),
    ... ]

    >>> for context_name, context_path, view in contexts:
    ...     edit_url = "http://launchpad.test/%s/%s" % (context_path, view)
    ...     admin_browser.open(edit_url)
    ...     admin_browser.getControl(
    ...         name="field.bug_reporting_guidelines"
    ...     ).value = (
    ...         "The version of %s you're using.\n"
    ...         "See http://example.com for more details." % (context_name,)
    ...     )
    ...     admin_browser.getControl(name="field.content_templates").value = (
    ...         "The pre-defined bug template."
    ...     )
    ...     admin_browser.getControl(
    ...         name="field.bug_reported_acknowledgement"
    ...     ).value = (
    ...         "Thank you for filing a bug for https://launchpad.test/%s"
    ...         % context_path
    ...     )
    ...     if context_path == "ubuntu":
    ...         admin_browser.getControl("Change", index=3).click()
    ...     else:
    ...         admin_browser.getControl("Change").click()
    ...

The guidelines and bug templates are not displayed on the initial basic
bug-reporting page, because that page does not include a bug description
field.

    >>> def print_guidelines(name, browser):
    ...     print("*")
    ...     print(name)
    ...     print("  <%s>" % user_browser.url)
    ...     print(
    ...         extract_text(
    ...             find_tag_by_id(
    ...                 user_browser.contents, "bug-reporting-guidelines"
    ...             )
    ...         )
    ...     )
    ...
    >>> def print_acknowledgement_message(browser):
    ...     print(
    ...         extract_text(
    ...             find_tags_by_class(
    ...                 user_browser.contents, "informational message"
    ...             )[0]
    ...         )
    ...     )
    ...

    >>> def print_visible_guidelines(context_path, guidelines):
    ...     result = guidelines.find_parents(id="filebug-form-container")
    ...     style_attrs = []
    ...     if result:
    ...         filebug_form_container = result[0]
    ...         style_attrs = [
    ...             item.strip()
    ...             for item in filebug_form_container["style"].split(";")
    ...         ]
    ...     if result and not "display: none" in style_attrs:
    ...         print("Found %s guidelines: %s" % (context_path, guidelines))
    ...

    >>> for context_name, context_path, view in contexts:
    ...     filebug_url = "http://launchpad.test/%s/+filebug" % (
    ...         context_path,
    ...     )
    ...     user_browser.open(filebug_url)
    ...     guidelines = find_tag_by_id(
    ...         user_browser.contents, "bug-reporting-guidelines"
    ...     )
    ...     if guidelines is not None:
    ...         print_visible_guidelines(context_path, guidelines)
    ...

But they are displayed once you've got to the step of entering a bug
description.

    >>> for context_name, context_path, view in contexts:
    ...     filebug_url = "http://bugs.launchpad.test/%s/+filebug" % (
    ...         context_path,
    ...     )
    ...     user_browser.open(filebug_url)
    ...     user_browser.getControl("Summary", index=0).value = (
    ...         "It doesn't work"
    ...     )
    ...     user_browser.getControl("Continue").click()
    ...     user_browser.getControl("Bug Description").value = "please help!"
    ...     print_guidelines(context_name, user_browser)
    ...     user_browser.getControl("Submit Bug Report").click()
    ...     print_acknowledgement_message(user_browser)
    ...
    *
    Ubuntu
      <http://bugs.launchpad.test/ubuntu/+filebug>
    Ubuntu bug reporting guidelines:
    The version of Ubuntu you're using.
    See http://example.com for more details.
    Thank you for filing a bug for https://launchpad.test/ubuntu
    *
    Mozilla
      <http://.../firefox/+filebug?field.title=It+doesn%27t+work&field.tags=>
    Mozilla Firefox bug reporting guidelines:
    The version of Firefox you're using.
    See http://example.com for more details.
    Thank you for filing a bug for https://launchpad.test/firefox
    *
    Firefox
      <http://bugs.launchpad.test/firefox/+filebug>
    Mozilla Firefox bug reporting guidelines:
    The version of Firefox you're using.
    See http://example.com for more details.
    Thank you for filing a bug for https://launchpad.test/firefox
    *
    alsa-utils in Ubuntu
      <http://bugs.launchpad.test/ubuntu/+source/alsa-utils/+filebug>
    alsa-utils (Ubuntu) bug reporting guidelines:
    The version of alsa-utils in Ubuntu you're using.
    See http://example.com for more details.
    Ubuntu bug reporting guidelines:
    The version of Ubuntu you're using.
    See http://example.com for more details.
    Thank you for filing a bug for
    https://launchpad.test/ubuntu/+source/alsa-utils

URLs are linkified.

    >>> print(
    ...     find_tags_by_class(
    ...         user_browser.contents, "informational message"
    ...     )[0]
    ... )
    <div ...><p class="last">Thank you for filing a bug for
    <a...https://launchpad.test/ubuntu/+source/alsa-utils.../a></p></div>

Note how the alsa-utils in Ubuntu specific guidelines were displayed
followed by the general Ubuntu bug reporting guidelines.

Bugs can also be reported directly against a distribution series, for
which the guidelines are taken from the respective distribution.

    >>> user_browser.open("http://launchpad.test/ubuntu/warty/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = "It doesn't work"
    >>> user_browser.getControl("Continue").click()
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             user_browser.contents, "bug-reporting-guidelines"
    ...         )
    ...     )
    ... )
    Ubuntu bug reporting guidelines:
    The version of Ubuntu you're using.
    See http://example.com for more details.

Any URLS in the guidelines will be linkified, with the target attribute
of the link being set to "_new" so that the links always open in a new
page. This prevents the user being taken away from the bug filing
process by clicking on the links.

    >>> print(
    ...     find_tag_by_id(user_browser.contents, "bug-reporting-guidelines")
    ... )
    <td...
    See <a ... target="_new">...</a> for more details...


Limitations
-----------

There are some limitations to where we can show guidelines, because
it's not always possible to know what the current context is. The
following pages are known to be affected:

    /bugs/+filebug
    /<distro>/+filebug
    /<distro>/<distroseries>/+filebug
    /<project-group>/+filebug

In all cases, the problem is that the user can change the context
(i.e. distro, package, project) without having to advance a page. This
may mean that no guidelines are shown or the wrong guidelines are
shown.

    >>> user_browser.open("http://launchpad.test/ubuntu/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = "It doesn't work"
    >>> user_browser.getControl("Continue").click()
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             user_browser.contents, "bug-reporting-guidelines"
    ...         )
    ...     )
    ... )
    Ubuntu bug reporting guidelines:
    The version of Ubuntu you're using.
    See http://example.com for more details.

Changing the package to alsa-utils does not make the alsa-utils
guidelines appear.

    >>> user_browser.getControl(name="packagename_option").value = ["choose"]
    >>> user_browser.getControl(name="field.packagename").value = "alsa-utils"
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(
    ...             user_browser.contents, "bug-reporting-guidelines"
    ...         )
    ...     )
    ... )
    Ubuntu bug reporting guidelines:
    The version of Ubuntu you're using.
    See http://example.com for more details.

XXX: allenap 2008-11-14 bug=297743: These limitations have been filed
as bug #297743, "When filing a bug always display the appropriate
reporting guidelines".


Editing the guidelines and description template.
----------------------

Unprivileged Launchpad users do not see the link to the page where the
bug reporting guidelines and the bug description template can be changed,
but admins do.

    >>> import re
    >>> import sys

    >>> def extract_text_from_link(link):
    ...     pass
    ...

    >>> edit_url_re = re.compile(r".*/\+edit$")
    >>> for context_name, context_path, view in contexts:
    ...     overview_url = "http://launchpad.test/%s" % (context_path,)
    ...     print("* " + context_name)
    ...     print("  - User:", end=" ")
    ...     user_browser.open(overview_url)
    ...     try:
    ...         user_browser.getLink(url=edit_url_re)
    ...     except Exception:
    ...         print(sys.exc_info()[0].__name__)
    ...     print("  - Admin:", end=" ")
    ...     admin_browser.open(overview_url)
    ...     print(bool(admin_browser.getLink(url=edit_url_re)))
    ...
    * Ubuntu
      - User: LinkNotFoundError
      - Admin: True
    * Mozilla
      - User: LinkNotFoundError
      - Admin: True
    * Firefox
      - User: LinkNotFoundError
      - Admin: True
    * alsa-utils in Ubuntu
      - User: LinkNotFoundError
      - Admin: True

Unprivileged cannot access the page for changing the bug reporting
guidelines and the bug template.

    >>> for context_name, context_path, view in contexts:
    ...     edit_url = "http://launchpad.test/%s/%s" % (context_path, view)
    ...     print("* " + context_name)
    ...     try:
    ...         user_browser.open(edit_url)
    ...     except Exception:
    ...         print(sys.exc_info()[0].__name__)
    ...
    * Ubuntu
      Unauthorized
    * Mozilla
      Unauthorized
    * Firefox
      Unauthorized
    * alsa-utils in Ubuntu
      Unauthorized
