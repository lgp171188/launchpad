Bug Export
==========

Some projects require regular exports of their bugs as a condition of
using Launchpad.  This provides them an exit strategy in the event that
they can't use Launchpad anymore.

Since the aim is to provide an export of a product's bugs, we don't
export information about all bug tasks -- only those for the product in
question.

The export is also limited to bug information -- it does not include
links to other Launchpad features such as specifications or questions.


Exporting one bug
-----------------

We will export bug #1 in the context of Firefox.  First some initial
setup:

    >>> import io
    >>> import sys
    >>> try:
    ...     import xml.etree.ElementTree as ET
    ... except ImportError:
    ...     import ElementTree as ET
    ...
    >>> from zope.component import getUtility
    >>> from lp.bugs.interfaces.bug import IBugSet
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from lp.bugs.scripts.bugexport import (
    ...     serialise_bugtask,
    ...     export_bugtasks,
    ... )

First get the bug task:

    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> bug1 = getUtility(IBugSet).get(1)
    >>> bugtask = bug1.bugtasks[0]
    >>> bugtask.target == firefox
    True

Now we serialise it as XML, and print it:

    >>> node = serialise_bugtask(bugtask)
    >>> tree = ET.ElementTree(node)
    >>> output = io.BytesIO()
    >>> tree.write(output)
    >>> print(output.getvalue().decode("UTF-8"))
    <bug id="1">
    <private>False</private>
    <security_related>False</security_related>
    <datecreated>2004-01-01T20:58:04Z</datecreated>
    <title>Firefox does not support SVG</title>
    <description>Firefox needs to support embedded SVG images, now that the
    standard has been finalised.
    <BLANKLINE>
    The SVG standard 1.0 is complete, and draft implementations for Firefox
    exist. One of these implementations needs to be integrated with the base
    install of Firefox. Ideally, the implementation needs to include support
    for the manipulation of SVG objects from JavaScript to enable interactive
    and dynamic SVG drawings.</description>
    <reporter name="name12">Sample Person</reporter>
    <status>NEW</status>
    <importance>LOW</importance>
    <assignee name="mark">Mark Shuttleworth</assignee>
    <subscriptions>
    <subscriber name="name12">Sample Person</subscriber>
    <subscriber name="stevea">Steve Alexander</subscriber>
    </subscriptions>
    <comment>
    <sender name="name12">Sample Person</sender>
    <date>2004-09-24T21:17:17Z</date>
    <text>We've seen something very similar on AIX with Gnome 2.6 when it is
    compiled with XFT support. It might be that the anti-aliasing is causing
    loopback devices to degrade, resulting in a loss of transparency at the
    system cache level and decoherence in the undelete function. This is only
    known to be a problem when the moon is gibbous.</text>
    </comment>
    <comment>
    <sender name="name12">Sample Person</sender>
    <date>2004-09-24T21:24:03Z</date>
    <text>Sorry, it was SCO unix which appears to have the same bug. For a
    brief moment I was confused there, since so much code is known to have
    been copied from SCO into AIX.</text>
    </comment>
    </bug>


Exporting a Product's Bugs
--------------------------

Rather than exporting a single bug, we'll usually want to export all the
bugs for a product.  The export_bugtasks() function does this by
successively serialising each of the tasks for that product.

    >>> import transaction
    >>> export_bugtasks(
    ...     transaction, firefox, getattr(sys.stdout, "buffer", sys.stdout)
    ... )
    <launchpad-bugs xmlns="https://launchpad.net/xmlns/2006/bugs">
    <bug id="1">
    ...
    </bug>
    <bug id="4">
    ...
    <title>Reflow problems with complex page layouts</title>
    ...
    <tags>
    <tag>layout-test</tag>
    </tags>
    ...
    </bug>
    <bug id="5">
    ...
    <title>Firefox install instructions should be complete</title>
    ...
    </bug>
    <bug id="6">
    ...
    <duplicateof>5</duplicateof>
    ...
    <title>Firefox crashes when Save As dialog for a nonexistent window is
    closed</title>
    ...
    ...
    </bug>
    </launchpad-bugs>


Attachments
-----------

Attachments are included in the XML dump.  First add an attachment to
bug #1.  We need to commit here so that the librarian can later serve
the file when we later serialise the bug:

    >>> login("test@canonical.com")
    >>> bug4 = getUtility(IBugSet).get(4)
    >>> sampleperson = getUtility(IPersonSet).getByEmail("test@canonical.com")
    >>> bug4.addAttachment(
    ...     owner=sampleperson,
    ...     data=io.BytesIO(b"Hello World"),
    ...     comment="Added attachment",
    ...     filename="hello.txt",
    ...     url=None,
    ...     description='"Hello World" attachment',
    ... )
    <BugAttachment ...>
    >>> bug4.addAttachment(
    ...     owner=sampleperson,
    ...     data=None,
    ...     comment="Added attachment with URL",
    ...     filename=None,
    ...     url="https://launchpad.net/",
    ...     description=None,
    ... )
    <BugAttachment ...>

    >>> transaction.commit()

A reference to the attachment is included with the new comment with the
attachment contents encoded using base-64:

    >>> node = serialise_bugtask(bug4.bugtasks[0])
    >>> tree = ET.ElementTree(node)
    >>> tree.write(sys.stdout)
    <bug id="4">
    ...
    <comment>
    <sender name="name12">Sample Person</sender>
    <date>...</date>
    <text>Added attachment</text>
    <attachment href="http://bugs.launchpad.test/bugs/4/.../+files/hello.txt">
    <type>UNSPECIFIED</type>
    <title>"Hello World" attachment</title>
    <filename>hello.txt</filename>
    <mimetype>text/plain</mimetype>
    <contents>SGVsbG8gV29ybGQ=
    </contents>
    </attachment>
    </comment>
    <comment>
    <sender name="name12">Sample Person</sender>
    <date>...</date>
    <text>Added attachment with URL</text>
    <attachment href="https://launchpad.net/">
    <type>UNSPECIFIED</type>
    <title>https://launchpad.net/</title>
    </attachment>
    ...


Private Bugs
------------

By default a bug export will not include any private bugs.  However,
they can be included by passing the --include-private flag to the import
script.  To test this, we'll make a bug private:

    >>> bug4.setPrivate(True, getUtility(ILaunchBag).user)
    True

    >>> transaction.commit()

Now we'll do a dump not including private bugs:

    >>> output = io.BytesIO()
    >>> export_bugtasks(transaction, firefox, output)
    >>> b'<bug id="4">' in output.getvalue()
    False

However, bug #4 will appear in the export if we include private bugs:

    >>> output = io.BytesIO()
    >>> export_bugtasks(transaction, firefox, output, include_private=True)
    >>> b'<bug id="4">' in output.getvalue()
    True
