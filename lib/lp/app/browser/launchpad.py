# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser code for the launchpad application."""

__all__ = [
    "AppFrontPageSearchView",
    "ExceptionHierarchy",
    "Hierarchy",
    "IcingFolder",
    "iter_view_registrations",
    "LaunchpadImageFolder",
    "LaunchpadRootNavigation",
    "LinkView",
    "LoginStatus",
    "Macro",
    "MaintenanceMessage",
    "NavigationMenuTabs",
    "SoftTimeoutView",
    "get_launchpad_views",
]


import operator
import os
import re
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlencode

from zope import i18n
from zope.component import (
    getGlobalSiteManager,
    getUtility,
    queryAdapter,
    queryUtility,
)
from zope.datetime import DateTimeError, parseDatetimetz
from zope.i18nmessageid import Message
from zope.interface import Interface, alsoProvides, implementer
from zope.publisher.defaultview import getDefaultViewName
from zope.publisher.interfaces import NotFound
from zope.publisher.interfaces.browser import IBrowserPublisher
from zope.publisher.interfaces.xmlrpc import IXMLRPCRequest
from zope.schema import Choice, TextLine
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy
from zope.traversing.interfaces import IPathAdapter, ITraversable

from lp import _
from lp.answers.interfaces.questioncollection import IQuestionSet
from lp.app.browser.folder import ExportedFolder, ExportedImageFolder
from lp.app.browser.launchpadform import LaunchpadFormView
from lp.app.browser.tales import DurationFormatterAPI, MenuAPI
from lp.app.errors import (
    GoneError,
    NameLookupFailed,
    NotFoundError,
    POSTToNonCanonicalURL,
)
from lp.app.interfaces.headings import IHeadingBreadcrumb, IMajorHeadingView
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.app.interfaces.services import IServiceFactory
from lp.app.widgets.project import ProjectScopeWidget
from lp.blueprints.interfaces.specification import ISpecificationSet
from lp.blueprints.interfaces.sprint import ISprintSet
from lp.bugs.interfaces.bug import IBugSet
from lp.bugs.interfaces.malone import IMaloneApplication
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.charms.interfaces.charmbase import ICharmBaseSet
from lp.charms.interfaces.charmrecipe import ICharmRecipeSet
from lp.code.errors import (
    CannotHaveLinkedBranch,
    InvalidNamespace,
    NoLinkedBranch,
)
from lp.code.interfaces.branch import IBranchSet
from lp.code.interfaces.branchlookup import IBranchLookup
from lp.code.interfaces.codehosting import IBazaarApplication
from lp.code.interfaces.codeimport import ICodeImportSet
from lp.code.interfaces.gitlookup import IGitLookup
from lp.code.interfaces.gitrepository import IGitRepositorySet
from lp.crafts.interfaces.craftrecipe import ICraftRecipeSet
from lp.layers import WebServiceLayer
from lp.registry.enums import VCSType
from lp.registry.interfaces.announcement import IAnnouncementSet
from lp.registry.interfaces.codeofconduct import ICodeOfConductSet
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.karma import IKarmaActionSet
from lp.registry.interfaces.nameblocklist import INameBlocklistSet
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.pillar import IPillarNameSet
from lp.registry.interfaces.poll import IPollSet
from lp.registry.interfaces.product import (
    InvalidProductName,
    IProduct,
    IProductSet,
)
from lp.registry.interfaces.projectgroup import IProjectGroupSet
from lp.registry.interfaces.role import IPersonRoles
from lp.registry.interfaces.sourcepackagename import ISourcePackageNameSet
from lp.rocks.interfaces.rockbase import IRockBaseSet
from lp.rocks.interfaces.rockrecipe import IRockRecipeSet
from lp.services.config import config
from lp.services.features import getFeatureFlag
from lp.services.features.interfaces import IFeatureRules
from lp.services.helpers import intOrZero
from lp.services.identity.interfaces.account import AccountStatus
from lp.services.propertycache import cachedproperty
from lp.services.statistics.interfaces.statistic import ILaunchpadStatisticSet
from lp.services.temporaryblobstorage.interfaces import (
    ITemporaryStorageManager,
)
from lp.services.utils import utc_now
from lp.services.verification.interfaces.logintoken import ILoginTokenSet
from lp.services.webapp import (
    LaunchpadView,
    Link,
    Navigation,
    StandardLaunchpadFacets,
    canonical_name,
    canonical_url,
    stepto,
)
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.breadcrumb import Breadcrumb
from lp.services.webapp.escaping import structured
from lp.services.webapp.interfaces import (
    IBreadcrumb,
    ICanonicalUrlData,
    IFacet,
    ILaunchBag,
    ILaunchpadRoot,
    IMultiFacetedBreadcrumb,
    INavigationMenu,
)
from lp.services.webapp.menu import get_facet
from lp.services.webapp.publisher import RedirectionView, redirection
from lp.services.webapp.url import urlappend
from lp.services.worlddata.interfaces.country import ICountrySet
from lp.services.worlddata.interfaces.language import ILanguageSet
from lp.snappy.interfaces.snap import ISnapSet
from lp.snappy.interfaces.snapbase import ISnapBaseSet
from lp.snappy.interfaces.snappyseries import ISnappySeriesSet
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.interfaces.binarypackagename import IBinaryPackageNameSet
from lp.soyuz.interfaces.livefs import ILiveFSSet
from lp.soyuz.interfaces.packageset import IPackagesetSet
from lp.testopenid.interfaces.server import ITestOpenIDApplication
from lp.translations.interfaces.translationgroup import ITranslationGroupSet
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue,
)
from lp.translations.interfaces.translations import IRosettaApplication


class IFacetBreadcrumb(Interface):
    pass


class NavigationMenuTabs(LaunchpadView):
    """View class that helps its template render the navigation menu tabs.

    Nothing at all is rendered if there are no navigation menu items.
    """

    def initialize(self):
        menuapi = MenuAPI(self.context)
        self.links = sorted(
            (
                link
                for link in menuapi.navigation.values()
                if (link.enabled or config.launchpad.devmode)
            ),
            key=operator.attrgetter("sort_key"),
        )
        self.title = None
        if len(self.links) > 0:
            facet = menuapi.selectedfacetname()
            menu = queryAdapter(self.context, INavigationMenu, name=facet)
            if menu is not None:
                self.title = menu.title
        self.enabled_links = [link for link in self.links if link.enabled]

    def render(self):
        if not self.links:
            return ""
        else:
            return self.template()


class LinkView(LaunchpadView):
    """View class that helps its template render a menu link.

    The link is not rendered if it's not enabled and we are not in development
    mode.
    """

    MODIFY_ICONS = ("edit", "remove", "trash-icon")

    @property
    def sprite_class(self):
        """Return the class used to display the link's icon."""
        if self.context.icon in self.MODIFY_ICONS:
            # The 3.0 UI design says these are displayed like other icons
            # But they do not have the same use so we want to keep this rule
            # separate.
            return "sprite modify"
        else:
            return "sprite"

    def render(self):
        """Render the menu link if it's enabled or we're in dev mode."""
        if self.context.enabled or config.launchpad.devmode:
            # XXX: Tom Berger 2008-04-16 bug=218706:
            # We strip the result of the template rendering
            # since ZPT seems to always insert a line break
            # at the end of an embedded template.
            return self.template().strip()
        else:
            return ""

    @property
    def css_class(self):
        """Return the CSS class."""
        value = ["menu-link-%s" % self.context.name]
        if not self.context.linked:
            value.append("nolink")
        if self.context.icon:
            value.append(self.sprite_class)
            value.append(self.context.icon)
        if self.context.hidden:
            value.append("hidden")
        return " ".join(value)

    @property
    def url(self):
        """Return the url if linked."""
        if self.context.linked:
            return self.context.url
        return ""

    @property
    def summary(self):
        """Return the summary if linked."""
        if self.context.linked:
            return self.context.summary
        return ""


class Hierarchy(LaunchpadView):
    """The heading, title, facet links and breadcrumbs parts of each page."""

    @property
    def objects(self):
        """The objects for which we want breadcrumbs."""
        # Start the chain with the deepest object that has a breadcrumb.
        try:
            objects = [
                next(
                    obj
                    for obj in reversed(self.request.traversed_objects)
                    if IBreadcrumb(obj, None)
                )
            ]
        except StopIteration:
            return []
        # Now iterate. If an object has a breadcrumb, it can override
        # its parent. Otherwise we just follow the normal URL hierarchy
        # until we reach the end.
        while True:
            next_obj = None
            breadcrumb = IBreadcrumb(objects[0], None)
            if breadcrumb is not None:
                next_obj = breadcrumb.inside
            if next_obj is None:
                urldata = ICanonicalUrlData(objects[0], None)
                if urldata is not None:
                    next_obj = urldata.inside
            if next_obj is None:
                break
            objects.insert(0, next_obj)
        return objects

    @cachedproperty
    def items(self):
        """Return a list of `IBreadcrumb` objects visible in the hierarchy.

        The list starts with the breadcrumb closest to the hierarchy root.
        """
        breadcrumbs = []
        for obj in self.objects:
            breadcrumb = IBreadcrumb(obj, None)
            if breadcrumb is not None:
                breadcrumbs.append(breadcrumb)

        facet = queryUtility(IFacet, name=get_facet(self._naked_context_view))
        if breadcrumbs and facet is not None:
            # We have breadcrumbs and we're on a custom facet, so we'll
            # sneak an extra breadcrumb for the facet we're on.
            # Iterate over the context of our breadcrumbs in reverse order and
            # find the first one that implements IMultiFactedBreadcrumb.
            # It'll be facet-agnostic, so insert a facet-specific one
            # after it.
            for idx, breadcrumb in reversed(list(enumerate(breadcrumbs))):
                if IMultiFacetedBreadcrumb.providedBy(breadcrumb):
                    facet_crumb = Breadcrumb(
                        breadcrumb.context,
                        rootsite=facet.rootsite,
                        text=facet.text,
                    )
                    alsoProvides(facet_crumb, IFacetBreadcrumb)
                    breadcrumbs.insert(idx + 1, facet_crumb)
                    # Ensure that all remaining breadcrumbs are
                    # themselves faceted.
                    for remaining_crumb in breadcrumbs[idx + 1 :]:
                        remaining_crumb.rootsite_override = facet.rootsite
                    break
        if len(breadcrumbs) > 0:
            breadcrumbs.extend(self.makeBreadcrumbsForRequestedPage())
        return breadcrumbs

    @property
    def items_for_body(self):
        """Return breadcrumbs to display in the page body's hierarchy section.

        While the entire sequence of breadcrumbs must be included in the
        document title, the first 0-3 are represented specially in the header
        (headings and facet links), so we don't want to duplicate them in the
        main content.
        """
        crumbs = []
        for crumb in self.items:
            if IHeadingBreadcrumb.providedBy(
                crumb
            ) or IFacetBreadcrumb.providedBy(crumb):
                crumbs = []
                continue
            crumbs.append(crumb)
        return crumbs

    @property
    def _naked_context_view(self):
        """Return the unproxied view for the context of the hierarchy."""
        # XXX wgrant 2014-11-16: Should just be able to use self.context
        # here, but some views end up delegating to things that don't
        # have __name__ or __launchpad_facetname__.
        if len(self.request.traversed_objects) > 0:
            return removeSecurityProxy(self.request.traversed_objects[-1])
        else:
            return None

    def makeBreadcrumbsForRequestedPage(self):
        """Return a sequence of `IBreadcrumb`s for the requested page.

        The `IBreadcrumb` for the requested page is created using the current
        URL and the page's name (i.e. the last path segment of the URL).

        If the view is the default one for the object or the current
        facet, no breadcrumbs are returned -- we'll have injected a
        facet Breadcrumb earlier in the hierarchy which links here.
        """
        url = self.request.getURL()
        obj = self.request.traversed_objects[-2]
        default_view_name = getDefaultViewName(obj, self.request)
        view = self._naked_context_view
        default_views = [default_view_name]
        facet = queryUtility(IFacet, name=get_facet(view))
        if facet is not None:
            default_views.append(facet.default_view)
        crumbs = []

        # Views may provide an additional breadcrumb to precede them.
        # This is useful to have an add view link back to its
        # collection despite its parent being the context of the collection.
        if hasattr(view, "inside_breadcrumb"):
            crumbs.append(view.inside_breadcrumb)

        if hasattr(view, "__name__") and view.__name__ not in default_views:
            title = getattr(view, "page_title", None)
            if title is None:
                title = getattr(view, "label", None)
            if isinstance(title, Message):
                title = i18n.translate(title, context=self.request)
            crumbs.append(Breadcrumb(None, url=url, text=title))
        return crumbs

    @property
    def display_breadcrumbs(self):
        """Return whether the breadcrumbs should be displayed."""
        # If there is only one breadcrumb then it does not make sense
        # to display it as it will simply repeat the context.title.
        # If the view is an IMajorHeadingView then we do not want
        # to display breadcrumbs either.
        has_major_heading = IMajorHeadingView.providedBy(
            self._naked_context_view
        )
        return len(self.items_for_body) > 1 and not has_major_heading

    @property
    def heading_breadcrumbs(self):
        crumbs = [
            crumb
            for crumb in self.items
            if IHeadingBreadcrumb.providedBy(crumb)
        ]
        assert len(crumbs) <= 2
        return crumbs

    def heading(self):
        """Return the heading markup for the page.

        If the context provides `IMajorHeadingView` then we return an
        H1, else an H2.
        """
        # The title is static, but only the index view gets an H1.
        tag = "h1" if IMajorHeadingView.providedBy(self.context) else "h2"
        # If there is actually no root context, then it's a top-level
        # context-less page so Launchpad.net is shown as the branding.
        crumb_markups = []
        for crumb in self.heading_breadcrumbs:
            crumb_markups.append(
                structured('<a href="%s">%s</a>', crumb.url, crumb.detail)
            )
        if not crumb_markups:
            crumb_markups.append(structured("<span>Launchpad.net</span>"))
        content = structured(
            "<br />".join(["%s"] * len(crumb_markups)), *crumb_markups
        )
        return structured(
            '<%s id="watermark-heading">%s</%s>', tag, content, tag
        ).escapedtext

    def logo(self):
        """Return the logo image for the top header breadcrumb's context."""
        logo_context = (
            self.heading_breadcrumbs[0].context
            if self.heading_breadcrumbs
            else None
        )
        adapter = queryAdapter(logo_context, IPathAdapter, "image")
        if logo_context is not None:
            return structured(
                '<a href="%s">%s</a>',
                canonical_url(logo_context, rootsite="mainsite"),
                structured(adapter.logo()),
            ).escapedtext
        else:
            return adapter.logo()


class ExceptionHierarchy(Hierarchy):
    @property
    def objects(self):
        """Return an empty list because the traversal is not safe or sane."""
        return []


@implementer(IBrowserPublisher, ITraversable)
class Macro:
    """Keeps templates that are registered as pages from being URL accessible.

    The standard pattern in LP is to register templates that contain macros as
    views on all objects:

    <browser:page
        for="*"
        name="+main-template-macros"
        template="../templates/base-layout-macros.pt"
        permission="zope.Public"
        />

    Without this class, that pattern would make the template URL traversable
    from any object.  Therefore requests like these would all "work":

        http://launchpad.net/+main-template-macros
        http://launchpad.net/ubuntu/+main-template-macros
        http://launchpad.net/ubuntu/+main-template-macros
        https://blueprints.launchpad.test/ubuntu/hoary/+main-template-macros

    Obviously, those requests wouldn't do anything useful and would instead
    generate an OOPS.

    It would be nice to use a different pattern for macros instead, but we've
    grown dependent on some of the peculiatrities of registering macro
    templates in this way.

    This class was created in order to prevent macro templates from being
    accessible via URL without having to make nontrivial changes to the many,
    many templates that use macros.  To use the class add a "class" parameter
    to macro template registrations:

    <browser:page
        for="*"
        name="+main-template-macros"
        template="../templates/base-layout-macros.pt"
        class="lp.app.browser.launchpad.Macro"
        permission="zope.Public"
        />
    """

    def __init__(self, context, request):
        self.context = context

    def traverse(self, name, furtherPath):
        return self.index.macros[name]

    def browserDefault(self, request):
        return self, ()

    def publishTraverse(self, request, name):
        raise NotFound(self.context, self.__name__)

    def __call__(self):
        raise NotFound(self.context, self.__name__)


class MaintenanceMessage:
    """Display a maintenance message if the control file is present and
    it contains a valid iso format time.

    The maintenance message shows the approximate time before launchpad will
    be taken offline for maintenance.

    The control file is +maintenancetime.txt in the launchpad root.

    If there is no maintenance message, an empty string is returned.

    If the maintenance time is too far in the future, then an empty string
    is returned.

    If the maintenance time is in the past, then the maintenance message says
    that Launchpad will go offline "very very soon".

    If the text in the maintenance message is poorly formatted, then an
    empty string is returned, and a warning should be logged.
    """

    timelefttext = None
    featuretext = None

    notmuchtime = timedelta(seconds=30)
    toomuchtime = timedelta(seconds=1800)  # 30 minutes

    def __call__(self):
        if os.path.exists("+maintenancetime.txt"):
            with open("+maintenancetime.txt") as f:
                message = f.read()
            try:
                maintenancetime = parseDatetimetz(message)
            except DateTimeError:
                # XXX SteveAlexander 2005-09-22: log a warning here.
                return ""
            timeleft = maintenancetime - utc_now()
            if timeleft > self.toomuchtime:
                return ""
            elif timeleft < self.notmuchtime:
                self.timelefttext = "very very soon"
            else:
                self.timelefttext = "in %s" % (
                    DurationFormatterAPI(timeleft).approximateduration()
                )
        self.featuretext = getFeatureFlag("app.maintenance_message")
        if self.timelefttext or self.featuretext:
            return self.index()
        return ""


class LaunchpadRootFacets(StandardLaunchpadFacets):
    usedfor = ILaunchpadRoot
    enable_only = [
        "overview",
        "branches",
        "bugs",
        "specifications",
        "translations",
        "answers",
    ]

    def overview(self):
        target = ""
        text = "Launchpad Home"
        return Link(target, text, site="mainsite")

    def translations(self):
        text = "Translations"
        target = "translations" if self.mainsite_only else ""
        site = "mainsite" if self.mainsite_only else "translations"
        return Link(target, text, site=site)

    def bugs(self):
        text = "Bugs"
        target = "bugs" if self.mainsite_only else ""
        site = "mainsite" if self.mainsite_only else "bugs"
        return Link(target, text, site=site)

    def answers(self):
        text = "Answers"
        target = "questions" if self.mainsite_only else ""
        site = "mainsite" if self.mainsite_only else "answers"
        return Link(target, text, site=site)

    def specifications(self):
        text = "Blueprints"
        target = "specs" if self.mainsite_only else ""
        site = "mainsite" if self.mainsite_only else "blueprints"
        return Link(target, text, site=site)

    def branches(self):
        text = "Code"
        target = "+code" if self.mainsite_only else ""
        site = "mainsite" if self.mainsite_only else "code"
        return Link(target, text, site=site)


class LoginStatus:
    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.user = getUtility(ILaunchBag).user

    @property
    def login_shown(self):
        return self.user is None and "+login" not in self.request["PATH_INFO"]

    @property
    def logged_in(self):
        return self.user is not None

    @property
    def login_url(self):
        query_string = self.request.get("QUERY_STRING", "")

        # If we have a query string, remove some things we don't want, and
        # keep it around.
        if query_string:
            query_dict = parse_qs(query_string, keep_blank_values=True)
            query_dict.pop("loggingout", None)
            query_string = urlencode(sorted(query_dict.items()), doseq=True)
            # If we still have a query_string after things we don't want
            # have been removed, add it onto the url.
            if query_string:
                query_string = "?" + query_string

        # The approach we're taking is to combine the application url with
        # the path_info, taking out path steps that are to do with virtual
        # hosting.  This is not exactly correct, as the application url
        # can have other path steps in it.  We're not using the feature of
        # having other path steps in the application url, so this will work
        # for us, assuming we don't need that in the future.

        # The application_url is typically like 'http://thing:port'. No
        # trailing slash.
        application_url = self.request.getApplicationURL()

        # We're going to use PATH_INFO to remove any spurious '+index' at the
        # end of the URL.  But, PATH_INFO will contain virtual hosting
        # configuration, if there is any.
        path_info = self.request["PATH_INFO"]

        # Remove any virtual hosting segments.
        path_steps = []
        in_virtual_hosting_section = False
        for step in path_info.split("/"):
            if step.startswith("++vh++"):
                in_virtual_hosting_section = True
                continue
            if step == "++":
                in_virtual_hosting_section = False
                continue
            if not in_virtual_hosting_section:
                path_steps.append(step)
        path = "/".join(path_steps)

        # Make the URL stop at the end of path_info so that we don't get
        # spurious '+index' at the end.
        full_url = "%s%s" % (application_url, path)
        if full_url.endswith("/"):
            full_url = full_url[:-1]
        logout_url_end = "/+logout"
        openid_callback_url_end = "/+openid-callback"
        if full_url.endswith(logout_url_end):
            full_url = full_url[: -len(logout_url_end)]
        elif full_url.endswith(openid_callback_url_end):
            full_url = full_url[: -len(openid_callback_url_end)]
        else:
            # No need to remove anything from full_url.
            pass
        return "%s/+login%s" % (full_url, query_string)


class LaunchpadRootNavigation(Navigation):
    usedfor = ILaunchpadRoot

    @stepto("support")
    def redirect_support(self):
        """Redirect /support to launchpad Answers site."""
        target_url = canonical_url(
            getUtility(ILaunchpadCelebrities).launchpad, rootsite="answers"
        )
        return self.redirectSubTree(target_url, status=301)

    @stepto("legal")
    def redirect_legal(self):
        """Redirect /legal to help.launchpad.net/Legal site."""
        return self.redirectSubTree(
            "https://help.launchpad.net/Legal", status=301
        )

    @stepto("faq")
    def redirect_faq(self):
        """Redirect /faq to launchpad-project/+faqs."""
        return self.redirectSubTree(
            "https://answers.launchpad.net/launchpad-project/+faqs", status=301
        )

    @stepto("feedback")
    def redirect_feedback(self):
        """Redirect /feedback to help.launchpad.net/Feedback site."""
        return self.redirectSubTree(
            (
                "https://documentation.ubuntu.com/launchpad/en/latest/user/"
                "reference/launchpad-and-community/feedback-on-launchpad/"
            ),
            status=301,
        )

    @stepto("+branch")
    def redirect_branch(self):
        """Redirect /+branch/<foo> to the branch named 'foo'.

        'foo' can be the unique name of the branch, or any of the aliases for
        the branch.
        If 'foo' resolves to an ICanHasLinkedBranch instance but the linked
        branch is not yet set, redirect back to the referring page with a
        suitable notification message.
        If 'foo' is completely invalid, redirect back to the referring page
        with a suitable error message.
        """

        # The default target url to go to will be back to the referring page
        # (in the case that there is an error resolving the branch url).
        # Note: the http referer may be None if someone has hacked a url
        # directly rather than following a /+branch/<foo> link.
        target_url = self.request.getHeader("referer")
        path = "/".join(self.request.stepstogo)
        try:
            branch, trailing = getUtility(IBranchLookup).getByLPPath(path)
            target_url = canonical_url(branch, request=self.request)
            if trailing != "":
                target_url = urlappend(target_url, trailing)
        except NoLinkedBranch:
            # A valid ICanHasLinkedBranch target exists but there's no
            # branch or it's not visible.

            # If are aren't arriving at this invalid branch URL from
            # another page then we just raise a NotFoundError to generate
            # a 404, otherwise we end up in a bad recursion loop. The
            # target url will be None in that case.
            if target_url is None:
                raise NotFoundError
            self.request.response.addNotification(
                "The target %s does not have a linked branch." % path
            )
        except (
            CannotHaveLinkedBranch,
            InvalidNamespace,
            InvalidProductName,
            NotFoundError,
        ) as e:
            # If are aren't arriving at this invalid branch URL from another
            # page then we just raise a NotFoundError to generate a 404,
            # otherwise we end up in a bad recursion loop. The target url will
            # be None in that case.
            if target_url is None:
                raise NotFoundError
            error_msg = str(e)
            if error_msg == "":
                error_msg = "Invalid branch lp:%s." % path
            self.request.response.addErrorNotification(error_msg)

        return self.redirectSubTree(target_url)

    @stepto("+code")
    def redirect_branch_or_repo(self):
        """Redirect /+code/<foo> to the branch or repository named 'foo'.

        'foo' can be the unique name of the branch/repo, or any of the aliases
        for the branch/repo.

        If 'foo' is invalid, or exists but the user does not have permission to
        view 'foo', a NotFoundError is raised, resulting in a 404 error.

        Unlike +branch, this works for both git and bzr repositories/branches.
        """
        target_url = None
        path = "/".join(self.request.stepstogo)

        # Try a Git repository lookup first, since the schema is simpler and
        # so it's quicker.
        try:
            repository, trailing = getUtility(IGitLookup).getByPath(path)
            if repository is not None:
                target_url = canonical_url(repository, request=self.request)
                if trailing:
                    target_url = urlappend(target_url, trailing)
        except (
            InvalidNamespace,
            InvalidProductName,
            NameLookupFailed,
            Unauthorized,
        ):
            # Either the git repository wasn't found, or it was found but we
            # lack authority to access it. In either case, attempt a bzr lookup
            # so don't set target_url
            pass

        # Attempt a bzr lookup as well:
        try:
            branch, trailing = getUtility(IBranchLookup).getByLPPath(path)
            bzr_url = canonical_url(branch, request=self.request)
            if trailing != "":
                bzr_url = urlappend(bzr_url, trailing)

            if target_url and branch.product is not None:
                # Project has both a bzr branch and a git repo. There's no
                # right thing we can do here, so pretend we didn't see
                # anything at all.
                if branch.product.vcs is None:
                    target_url = None
                # if it's set to BZR, then set this branch as the target
                if branch.product.vcs == VCSType.BZR:
                    target_url = bzr_url
            else:
                target_url = bzr_url
        except (
            NoLinkedBranch,
            CannotHaveLinkedBranch,
            InvalidNamespace,
            InvalidProductName,
            NotFoundError,
        ):
            # No bzr branch found either.
            pass

        # Either neither bzr nor git returned matches, or they did but we're
        # not authorised to view them, or they both did and the project has not
        # set its 'vcs' property to indicate which one to prefer. In all cases
        # raise a 404:
        if not target_url:
            raise NotFoundError

        return self.redirectSubTree(target_url)

    @stepto("+builds")
    def redirect_buildfarm(self):
        """Redirect old /+builds requests to new URL, /builders."""
        new_url = "/builders"
        return self.redirectSubTree(
            urlappend(new_url, "/".join(self.request.stepstogo))
        )

    @redirection("+feature-info", status=301)
    def redirect_feature_info(self):
        return "/+feature-rules/info"

    @redirection("+feature-changelog", status=301)
    def redirect_feature_changelog(self):
        return "/+feature-rules/changelog"

    @redirection("+nameblacklist", status=301)  # wokeignore:rule=blacklist
    def redirect_nameblacklist(self):  # wokeignore:rule=blacklist
        return "+nameblocklist"

    # XXX cprov 2009-03-19 bug=345877: path segments starting with '+'
    # should never correspond to a valid traversal, they confuse the
    # hierarchical navigation model.
    stepto_utilities = {
        "+announcements": IAnnouncementSet,
        "archives": IArchiveSet,
        "+services": IServiceFactory,
        "binarypackagenames": IBinaryPackageNameSet,
        "branches": IBranchSet,
        "bugs": IMaloneApplication,
        "builders": IBuilderSet,
        "+charm-bases": ICharmBaseSet,
        "+charm-recipes": ICharmRecipeSet,
        "+code-index": IBazaarApplication,
        "+code-imports": ICodeImportSet,
        "codeofconduct": ICodeOfConductSet,
        "+countries": ICountrySet,
        "+craft-recipes": ICraftRecipeSet,
        "distros": IDistributionSet,
        "+git": IGitRepositorySet,
        "karmaaction": IKarmaActionSet,
        "+imports": ITranslationImportQueue,
        "+languages": ILanguageSet,
        "livefses": ILiveFSSet,
        "+nameblocklist": INameBlocklistSet,
        "package-sets": IPackagesetSet,
        "people": IPersonSet,
        "pillars": IPillarNameSet,
        "+polls": IPollSet,
        "+processors": IProcessorSet,
        "projects": IProductSet,
        "projectgroups": IProjectGroupSet,
        "+rock-bases": IRockBaseSet,
        "+rock-recipes": IRockRecipeSet,
        "+snaps": ISnapSet,
        "+snap-bases": ISnapBaseSet,
        "+snappy-series": ISnappySeriesSet,
        "sourcepackagenames": ISourcePackageNameSet,
        "specs": ISpecificationSet,
        "sprints": ISprintSet,
        "+statistics": ILaunchpadStatisticSet,
        "token": ILoginTokenSet,
        "+groups": ITranslationGroupSet,
        "translations": IRosettaApplication,
        "testopenid": ITestOpenIDApplication,
        "questions": IQuestionSet,
        "temporary-blobs": ITemporaryStorageManager,
        "+feature-rules": IFeatureRules,
        # These three have been renamed, and no redirects done, as the old
        # urls now point to the product pages.
        # "bazaar": IBazaarApplication,
        # "malone": IMaloneApplication,
        # "rosetta": IRosettaApplication,
    }

    @stepto("products")
    def products(self):
        return self.redirectSubTree(
            canonical_url(getUtility(IProductSet)), status=301
        )

    def traverse(self, name):
        if name in self.stepto_utilities:
            return getUtility(self.stepto_utilities[name])

        if name == "~":
            person = getUtility(ILaunchBag).user
            if person is None:
                raise Unauthorized()
            # Keep the context and the subtree so that
            # bugs.l.n/~/+assignedbugs goes to the person's canonical
            # assigned list.
            return self.redirectSubTree(
                canonical_url(self.context)
                + "~"
                + canonical_name(person.name),
                status=302,
            )
        elif name.startswith("~"):  # Allow traversal to ~foo for People
            if canonical_name(name) != name:
                # (for instance, uppercase username?)
                if self.request.method == "POST":
                    raise POSTToNonCanonicalURL
                return self.redirectSubTree(
                    canonical_url(self.context) + canonical_name(name),
                    status=301,
                )
            else:
                person = getUtility(IPersonSet).getByName(name[1:])
                if person is None:
                    return person
                # Check to see if this is a team, and if so, whether the
                # logged in user is allowed to view the team, by virtue of
                # team membership or Launchpad administration.
                if person.is_team and not check_permission(
                    "launchpad.LimitedView", person
                ):
                    return None
                # Only admins are permitted to see suspended users.
                if person.account_status == AccountStatus.SUSPENDED:
                    if not check_permission("launchpad.Moderate", person):
                        raise GoneError("User is suspended: %s" % name)
                if person.account_status == AccountStatus.PLACEHOLDER:
                    if not check_permission("launchpad.Moderate", person):
                        return None
                return person

        # Dapper and Edgy shipped with https://launchpad.net/bazaar hard coded
        # into the Bazaar Launchpad plugin (part of Bazaar core). So in theory
        # we need to support this URL until 2011 (although I suspect the API
        # will break much sooner than that) or updates sent to
        # {dapper,edgy}-updates. Probably all irrelevant, as I suspect the
        # number of people using the plugin in edgy and dapper is 0.
        if name == "bazaar" and IXMLRPCRequest.providedBy(self.request):
            return getUtility(IBazaarApplication)

        # account for common typing mistakes
        if canonical_name(name) != name:
            if self.request.method == "POST":
                raise POSTToNonCanonicalURL
            return self.redirectSubTree(
                (
                    canonical_url(self.context, request=self.request)
                    + canonical_name(name)
                ),
                status=301,
            )

        pillar = getUtility(IPillarNameSet).getByName(
            name, ignore_inactive=False
        )

        if pillar is None:
            return None

        if IProduct.providedBy(pillar):
            if not pillar.active:
                # Emergency brake for public but inactive products:
                # These products should not be shown to ordinary users.
                # The root problem is that many views iterate over products,
                # inactive products included, and access attributes like
                # name, displayname or call canonical_url(product) --
                # and finally throw the data away, if the product is
                # inactive. So we cannot make these attributes inaccessible
                # for inactive public products. On the other hand, we
                # require the permission launchpad.View to protect private
                # products.
                # This means that we cannot simply check if the current
                # user has the permission launchpad.View for an inactive
                # product.
                user = getUtility(ILaunchBag).user
                if user is None:
                    return None
                user = IPersonRoles(user)
                if (
                    not user.in_commercial_admin
                    and not user.in_admin
                    and not user.in_registry_experts
                ):
                    return None
        if check_permission("launchpad.LimitedView", pillar):
            if pillar.name != name:
                # This pillar was accessed through one of its aliases, so we
                # must redirect to its canonical URL.
                return self.redirectSubTree(
                    canonical_url(pillar, self.request), status=301
                )
            return pillar
        return None

    def _getBetaRedirectionView(self):
        # If the inhibit_beta_redirect cookie is set, don't redirect.
        if self.request.cookies.get("inhibit_beta_redirect", "0") == "1":
            return None

        # If we are looking at the front page, don't redirect.
        if self.request["PATH_INFO"] == "/":
            return None

        # If this is a HTTP POST, we don't want to issue a redirect.
        # Doing so would go against the HTTP standard.
        if self.request.method == "POST":
            return None

        # If this is a web service request, don't redirect.
        if WebServiceLayer.providedBy(self.request):
            return None

        # If the request is for a bug then redirect straight to that bug.
        bug_match = re.match(r"/bugs/(\d+)$", self.request["PATH_INFO"])
        if bug_match:
            bug_number = bug_match.group(1)
            bug_set = getUtility(IBugSet)
            try:
                bug = bug_set.get(bug_number)
            except NotFoundError:
                raise NotFound(self.context, bug_number)
            if not check_permission("launchpad.View", bug):
                return None
            # Empty the traversal stack, since we're redirecting.
            self.request.setTraversalStack([])
            # And perform a temporary redirect.
            return RedirectionView(
                canonical_url(bug.default_bugtask), self.request, status=303
            )
        # Explicit catchall - do not redirect.
        return None

    def publishTraverse(self, request, name):
        beta_redirection_view = self._getBetaRedirectionView()
        if beta_redirection_view is not None:
            return beta_redirection_view
        return Navigation.publishTraverse(self, request, name)


class SoftTimeoutView(LaunchpadView):
    def __call__(self):
        """Generate a soft timeout by sleeping enough time."""
        start_time = time.time()
        celebrities = getUtility(ILaunchpadCelebrities)
        if self.user is None or not self.user.inTeam(
            celebrities.launchpad_developers
        ):
            raise Unauthorized

        self.request.response.setHeader("content-type", "text/plain")
        soft_timeout = intOrZero(config.database.soft_request_timeout)
        if soft_timeout == 0:
            return "No soft timeout threshold is set."

        time.sleep(soft_timeout / 1000.0)
        time_to_generate_page = (time.time() - start_time) * 1000
        # In case we didn't sleep enough time, sleep a while longer to
        # pass the soft timeout threshold.
        while time_to_generate_page < soft_timeout:
            time.sleep(0.1)
            time_to_generate_page = (time.time() - start_time) * 1000
        return (
            "Soft timeout threshold is set to %s ms. This page took"
            " %s ms to render." % (soft_timeout, time_to_generate_page)
        )


class IcingFolder(ExportedFolder):
    """Export the Launchpad icing."""

    export_subdirectories = True

    folder = os.path.join(config.root, "lib/canonical/launchpad/icing/")


class LaunchpadImageFolder(ExportedImageFolder):
    """Export the Launchpad images - supporting retrieval without extension."""

    folder = os.path.join(config.root, "lib/canonical/launchpad/images/")


class LaunchpadTourFolder(ExportedFolder):
    """Export a launchpad tour folder.

    This exported folder supports traversing to subfolders.
    """

    folder = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "../tour/"
    )

    export_subdirectories = True

    def publishTraverse(self, request, name):
        """Hide the source directory.

        The source directory contains source material that we don't want
        published over the web.
        """
        if name == "source":
            raise NotFound(request, name)
        return super().publishTraverse(request, name)

    def browserDefault(self, request):
        """Redirect to index.html if the directory itself is requested."""
        if len(self.names) == 0:
            return (
                RedirectionView(
                    "%s+tour/index" % canonical_url(self.context),
                    self.request,
                    status=302,
                ),
                (),
            )
        else:
            return self, ()


class LaunchpadAPIDocFolder(ExportedFolder):
    """Export the API documentation."""

    folder = os.path.join(config.root, "lib/canonical/launchpad/apidoc/")

    def browserDefault(self, request):
        """Traverse to index.html if the directory itself is requested."""
        if len(self.names) == 0:
            return self, ("index.html",)
        else:
            return self, ()


class IAppFrontPageSearchForm(Interface):
    """Schema for the app-specific front page search question forms."""

    search_text = TextLine(title=_("Search text"), required=False)

    scope = Choice(
        title=_("Search scope"),
        required=False,
        vocabulary="DistributionOrProductOrProjectGroup",
    )


class AppFrontPageSearchView(LaunchpadFormView):
    schema = IAppFrontPageSearchForm
    custom_widget_scope = ProjectScopeWidget

    @property
    def scope_css_class(self):
        """The CSS class for used in the scope widget."""
        if self.scope_error:
            return "error"
        else:
            return None

    @property
    def scope_error(self):
        """The error message for the scope widget."""
        return self.getFieldError("scope")


def get_launchpad_views(cookies):
    """The state of optional page elements the user may choose to view.

    :param cookies: The request.cookies object that contains launchpad_views.
    :return: A dict of all the view states.
    """
    views = {
        "small_maps": True,
    }
    cookie = cookies.get("launchpad_views", "")
    if len(cookie) > 0:
        pairs = cookie.split("&")
        for pair in pairs:
            parts = pair.split("=")
            if len(parts) != 2:
                # The cookie is malformed, possibly hacked.
                continue
            key, value = parts
            if key not in views:
                # The cookie may be hacked.
                continue
            # 'false' is the value that the browser script sets to disable a
            # part of a page. Any other value is considered to be 'true'.
            views[key] = value != "false"
    return views


def iter_view_registrations(cls):
    """Iterate through the AdapterRegistrations of a view.

    The input must be the final registered form of the class, which is
    typically a SimpleViewClass variant.
    """
    for registration in getGlobalSiteManager().registeredAdapters():
        if registration.factory == cls:
            yield registration
