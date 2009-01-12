# Copyright 2004-2008 Canonical Ltd

"""Person-related view classes."""

__metaclass__ = type

__all__ = [
    'BeginTeamClaimView',
    'BugSubscriberPackageBugsSearchListingView',
    'FOAFSearchView',
    'EmailToPersonView',
    'PersonActiveReviewsView',
    'PersonAddView',
    'PersonAnswerContactForView',
    'PersonAnswersMenu',
    'PersonApprovedMergesView',
    'PersonAssignedBugTaskSearchListingView',
    'PersonBranchesMenu',
    'PersonBranchesView',
    'PersonBrandingView',
    'PersonBreadcrumbBuilder',
    'PersonBugsMenu',
    'PersonChangePasswordView',
    'PersonClaimView',
    'PersonCodeOfConductEditView',
    'PersonCodeSummaryView',
    'PersonCommentedBugTaskSearchListingView',
    'PersonDeactivateAccountView',
    'PersonEditEmailsView',
    'PersonEditHomePageView',
    'PersonEditIRCNicknamesView',
    'PersonEditJabberIDsView',
    'PersonEditSSHKeysView',
    'PersonEditView',
    'PersonEditWikiNamesView',
    'PersonEditLocationView',
    'PersonFacets',
    'PersonGPGView',
    'PersonIndexView',
    'PersonLanguagesView',
    'PersonLatestQuestionsView',
    'PersonNavigation',
    'PersonOAuthTokensView',
    'PersonOverviewMenu',
    'PersonOwnedBranchesView',
    'PersonRdfView',
    'PersonRdfContentsView',
    'PersonRegisteredBranchesView',
    'PersonRelatedBugsView',
    'PersonRelatedSoftwareView',
    'PersonSearchQuestionsView',
    'PersonSetContextMenu',
    'PersonSetNavigation',
    'PersonSpecFeedbackView',
    'PersonSpecsMenu',
    'PersonSpecWorkloadView',
    'PersonSpecWorkloadTableView',
    'PersonSubscribedBranchesView',
    'PersonTeamBranchesView',
    'PersonTranslationView',
    'PersonTranslationRelicensingView',
    'PersonView',
    'PersonVouchersView',
    'RedirectToEditLanguagesView',
    'ReportedBugTaskSearchListingView',
    'RestrictedMembershipsPersonView',
    'SearchAnsweredQuestionsView',
    'SearchAssignedQuestionsView',
    'SearchCommentedQuestionsView',
    'SearchCreatedQuestionsView',
    'SearchNeedAttentionQuestionsView',
    'SearchSubscribedQuestionsView',
    'SubscribedBugTaskSearchListingView',
    'TeamAddMyTeamsView',
    'TeamEditLocationView',
    'TeamJoinView',
    'TeamBreadcrumbBuilder',
    'TeamLeaveView',
    'TeamNavigation',
    'TeamOverviewMenu',
    'TeamMembershipView',
    'TeamMugshotView',
    'TeamReassignmentView',
    'TeamSpecsMenu',
    'archive_to_person',
    ]

import copy
import pytz
import subprocess
import urllib

from datetime import datetime, timedelta
from itertools import chain
from operator import attrgetter, itemgetter
from textwrap import dedent

from zope.error.interfaces import IErrorReportingUtility
from zope.app.form.browser import TextAreaWidget, TextWidget
from zope.app.pagetemplate.viewpagetemplatefile import ViewPageTemplateFile
from zope.formlib.form import FormFields
from zope.interface import implements, Interface
from zope.component import getUtility
from zope.publisher.interfaces import NotFound
from zope.publisher.interfaces.browser import IBrowserPublisher
from zope.schema import Bool, Choice, List, Text, TextLine
from zope.schema.vocabulary import (
    SimpleTerm, SimpleVocabulary, getVocabularyRegistry)
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from lazr.delegates import delegates
from lazr.config import as_timedelta
from canonical.lazr.interface import copy_field, use_template
from canonical.lazr.utils import safe_hasattr
from canonical.database.sqlbase import flush_database_updates

from canonical.widgets import (
    LaunchpadDropdownWidget, LaunchpadRadioWidget,
    LaunchpadRadioWidgetWithDescription, LocationWidget, PasswordChangeWidget)
from canonical.widgets.popup import SinglePopupWidget
from canonical.widgets.image import ImageChangeWidget
from canonical.widgets.itemswidgets import LabeledMultiCheckBoxWidget

from canonical.cachedproperty import cachedproperty

from canonical.launchpad.components.openidserver import CurrentOpenIDEndPoint
from canonical.launchpad.interfaces import (
    AccountStatus, BranchListingSort, BranchPersonSearchContext,
    BranchPersonSearchRestriction, BugTaskSearchParams, BugTaskStatus,
    CannotUnsubscribe, DAYS_BEFORE_EXPIRATION_WARNING_IS_SENT,
    EmailAddressStatus, GPGKeyNotFoundError, IBranchSet, ICountry,
    IEmailAddress, IEmailAddressSet, IGPGHandler, IGPGKeySet, IIrcIDSet,
    IJabberIDSet, ILanguageSet, ILaunchBag, ILoginTokenSet, IMailingListSet,
    INewPerson, IOAuthConsumerSet, IOpenLaunchBag, IPOTemplateSet,
    IPasswordEncryptor, IPerson, IPersonChangePassword, IPersonClaim,
    IPersonSet, IPollSet, IPollSubset, IRequestPreferredLanguages, ISSHKeySet,
    ISignedCodeOfConductSet, ITeam, ITeamMembership, ITeamMembershipSet,
    ITeamReassignment, IWikiNameSet, LoginTokenType,
    MailingListAutoSubscribePolicy, NotFoundError, PersonCreationRationale,
    PersonVisibility, QuestionParticipation, SSHKeyType, SpecificationFilter,
    TeamMembershipRenewalPolicy, TeamMembershipStatus, TeamSubscriptionPolicy,
    UNRESOLVED_BUGTASK_STATUSES, UnexpectedFormData)
from canonical.launchpad.interfaces.branchnamespace import (
    get_branch_namespace, IBranchNamespaceSet)
from canonical.launchpad.interfaces.bugtask import IBugTaskSet
from canonical.launchpad.interfaces.build import (
    BuildStatus, IBuildSet)
from canonical.launchpad.interfaces.branchmergeproposal import (
    BranchMergeProposalStatus, IBranchMergeProposalGetter)
from canonical.launchpad.interfaces.launchpad import (
    INotificationRecipientSet, UnknownRecipientError)
from canonical.launchpad.interfaces.message import (
    IDirectEmailAuthorization, QuotaReachedError)
from canonical.launchpad.interfaces.product import IProduct
from canonical.launchpad.interfaces.openidserver import (
    IOpenIDPersistentIdentity, IOpenIDRPSummarySet)
from canonical.launchpad.interfaces.questioncollection import IQuestionSet
from canonical.launchpad.interfaces.salesforce import (
    ISalesforceVoucherProxy, SalesforceVoucherProxyException)
from canonical.launchpad.interfaces.sourcepackagerelease import (
    ISourcePackageRelease)
from canonical.launchpad.interfaces.translationrelicensingagreement import (
    ITranslationRelicensingAgreementEdit,
    TranslationRelicensingAgreementOptions)

from canonical.launchpad.browser.bugtask import (
    BugListingBatchNavigator, BugTaskSearchListingView)
from canonical.launchpad.browser.branchlisting import BranchListingView
from canonical.launchpad.browser.branchmergeproposallisting import (
    BranchMergeProposalListingView)
from canonical.launchpad.browser.feeds import FeedsMixin
from canonical.launchpad.browser.objectreassignment import (
    ObjectReassignmentView)
from canonical.launchpad.browser.openiddiscovery import (
    XRDSContentNegotiationMixin)
from canonical.launchpad.browser.specificationtarget import (
    HasSpecificationsView)
from canonical.launchpad.browser.branding import BrandingChangeView
from canonical.launchpad.browser.mailinglists import (
    enabled_with_active_mailing_list)
from canonical.launchpad.browser.questiontarget import SearchQuestionsView

from canonical.launchpad.fields import LocationField

from canonical.launchpad.mailnotification import send_direct_contact_email
from canonical.launchpad.validators.email import valid_email

from canonical.launchpad.webapp import (
    ApplicationMenu, ContextMenu, LaunchpadEditFormView, LaunchpadFormView,
    Link, Navigation, StandardLaunchpadFacets, action, canonical_url,
    custom_widget, enabled_with_permission, stepthrough, stepto)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.breadcrumb import BreadcrumbBuilder
from canonical.launchpad.webapp.interfaces import IPlacelessLoginSource
from canonical.launchpad.webapp.login import (
    logoutPerson, allowUnauthenticatedSession)
from canonical.launchpad.webapp.menu import structured, NavigationMenu
from canonical.launchpad.webapp.publisher import LaunchpadView
from canonical.launchpad.webapp.tales import DateTimeFormatterAPI
from canonical.launchpad.webapp.uri import URI, InvalidURIError

from canonical.launchpad import _

from canonical.lazr.utils import smartquote


class RestrictedMembershipsPersonView(LaunchpadView):
    """Secure access to team membership information for a person.

    This class checks that the logged-in user has access to view
    all the teams that these attributes and functions return.
    """

    def getLatestApprovedMembershipsForPerson(self):
        """Returns a list of teams the person has recently joined.

        Private teams are filtered out if the user is not a member of them.
        """
        # This method returns a list as opposed to the database object's
        # getLatestApprovedMembershipsForPerson which returns a sqlobject
        # result set.
        membership_list = self.context.getLatestApprovedMembershipsForPerson()
        return [membership for membership in membership_list
                if check_permission('launchpad.View', membership.team)]

    @property
    def teams_with_icons(self):
        """Returns list of teams with custom icons.

        These are teams that the person is an active member of.
        Private teams are filtered out if the user is not a member of them.
        """
        # This method returns a list as opposed to the database object's
        # teams_with_icons which returns a sqlobject
        # result set.
        return [team for team in self.context.teams_with_icons
                if check_permission('launchpad.View', team)]

    @property
    def administrated_teams(self):
        """Return the list of teams administrated by the person.

        The user must be an administrator of the team, and the team must
        be public.
        """
        return [team for team in self.context.getAdministratedTeams()
                if team.visibility == PersonVisibility.PUBLIC]

    def userCanViewMembership(self):
        """Return true if the user can view a team's membership.

        Only launchpad admins and team members can view the private
        membership. Anyone can view a public team's membership.
        """
        return check_permission('launchpad.View', self.context)


class BranchTraversalMixin:
    """Branch of this person or team for the specified product and
    branch names.

    For example:

    * '/~ddaa/bazaar/devel' points to the branch whose owner
    name is 'ddaa', whose product name is 'bazaar', and whose branch name
    is 'devel'.

    * '/~sabdfl/+junk/junkcode' points to the branch whose
    owner name is 'sabdfl', with no associated product, and whose branch
    name is 'junkcode'.

    * '/~ddaa/+branch/bazaar/devel' redirects to '/~ddaa/bazaar/devel'

    """

    def _getBranch(self, product_name, branch_name):
        return getUtility(IBranchNamespaceSet).interpret(
            self.context.name, product_name).getByName(branch_name)

    @stepto('+branch')
    def redirect_branch(self):
        """Redirect to canonical_url, which is ~user/product/name."""
        stepstogo = self.request.stepstogo
        product_name = stepstogo.consume()
        branch_name = stepstogo.consume()
        branch = self._getBranch(product_name, branch_name)
        if branch:
            return self.redirectSubTree(canonical_url(branch))
        raise NotFoundError

    @stepthrough('+junk')
    def traverse_junk(self, name):
        return get_branch_namespace(self.context).getByName(name)

    def traverse(self, product_name):
        # XXX: JonathanLange 2008-12-10 spec=package-branches: This is a big
        # thing that needs to be changed for package branches.
        branch_name = self.request.stepstogo.consume()
        if branch_name is not None:
            branch = self._getBranch(product_name, branch_name)
            if branch is not None and branch.product is not None:
                # The launch bag contains "stuff of interest" related to where
                # the user is traversing to.  When a user traverses over a
                # product, the product gets added to the launch bag by the
                # traversal machinery, however when traversing to a branch, we
                # short circuit it somewhat by looking for a two part key (in
                # addition to the user) to identify the branch, and as such
                # the product isnt't being added to the bag by the internals.
                getUtility(IOpenLaunchBag).add(branch.product)

                if branch.product.name != product_name:
                    # This branch was accessed through one of its product's
                    # aliases, so we must redirect to its canonical URL.
                    return self.redirectSubTree(canonical_url(branch))
            return branch
        else:
            return super(BranchTraversalMixin, self).traverse(product_name)


class PersonNavigation(BranchTraversalMixin, Navigation):

    usedfor = IPerson

    @stepthrough('+expiringmembership')
    def traverse_expiring_membership(self, name):
        # Return the found membership regardless of its status as we know
        # TeamMembershipSelfRenewalView will tell users why the memembership
        # can't be renewed when necessary.
        membership = getUtility(ITeamMembershipSet).getByPersonAndTeam(
            self.context, getUtility(IPersonSet).getByName(name))
        if membership is None:
            return None
        return TeamMembershipSelfRenewalView(membership, self.request)

    @stepto('+archive')
    def traverse_archive(self):
        return self.context.archive

    @stepthrough('+email')
    def traverse_email(self, email):
        """Traverse to this person's emails on the webservice layer."""
        email = getUtility(IEmailAddressSet).getByEmail(email)
        if email is None or email.person != self.context:
            return None
        return email

    @stepthrough('+wikiname')
    def traverse_wikiname(self, id):
        """Traverse to this person's WikiNames on the webservice layer."""
        wiki = getUtility(IWikiNameSet).get(id)
        if wiki is None or wiki.person != self.context:
            return None
        return wiki

    @stepthrough('+jabberid')
    def traverse_jabberid(self, jabber_id):
        """Traverse to this person's JabberIDs on the webservice layer."""
        jabber = getUtility(IJabberIDSet).getByJabberID(jabber_id)
        if jabber is None or jabber.person != self.context:
            return None
        return jabber

    @stepthrough('+ircnick')
    def traverse_ircnick(self, id):
        """Traverse to this person's IrcIDs on the webservice layer."""
        irc_nick = getUtility(IIrcIDSet).get(id)
        if irc_nick is None or irc_nick.person != self.context:
            return None
        return irc_nick


class TeamNavigation(PersonNavigation):

    usedfor = ITeam

    @stepthrough('+poll')
    def traverse_poll(self, name):
        return getUtility(IPollSet).getByTeamAndName(self.context, name)

    @stepthrough('+invitation')
    def traverse_invitation(self, name):
        # Return the found membership regardless of its status as we know
        # TeamInvitationView can handle memberships in statuses other than
        # INVITED.
        membership = getUtility(ITeamMembershipSet).getByPersonAndTeam(
            self.context, getUtility(IPersonSet).getByName(name))
        if membership is None:
            return None
        return TeamInvitationView(membership, self.request)

    @stepthrough('+member')
    def traverse_member(self, name):
        person = getUtility(IPersonSet).getByName(name)
        if person is None:
            return None
        return getUtility(ITeamMembershipSet).getByPersonAndTeam(
            person, self.context)


class TeamBreadcrumbBuilder(BreadcrumbBuilder):
    """Builds a breadcrumb for an `ITeam`."""
    @property
    def text(self):
        return smartquote('"%s" team') % self.context.displayname


class TeamMembershipSelfRenewalView(LaunchpadFormView):

    implements(IBrowserPublisher)

    schema = ITeamMembership
    field_names = []
    label = 'Renew team membership'
    template = ViewPageTemplateFile(
        '../templates/teammembership-self-renewal.pt')

    def __init__(self, context, request):
        # Only the member himself or admins of the member (in case it's a
        # team) can see the page in which they renew memberships that are
        # about to expire.
        if not check_permission('launchpad.Edit', context.person):
            raise Unauthorized(
                "Only the member himself can renew his memberships.")
        LaunchpadFormView.__init__(self, context, request)

    def browserDefault(self, request):
        return self, ()

    def getReasonForDeniedRenewal(self):
        """Return text describing why the membership can't be renewed."""
        context = self.context
        ondemand = TeamMembershipRenewalPolicy.ONDEMAND
        admin = TeamMembershipStatus.ADMIN
        approved = TeamMembershipStatus.APPROVED
        date_limit = datetime.now(pytz.timezone('UTC')) - timedelta(
            days=DAYS_BEFORE_EXPIRATION_WARNING_IS_SENT)
        if context.status not in (admin, approved):
            text = "it is not active."
        elif context.team.renewal_policy != ondemand:
            text = ('<a href="%s">%s</a> is not a team which accepts its '
                    'members to renew their own memberships.'
                    % (canonical_url(context.team),
                       context.team.unique_displayname))
        elif context.dateexpires is None or context.dateexpires > date_limit:
            if context.person.isTeam():
                link_text = "Somebody else has already renewed it."
            else:
                link_text = (
                    "You or one of the team administrators has already "
                    "renewed it.")
            text = ('it is not set to expire in %d days or less. '
                    '<a href="%s/+members">%s</a>'
                    % (DAYS_BEFORE_EXPIRATION_WARNING_IS_SENT,
                       canonical_url(context.team), link_text))
        else:
            raise AssertionError('This membership can be renewed!')
        return text

    @property
    def time_before_expiration(self):
        return self.context.dateexpires - datetime.now(pytz.timezone('UTC'))

    @property
    def next_url(self):
        return canonical_url(self.context.person)

    @action(_("Renew"), name="renew")
    def renew_action(self, action, data):
        member = self.context.person
        member.renewTeamMembership(self.context.team)
        self.request.response.addInfoNotification(
            _("Membership renewed until ${date}.", mapping=dict(
                    date=self.context.dateexpires.strftime('%Y-%m-%d'))))

    @action(_("Let it Expire"), name="nothing")
    def do_nothing_action(self, action, data):
        # Redirect back and wait for the membership to expire automatically.
        pass


class ITeamMembershipInvitationAcknowledgementForm(Interface):
    """Schema for the form in which team admins acknowledge invitations.

    We could use ITeamMembership for that, but the acknowledger_comment is
    marked readonly there and that means LaunchpadFormView won't include the
    value of that in the data given to our action handler.
    """

    acknowledger_comment = Text(
        title=_("Comment"), required=False, readonly=False)


class TeamInvitationView(LaunchpadFormView):
    """Where team admins can accept/decline membership invitations."""

    implements(IBrowserPublisher)

    schema = ITeamMembershipInvitationAcknowledgementForm
    label = 'Team membership invitation'
    field_names = ['acknowledger_comment']
    custom_widget('acknowledger_comment', TextAreaWidget, height=5, width=60)
    template = ViewPageTemplateFile(
        '../templates/teammembership-invitation.pt')

    def __init__(self, context, request):
        # Only admins of the invited team can see the page in which they
        # approve/decline invitations.
        if not check_permission('launchpad.Edit', context.person):
            raise Unauthorized(
                "Only team administrators can approve/decline invitations "
                "sent to this team.")
        LaunchpadFormView.__init__(self, context, request)

    def browserDefault(self, request):
        return self, ()

    @property
    def next_url(self):
        return canonical_url(self.context.person)

    @action(_("Accept"), name="accept")
    def accept_action(self, action, data):
        if self.context.status != TeamMembershipStatus.INVITED:
            self.request.response.addInfoNotification(
                _("This invitation has already been processed."))
            return
        member = self.context.person
        member.acceptInvitationToBeMemberOf(
            self.context.team, data['acknowledger_comment'])
        self.request.response.addInfoNotification(
            _("This team is now a member of ${team}", mapping=dict(
                  team=self.context.team.browsername)))

    @action(_("Decline"), name="decline")
    def decline_action(self, action, data):
        if self.context.status != TeamMembershipStatus.INVITED:
            self.request.response.addInfoNotification(
                _("This invitation has already been processed."))
            return
        member = self.context.person
        member.declineInvitationToBeMemberOf(
            self.context.team, data['acknowledger_comment'])
        self.request.response.addInfoNotification(
            _("Declined the invitation to join ${team}", mapping=dict(
                  team=self.context.team.browsername)))

    @action(_("Cancel"), name="cancel")
    def cancel_action(self, action, data):
        # Simply redirect back.
        pass


class PersonSetNavigation(Navigation):

    usedfor = IPersonSet

    def traverse(self, name):
        # Raise a 404 on an invalid Person name
        person = self.context.getByName(name)
        if person is None:
            raise NotFoundError(name)
        # Redirect to /~name
        return self.redirectSubTree(canonical_url(person))

    @stepto('+me')
    def me(self):
        me = getUtility(ILaunchBag).user
        if me is None:
            raise Unauthorized("You need to be logged in to view this URL.")
        return self.redirectSubTree(canonical_url(me), status=303)


class PersonSetContextMenu(ContextMenu):

    usedfor = IPersonSet

    links = ['products', 'distributions', 'people', 'meetings', 'newteam',
             'adminpeoplemerge', 'adminteammerge', 'mergeaccounts']

    def products(self):
        return Link('/projects/', 'View projects')

    def distributions(self):
        return Link('/distros/', 'View distributions')

    def people(self):
        return Link('/people/', 'View people')

    def meetings(self):
        return Link('/sprints/', 'View meetings')

    def newteam(self):
        text = 'Register a team'
        return Link('+newteam', text, icon='add')

    def mergeaccounts(self):
        text = 'Merge accounts'
        return Link('+requestmerge', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def adminpeoplemerge(self):
        text = 'Admin merge people'
        return Link('+adminpeoplemerge', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def adminteammerge(self):
        text = 'Admin merge teams'
        return Link('+adminteammerge', text, icon='edit')


class PersonBreadcrumbBuilder(BreadcrumbBuilder):
    """Builds a breadcrumb for an `IPerson`."""
    @property
    def text(self):
        return self.context.displayname


class PersonFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IPerson."""

    usedfor = IPerson

    enable_only = ['overview', 'bugs', 'answers', 'specifications',
                   'branches', 'translations']

    def overview(self):
        text = 'Overview'
        summary = 'General information about %s' % self.context.browsername
        return Link('', text, summary)

    def bugs(self):
        text = 'Bugs'
        summary = (
            'Bug reports that %s is involved with' % self.context.browsername)
        return Link('', text, summary)

    def specifications(self):
        text = 'Blueprints'
        summary = (
            'Feature specifications that %s is involved with' %
            self.context.browsername)
        return Link('', text, summary)

    def bounties(self):
        text = 'Bounties'
        browsername = self.context.browsername
        summary = (
            'Bounty offers that %s is involved with' % browsername)
        return Link('+bounties', text, summary)

    def branches(self):
        text = 'Code'
        summary = ('Bazaar Branches and revisions registered and authored '
                   'by %s' % self.context.browsername)
        return Link('', text, summary)

    def answers(self):
        text = 'Answers'
        summary = (
            'Questions that %s is involved with' % self.context.browsername)
        return Link('', text, summary)

    def translations(self):
        text = 'Translations'
        summary = (
            'Software that %s is involved in translating' %
            self.context.browsername)
        return Link('', text, summary)


class PersonBranchCountMixin:
    """A mixin class for person branch listings."""

    @cachedproperty
    def total_branch_count(self):
        """Return the number of branches related to the person."""
        query = getUtility(IBranchSet).getBranchesForContext(
            self.context, visible_by_user=self.user)
        return query.count()

    @cachedproperty
    def registered_branch_count(self):
        """Return the number of branches registered by the person."""
        query = getUtility(IBranchSet).getBranchesForContext(
            BranchPersonSearchContext(
                self.context, BranchPersonSearchRestriction.REGISTERED),
            visible_by_user=self.user)
        return query.count()

    @cachedproperty
    def owned_branch_count(self):
        """Return the number of branches owned by the person."""
        query = getUtility(IBranchSet).getBranchesForContext(
            BranchPersonSearchContext(
                self.context, BranchPersonSearchRestriction.OWNED),
            visible_by_user=self.user)
        return query.count()

    @cachedproperty
    def subscribed_branch_count(self):
        """Return the number of branches subscribed to by the person."""
        query = getUtility(IBranchSet).getBranchesForContext(
            BranchPersonSearchContext(
                self.context, BranchPersonSearchRestriction.SUBSCRIBED),
            visible_by_user=self.user)
        return query.count()

    @property
    def user_in_context_team(self):
        if self.user is None:
            return False
        return self.user.inTeam(self.context)

    @cachedproperty
    def active_review_count(self):
        """Return the number of active reviews for the user."""
        query = getUtility(IBranchMergeProposalGetter).getProposalsForContext(
            self.context, [BranchMergeProposalStatus.NEEDS_REVIEW], self.user)
        return query.count()

    @cachedproperty
    def approved_merge_count(self):
        """Return the number of active reviews for the user."""
        query = getUtility(IBranchMergeProposalGetter).getProposalsForContext(
            self.context, [BranchMergeProposalStatus.CODE_APPROVED],
            self.user)
        return query.count()


class PersonBranchesMenu(ApplicationMenu, PersonBranchCountMixin):

    usedfor = IPerson
    facet = 'branches'
    links = ['all_related', 'registered', 'owned', 'subscribed', 'addbranch',
             'active_reviews', 'approved_merges']

    def all_related(self):
        return Link(canonical_url(self.context, rootsite='code'),
                    'Related branches')

    def owned(self):
        return Link('+ownedbranches', 'owned')

    def registered(self):
        return Link('+registeredbranches', 'registered')

    def subscribed(self):
        return Link('+subscribedbranches', 'subscribed')

    def active_reviews(self):
        if self.active_review_count == 1:
            text = 'active review'
        else:
            text = 'active reviews'
        return Link('+activereviews', text)

    def approved_merges(self):
        if self.approved_merge_count == 1:
            text = 'approved merge'
        else:
            text = 'approved merges'
        return Link('+approvedmerges', text)

    def addbranch(self):
        if self.user is None:
            enabled = False
        else:
            enabled = self.user.inTeam(self.context)
        text = 'Register branch'
        return Link('+addbranch', text, icon='add', enabled=enabled)


class PersonBugsMenu(ApplicationMenu):

    usedfor = IPerson
    facet = 'bugs'
    links = ['assignedbugs', 'commentedbugs', 'reportedbugs',
             'subscribedbugs', 'relatedbugs', 'softwarebugs', 'mentoring']

    def relatedbugs(self):
        text = 'List all related bugs'
        summary = ('Lists all bug reports which %s reported, is assigned to, '
                   'or is subscribed to.' % self.context.displayname)
        return Link('', text, summary=summary)

    def assignedbugs(self):
        text = 'List assigned bugs'
        summary = 'Lists bugs assigned to %s.' % self.context.displayname
        return Link('+assignedbugs', text, summary=summary)

    def softwarebugs(self):
        text = 'Show package report'
        summary = (
            'A summary report for packages where %s is a bug supervisor.'
            % self.context.displayname)
        return Link('+packagebugs', text, summary=summary)

    def reportedbugs(self):
        text = 'List reported bugs'
        summary = 'Lists bugs reported by %s.' % self.context.displayname
        return Link('+reportedbugs', text, summary=summary)

    def subscribedbugs(self):
        text = 'List subscribed bugs'
        summary = ('Lists bug reports %s is subscribed to.'
                   % self.context.displayname)
        return Link('+subscribedbugs', text, summary=summary)

    def mentoring(self):
        text = 'Mentoring offered'
        summary = ('Lists bugs for which %s has offered to mentor someone.'
                   % self.context.displayname)
        enabled = bool(self.context.mentoring_offers)
        return Link('+mentoring', text, enabled=enabled, summary=summary)

    def commentedbugs(self):
        text = 'List commented bugs'
        summary = ('Lists bug reports on which %s has commented.'
                   % self.context.displayname)
        return Link('+commentedbugs', text, summary=summary)


class PersonSpecsMenu(ApplicationMenu):

    usedfor = IPerson
    facet = 'specifications'
    links = ['assignee', 'drafter', 'approver',
             'subscriber', 'registrant', 'feedback',
             'workload', 'mentoring']

    def registrant(self):
        text = 'Registrant'
        summary = 'List specs registered by %s' % self.context.browsername
        return Link('+specs?role=registrant', text, summary, icon='spec')

    def approver(self):
        text = 'Approver'
        summary = 'List specs with %s is supposed to approve' % (
            self.context.browsername)
        return Link('+specs?role=approver', text, summary, icon='spec')

    def assignee(self):
        text = 'Assignee'
        summary = 'List specs for which %s is the assignee' % (
            self.context.browsername)
        return Link('+specs?role=assignee', text, summary, icon='spec')

    def drafter(self):
        text = 'Drafter'
        summary = 'List specs drafted by %s' % self.context.browsername
        return Link('+specs?role=drafter', text, summary, icon='spec')

    def subscriber(self):
        text = 'Subscriber'
        return Link('+specs?role=subscriber', text, icon='spec')

    def feedback(self):
        text = 'Feedback requests'
        summary = 'List specs where feedback has been requested from %s' % (
            self.context.browsername)
        return Link('+specfeedback', text, summary, icon='info')

    def mentoring(self):
        text = 'Mentoring offered'
        enabled = bool(self.context.mentoring_offers)
        return Link('+mentoring', text, enabled=enabled, icon='info')

    def workload(self):
        text = 'Workload'
        summary = 'Show all specification work assigned'
        return Link('+specworkload', text, summary, icon='info')


class PersonTranslationsMenu(ApplicationMenu):

    usedfor = IPerson
    facet = 'translations'
    links = ['imports', 'relicensing']

    def imports(self):
        text = 'See import queue'
        return Link('+imports', text)

    def relicensing(self):
        text = 'Translations licensing'
        enabled = (self.context == self.user)
        return Link('+licensing', text, enabled=enabled)


class TeamSpecsMenu(PersonSpecsMenu):

    usedfor = ITeam
    facet = 'specifications'

    def mentoring(self):
        target = '+mentoring'
        text = 'Mentoring offered'
        summary = 'Offers of mentorship for prospective team members'
        return Link(target, text, summary=summary, icon='info')


class TeamBugsMenu(PersonBugsMenu):

    usedfor = ITeam
    facet = 'bugs'
    links = ['assignedbugs', 'relatedbugs', 'softwarebugs', 'subscribedbugs',
             'mentorships']

    def mentorships(self):
        target = '+mentoring'
        text = 'Mentoring offered'
        summary = 'Offers of mentorship for prospective team members'
        return Link(target, text, summary=summary, icon='info')


class CommonMenuLinks:

    @enabled_with_permission('launchpad.Edit')
    def common_edithomepage(self):
        target = '+edithomepage'
        text = 'Change home page'
        return Link(target, text, icon='edit')

    def common_packages(self):
        target = '+related-software'
        text = 'List assigned packages'
        summary = 'Packages assigned to %s' % self.context.browsername
        return Link(target, text, summary, icon='packages')

    def related_projects(self):
        target = '+related-software#projects'
        text = 'List related projects'
        summary = 'Projects %s is involved with' % self.context.browsername
        return Link(target, text, summary, icon='packages')

    @enabled_with_permission('launchpad.Edit')
    def activate_ppa(self):
        target = "+activate-ppa"
        text = 'Activate Personal Package Archive'
        summary = ('Acknowledge terms of service for Launchpad Personal '
                   'Package Archive.')
        enabled = not bool(self.context.archive)
        return Link(target, text, summary, icon='edit', enabled=enabled)

    def show_ppa(self):
        target = '+archive'
        text = 'Personal Package Archive'
        summary = 'Browse Personal Package Archive packages.'
        archive = self.context.archive
        enable_link = (archive is not None and
                       check_permission('launchpad.View', archive))
        return Link(target, text, summary, icon='info', enabled=enable_link)


class PersonOverviewMenu(ApplicationMenu, CommonMenuLinks):

    usedfor = IPerson
    facet = 'overview'
    links = ['edit', 'branding', 'common_edithomepage',
             'editemailaddresses', 'editlanguages', 'editwikinames',
             'editircnicknames', 'editjabberids', 'editpassword',
             'editsshkeys', 'editpgpkeys', 'editlocation', 'memberships',
             'mentoringoffers', 'codesofconduct', 'karma', 'common_packages',
             'administer', 'related_projects', 'activate_ppa', 'show_ppa']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        target = '+edit'
        text = 'Change details'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def branding(self):
        target = '+branding'
        text = 'Change branding'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editlanguages(self):
        target = '+editlanguages'
        text = 'Set preferred languages'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editemailaddresses(self):
        target = '+editemails'
        text = 'Change e-mail settings'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editwikinames(self):
        target = '+editwikinames'
        text = 'Update wiki names'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editircnicknames(self):
        target = '+editircnicknames'
        text = 'Update IRC nicknames'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editjabberids(self):
        target = '+editjabberids'
        text = 'Update Jabber IDs'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editpassword(self):
        target = '+changepassword'
        text = 'Change your password'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.EditLocation')
    def editlocation(self):
        target = '+editlocation'
        text = 'Set location and time zone'
        return Link(target, text, icon='edit')

    def karma(self):
        target = '+karma'
        text = 'Show karma summary'
        summary = (
            u'%s\N{right single quotation mark}s activities '
            u'in Launchpad' % self.context.browsername)
        return Link(target, text, summary, icon='info')

    def memberships(self):
        target = '+participation'
        text = 'Show team participation'
        return Link(target, text, icon='info')

    def mentoringoffers(self):
        target = '+mentoring'
        text = 'Mentoring offered'
        enabled = bool(self.context.mentoring_offers)
        return Link(target, text, enabled=enabled, icon='info')

    @enabled_with_permission('launchpad.Special')
    def editsshkeys(self):
        target = '+editsshkeys'
        text = 'Update SSH keys'
        summary = (
            'Used if %s stores code on the Supermirror' %
            self.context.browsername)
        return Link(target, text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editpgpkeys(self):
        target = '+editpgpkeys'
        text = 'Update OpenPGP keys'
        summary = 'Used for the Supermirror, and when maintaining packages'
        return Link(target, text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def codesofconduct(self):
        target = '+codesofconduct'
        text = 'Codes of Conduct'
        summary = (
            'Agreements to abide by the rules of a distribution or project')
        return Link(target, text, summary, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        target = '+review'
        text = 'Administer'
        return Link(target, text, icon='edit')


class IPersonEditMenu(Interface):
    """A marker interface for the 'Edit Profile' navigation menu."""


class IPersonRelatedSoftwareMenu(Interface):
    """A marker interface for the 'Related Software' navigation menu."""

class PersonPPANavigationMenuMixin:
    """A mixin that provides the PPA navigation menu link."""

    def show_ppa(self):
        """Show the link to a Personal Package Archive.

        The person's archive link changes depending on the status of the
        archive and the privileges of the viewer.
        """
        archive = self.context.archive
        has_archive = archive is not None
        user_can_edit_archive = check_permission('launchpad.Edit',
                                                 self.context)

        text = 'Personal Package Archive'
        summary = 'Browse Personal Package Archive packages.'
        if has_archive:
            target = '+archive'
            enable_link = check_permission('launchpad.View', archive)
        elif user_can_edit_archive:
            summary = 'Activate Personal Package Archive'
            target = '+activate-ppa'
            enable_link = True
        else:
            target = '+archive'
            enable_link = False

        return Link(target, text, summary, icon='info', enabled=enable_link)


class PersonOverviewNavigationMenu(
    NavigationMenu, PersonPPANavigationMenuMixin):
    """The top-level menu of actions a Person may take."""

    usedfor = IPerson
    facet = 'overview'
    links = ('profile', 'related_software', 'karma', 'show_ppa')

    def __init__(self, context):
        context = IPerson(context)
        super(PersonOverviewNavigationMenu, self).__init__(context)

    def profile(self):
        target = ''
        text = 'Profile'
        return Link(target, text, menu=IPersonEditMenu)

    def related_software(self):
        target = '+related-software'
        text = 'Related Software'
        return Link(target, text, menu=IPersonRelatedSoftwareMenu)

    def karma(self):
        target = '+karma'
        text = 'Karma'
        return Link(target, text)


class PersonRelatedSoftwareNavigationMenu(NavigationMenu):

    usedfor = IPersonRelatedSoftwareMenu
    facet = 'overview'
    links = ('summary', 'maintained', 'uploaded', 'ppa', 'projects')

    def summary(self):
        target = '+related-software'
        text = 'Summary'
        return Link(target, text)

    def maintained(self):
        target = '+maintained-packages'
        text = 'Maintained Packages'
        return Link(target, text)

    def uploaded(self):
        target = '+uploaded-packages'
        text = 'Uploaded Packages'
        return Link(target, text)

    def ppa(self):
        target = '+ppa-packages'
        text = 'PPA Packages'
        return Link(target, text)

    def projects(self):
        target = '+related-projects'
        text = 'Related Projects'
        return Link(target, text)


class PersonEditNavigationMenu(NavigationMenu):
    """A sub-menu for different aspects of editing a Person's profile."""

    usedfor = IPersonEditMenu
    facet = 'overview'
    links = ('personal', 'email_settings',
             'sshkeys', 'gpgkeys', 'passwords')

    def personal(self):
        target = '+edit'
        text = 'Personal'
        return Link(target, text)

    def email_settings(self):
        target = '+editemails'
        text = 'E-mail Settings'
        return Link(target, text)

    @enabled_with_permission('launchpad.Special')
    def sshkeys(self):
        target = '+editsshkeys'
        text = 'SSH Keys'
        return Link(target, text)

    def gpgkeys(self):
        target = '+editpgpkeys'
        text = 'OpenPGP Keys'
        return Link(target, text)

    def passwords(self):
        target = '+changepassword'
        text = 'Passwords'
        return Link(target, text)


class TeamOverviewMenu(ApplicationMenu, CommonMenuLinks):

    usedfor = ITeam
    facet = 'overview'
    links = ['edit', 'branding', 'common_edithomepage', 'members',
             'add_member', 'memberships', 'received_invitations', 'mugshots',
             'editemail', 'configure_mailing_list', 'moderate_mailing_list',
             'editlanguages', 'map', 'polls',
             'add_poll', 'joinleave', 'add_my_teams', 'mentorships',
             'reassign', 'common_packages', 'related_projects',
             'activate_ppa', 'show_ppa']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        target = '+edit'
        text = 'Change details'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def branding(self):
        target = '+branding'
        text = 'Change branding'
        return Link(target, text, icon='edit')

    @enabled_with_permission('launchpad.Owner')
    def reassign(self):
        target = '+reassign'
        text = 'Change owner'
        summary = 'Change the owner of the team'
        # alt="(Change owner)"
        return Link(target, text, summary, icon='edit')

    @enabled_with_permission('launchpad.View')
    def members(self):
        target = '+members'
        text = 'Show all members'
        return Link(target, text, icon='people')

    @enabled_with_permission('launchpad.Edit')
    def received_invitations(self):
        target = '+invitations'
        text = 'Show received invitations'
        return Link(target, text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def add_member(self):
        target = '+addmember'
        text = 'Add member'
        return Link(target, text, icon='add')

    def map(self):
        target = '+map'
        text = 'Show map and time zones'
        return Link(target, text)

    def add_my_teams(self):
        target = '+add-my-teams'
        text = 'Add one of my teams'
        return Link(target, text, icon='add')

    def memberships(self):
        target = '+participation'
        text = 'Show team participation'
        return Link(target, text, icon='info')

    def mentorships(self):
        target = '+mentoring'
        text = 'Mentoring available'
        enabled = bool(self.context.team_mentorships)
        summary = 'Offers of mentorship for prospective team members'
        return Link(target, text, summary=summary, enabled=enabled,
                    icon='info')

    @enabled_with_permission('launchpad.View')
    def mugshots(self):
        target = '+mugshots'
        text = 'Show group photo'
        return Link(target, text, icon='people')

    def polls(self):
        target = '+polls'
        text = 'Show polls'
        return Link(target, text, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def add_poll(self):
        target = '+newpoll'
        text = 'Create a poll'
        return Link(target, text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def editemail(self):
        target = '+contactaddress'
        text = 'Change contact address'
        summary = (
            'The address Launchpad uses to contact %s' %
            self.context.browsername)
        return Link(target, text, summary, icon='mail')

    @enabled_with_permission('launchpad.MailingListManager')
    def configure_mailing_list(self):
        target = '+mailinglist'
        text = 'Configure mailing list'
        summary = (
            'The mailing list associated with %s' % self.context.browsername)
        return Link(target, text, summary, icon='edit')

    @enabled_with_active_mailing_list
    @enabled_with_permission('launchpad.Edit')
    def moderate_mailing_list(self):
        target = '+mailinglist-moderate'
        text = 'Moderate mailing list'
        summary = (
            'The mailing list associated with %s' % self.context.browsername)
        return Link(target, text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def editlanguages(self):
        target = '+editlanguages'
        text = 'Set preferred languages'
        return Link(target, text, icon='edit')

    def joinleave(self):
        team = self.context
        enabled = True
        if userIsActiveTeamMember(team):
            target = '+leave'
            text = 'Leave the Team' # &#8230;
            icon = 'remove'
        else:
            if team.subscriptionpolicy == TeamSubscriptionPolicy.RESTRICTED:
                # This is a restricted team; users can't join.
                enabled = False
            target = '+join'
            text = 'Join the team' # &#8230;
            icon = 'add'
        return Link(target, text, icon=icon, enabled=enabled)


class TeamOverviewNavigationMenu(
    NavigationMenu, PersonPPANavigationMenuMixin):
    """A top-level menu for navigation within a Team."""

    usedfor = ITeam
    facet = 'overview'
    links = ['profile', 'polls', 'members', 'show_ppa']

    def profile(self):
        target = ''
        text = 'Overview'
        return Link(target, text)

    def polls(self):
        target = '+polls'
        text = 'Polls'
        return Link(target, text)

    @enabled_with_permission('launchpad.View')
    def members(self):
        target = '+members'
        text = 'Members'
        return Link(target, text)


class ActiveBatchNavigator(BatchNavigator):
    """A paginator for active items.

    Used when a view needs to display more than one BatchNavigator of items.
    """
    start_variable_name = 'active_start'
    batch_variable_name = 'active_batch'


class InactiveBatchNavigator(BatchNavigator):
    """A paginator for inactive items.

    Used when a view needs to display more than one BatchNavigator of items.
    """
    start_variable_name = 'inactive_start'
    batch_variable_name = 'inactive_batch'


class TeamMembershipView(LaunchpadView):
    """The view behins ITeam/+members."""

    @cachedproperty
    def active_memberships(self):
        """Current members of the team."""
        return ActiveBatchNavigator(
            self.context.member_memberships, self.request)

    @cachedproperty
    def inactive_memberships(self):
        """Former members of the team."""
        return InactiveBatchNavigator(
            self.context.getInactiveMemberships(), self.request)

    @cachedproperty
    def invited_memberships(self):
        """Other teams invited to become members of this team."""
        return list(self.context.getInvitedMemberships())

    @cachedproperty
    def proposed_memberships(self):
        """Users who have requested to join this team."""
        return list(self.context.getProposedMemberships())

    @property
    def have_pending_members(self):
        return self.proposed_memberships or self.invited_memberships


class FOAFSearchView:

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.results = []

    def teamsCount(self):
        return getUtility(IPersonSet).teamsCount()

    def peopleCount(self):
        return getUtility(IPersonSet).peopleCount()

    def searchPeopleBatchNavigator(self):
        name = self.request.get("name")

        if not name:
            return None

        searchfor = self.request.get("searchfor")
        if searchfor == "peopleonly":
            results = getUtility(IPersonSet).findPerson(name)
        elif searchfor == "teamsonly":
            results = getUtility(IPersonSet).findTeam(name)
        else:
            results = getUtility(IPersonSet).find(name)

        return BatchNavigator(results, self.request)


class PersonAddView(LaunchpadFormView):
    """The page where users can create new Launchpad profiles."""

    label = "Create a new Launchpad profile"
    schema = INewPerson
    custom_widget('creation_comment', TextAreaWidget, height=5, width=60)

    @action(_("Create Profile"), name="create")
    def create_action(self, action, data):
        emailaddress = data['emailaddress']
        displayname = data['displayname']
        creation_comment = data['creation_comment']
        person, ignored = getUtility(IPersonSet).createPersonAndEmail(
            emailaddress, PersonCreationRationale.USER_CREATED,
            displayname=displayname, comment=creation_comment,
            registrant=self.user)
        self.next_url = canonical_url(person)
        logintokenset = getUtility(ILoginTokenSet)
        token = logintokenset.new(
            requester=self.user,
            requesteremail=self.user.preferredemail.email,
            email=emailaddress, tokentype=LoginTokenType.NEWPROFILE)
        token.sendProfileCreatedEmail(person, creation_comment)


class DeactivateAccountSchema(Interface):
    use_template(IPerson, include=['password'])
    comment = copy_field(
        IPerson['account_status_comment'], readonly=False, __name__='comment')


class PersonDeactivateAccountView(LaunchpadFormView):

    schema = DeactivateAccountSchema
    label = "Deactivate your Launchpad account"
    custom_widget('comment', TextAreaWidget, height=5, width=60)

    def validate(self, data):
        loginsource = getUtility(IPlacelessLoginSource)
        principal = loginsource.getPrincipalByLogin(
            self.user.preferredemail.email)
        assert principal is not None, "User must be logged in at this point."
        # The widget will transform '' into a special marker value.
        password = data.get('password')
        if password is self.schema['password'].UNCHANGED_PASSWORD:
            password = u''
        if not principal.validate(password):
            self.setFieldError('password', 'Incorrect password.')
            return

    @action(_("Deactivate My Account"), name="deactivate")
    def deactivate_action(self, action, data):
        self.context.deactivateAccount(data['comment'])
        logoutPerson(self.request)
        self.request.response.addNoticeNotification(
            _(u'Your account has been deactivated.'))
        self.next_url = self.request.getApplicationURL()


class PersonClaimView(LaunchpadFormView):
    """The page where a user can claim an unvalidated profile."""

    schema = IPersonClaim

    def initialize(self):
        if self.context.is_valid_person_or_team:
            # Valid teams and people aren't claimable. We pull the path
            # out of PATH_INFO to make sure that the exception looks
            # good for subclasses. We're that picky!
            name = self.request['PATH_INFO'].split("/")[-1]
            raise NotFound(self, name, request=self.request)
        LaunchpadFormView.initialize(self)

    def validate(self, data):
        emailaddress = data.get('emailaddress')
        if emailaddress is None:
            self.setFieldError(
                'emailaddress', 'Please enter the email address')
            return

        email = getUtility(IEmailAddressSet).getByEmail(emailaddress)
        error = ""
        if email is None:
            # Email not registered in launchpad, ask the user to try another
            # one.
            error = ("We couldn't find this email address. Please try "
                     "another one that could possibly be associated with "
                     "this profile. Note that this profile's name (%s) was "
                     "generated based on the email address it's "
                     "associated with."
                     % self.context.name)
        elif email.person != self.context:
            if email.person.is_valid_person:
                error = structured(
                         "This email address is associated with yet another "
                         "Launchpad profile, which you seem to have used at "
                         "some point. If that's the case, you can "
                         '<a href="/people/+requestmerge'
                         '?field.dupeaccount=%s">combine '
                         "this profile with the other one</a> (you'll "
                         "have to log in with the other profile first, "
                         "though). If that's not the case, please try with a "
                         "different email address.",
                         self.context.name)
            else:
                # There seems to be another unvalidated profile for you!
                error = structured(
                         "Although this email address is not associated with "
                         "this profile, it's associated with yet another "
                         'one. You can <a href="%s/+claim">claim that other '
                         'profile</a> and then later '
                         '<a href="/people/+requestmerge">combine</a> both '
                         'of them into a single one.',
                         canonical_url(email.person))
        else:
            # Yay! You got the right email this time.
            pass
        if error:
            self.setFieldError('emailaddress', error)

    @property
    def next_url(self):
        return canonical_url(self.context)

    @action(_("E-mail Me"), name="confirm")
    def confirm_action(self, action, data):
        email = data['emailaddress']
        token = getUtility(ILoginTokenSet).new(
            requester=None, requesteremail=None, email=email,
            tokentype=LoginTokenType.PROFILECLAIM)
        token.sendClaimProfileEmail()
        # A dance to assert that we want to break the rules about no
        # unauthenticated sessions. Only after this next line is it safe
        # to use the ``addNoticeNotification`` method.
        allowUnauthenticatedSession(self.request)
        self.request.response.addInfoNotification(_(
            "A confirmation  message has been sent to '${email}'. "
            "Follow the instructions in that message to finish claiming this "
            "profile. "
            "(If the message doesn't arrive in a few minutes, your mail "
            "provider might use 'greylisting', which could delay the message "
            "for up to an hour or two.)", mapping=dict(email=email)))


class BeginTeamClaimView(PersonClaimView):
    """Where you can claim an unvalidated profile turning it into a team.

    This is actually just the first step, where you enter the email address
    of the team and we email further instructions to that address.
    """

    @action(_("Continue"), name="confirm")
    def confirm_action(self, action, data):
        email = data['emailaddress']
        token = getUtility(ILoginTokenSet).new(
            requester=self.user, requesteremail=None, email=email,
            tokentype=LoginTokenType.TEAMCLAIM)
        token.sendClaimTeamEmail()
        self.request.response.addInfoNotification(_(
            "A confirmation message has been sent to '${email}'. "
            "Follow the instructions in that message to finish claiming this "
            "team. "
            "(If the above address is from a mailing list, it may be "
            "necessary to talk with one of its admins to accept the message "
            "from Launchpad so that you can finish the process.)",
            mapping=dict(email=email)))


class RedirectToEditLanguagesView(LaunchpadView):
    """Redirect the logged in user to his +editlanguages page.

    This view should always be registered with a launchpad.AnyPerson
    permission, to make sure the user is logged in. It exists so that
    we provide a link for non logged in users that will require them to login
    and them send them straight to the page they want to go.
    """

    def initialize(self):
        self.request.response.redirect(
            '%s/+editlanguages' % canonical_url(self.user))


class PersonWithKeysAndPreferredEmail:
    """A decorated person that includes GPG keys and preferred emails."""

    # These need to be predeclared to avoid delegates taking them over.
    # Would be nice if there was a way of allowing writes to just work
    # (i.e. no proxying of __set__).
    gpgkeys = None
    sshkeys = None
    preferredemail = None
    delegates(IPerson, 'person')

    def __init__(self, person):
        self.person = person
        self.gpgkeys = []
        self.sshkeys = []

    def addGPGKey(self, key):
        self.gpgkeys.append(key)

    def addSSHKey(self, key):
        self.sshkeys.append(key)

    def setPreferredEmail(self, email):
        self.preferredemail = email


class PersonRdfView:
    """A view that embeds PersonRdfContentsView in a standalone page."""

    template = ViewPageTemplateFile(
        '../templates/person-rdf.pt')

    def __call__(self):
        """Render RDF output, and return it as a string encoded in UTF-8.

        Render the page template to produce RDF output.
        The return value is string data encoded in UTF-8.

        As a side-effect, HTTP headers are set for the mime type
        and filename for download."""
        self.request.response.setHeader('content-type',
                                        'application/rdf+xml')
        self.request.response.setHeader('Content-Disposition',
                                        'attachment; filename=%s.rdf' %
                                            self.context.name)
        unicodedata = self.template()
        encodeddata = unicodedata.encode('utf-8')
        return encodeddata


class PersonRdfContentsView:
    """A view for the contents of Person FOAF RDF."""

    # We need to set the content_type here explicitly in order to
    # preserve the case of the elements (which is not preserved in the
    # parsing of the default text/html content-type.)
    template = ViewPageTemplateFile(
        '../templates/person-rdf-contents.pt',
        content_type="application/rdf+xml")

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def buildMemberData(self):
        members = []
        members_by_id = {}
        raw_members = list(self.context.allmembers)
        if not raw_members:
            # Empty teams have nothing to offer.
            return []
        personset = getUtility(IPersonSet)
        personset.cacheBrandingForPeople(raw_members)
        for member in raw_members:
            decorated_member = PersonWithKeysAndPreferredEmail(member)
            members.append(decorated_member)
            members_by_id[member.id] = decorated_member
        sshkeyset = getUtility(ISSHKeySet)
        gpgkeyset = getUtility(IGPGKeySet)
        emailset = getUtility(IEmailAddressSet)
        for key in sshkeyset.getByPeople(members):
            members_by_id[key.personID].addSSHKey(key)
        for key in gpgkeyset.getGPGKeysForPeople(members):
            members_by_id[key.ownerID].addGPGKey(key)
        for email in emailset.getPreferredEmailForPeople(members):
            members_by_id[email.person.id].setPreferredEmail(email)
        return members

    def __call__(self):
        """Render RDF output.

        This is only used when rendering this to the end-user, and is
        only here to avoid us OOPSing if people access +raw-contents via
        the web. All templates should reuse this view by invoking
        +rdf-contents/template.
        """
        unicodedata = self.template()
        encodeddata = unicodedata.encode('utf-8')
        return encodeddata


def userIsActiveTeamMember(team):
    """Return True if the user is an active member of this team."""
    user = getUtility(ILaunchBag).user
    if user is None:
        return False
    if not check_permission('launchpad.View', team):
        return False
    return user in team.activemembers


class PersonSpecWorkloadView(LaunchpadView):
    """View to render the specification workload for a person or team.

    It shows the set of specifications with which this person has a role.  If
    the person is a team, then all members of the team are presented using
    batching with their individual specifications.
    """

    @cachedproperty
    def members(self):
        """Return a batch navigator for all members.

        This batch does not test for whether the person has specifications or
        not.
        """
        assert self.context.isTeam, (
            "PersonSpecWorkloadView.members can only be called on a team.")
        members = self.context.allmembers
        batch_nav = BatchNavigator(members, self.request)
        return batch_nav


class PersonSpecWorkloadTableView(LaunchpadView):
    """View to render the specification workload table for a person.

    It shows the set of specifications with which this person has a role
    in a single table.
    """

    class PersonSpec:
        """One record from the workload list."""

        def __init__(self, spec, person):
            self.spec = spec
            self.assignee = spec.assignee == person
            self.drafter = spec.drafter == person
            self.approver = spec.approver == person

    @cachedproperty
    def workload(self):
        """This code is copied in large part from browser/sprint.py. It may
        be worthwhile refactoring this to use a common code base.

        Return a structure that lists the specs for which this person is the
        approver, the assignee or the drafter.
        """
        return [PersonSpecWorkloadTableView.PersonSpec(spec, self.context)
                for spec in self.context.specifications()]


class PersonSpecFeedbackView(HasSpecificationsView):

    @cachedproperty
    def feedback_specs(self):
        filter = [SpecificationFilter.FEEDBACK]
        return self.context.specifications(filter=filter)


class ReportedBugTaskSearchListingView(BugTaskSearchListingView):
    """All bugs reported by someone."""

    columns_to_show = ["id", "summary", "bugtargetdisplayname",
                       "importance", "status"]

    def search(self):
        # Specify both owner and bug_reporter to try to prevent the same
        # bug (but different tasks) being displayed.
        return BugTaskSearchListingView.search(
            self,
            extra_params=dict(owner=self.context, bug_reporter=self.context))

    def getSearchPageHeading(self):
        """The header for the search page."""
        return "Bugs reported by %s" % self.context.displayname

    def getAdvancedSearchPageHeading(self):
        """The header for the advanced search page."""
        return "Bugs Reported by %s: Advanced Search" % (
            self.context.displayname)

    def getAdvancedSearchButtonLabel(self):
        """The Search button for the advanced search page."""
        return "Search bugs reported by %s" % self.context.displayname

    def getSimpleSearchURL(self):
        """Return a URL that can be used as an href to the simple search."""
        return canonical_url(self.context) + "/+reportedbugs"

    def shouldShowReporterWidget(self):
        """Should the reporter widget be shown on the advanced search page?"""
        return False

    def shouldShowTagsCombinatorWidget(self):
        """Should the tags combinator widget show on the search page?"""
        return False


class BugSubscriberPackageBugsSearchListingView(BugTaskSearchListingView):
    """Bugs reported on packages for a bug subscriber."""

    columns_to_show = ["id", "summary", "importance", "status"]

    @property
    def current_package(self):
        """Get the package whose bugs are currently being searched."""
        if not (
            self.widgets['distribution'].hasInput() and
            self.widgets['distribution'].getInputValue()):
            raise UnexpectedFormData("A distribution is required")
        if not (
            self.widgets['sourcepackagename'].hasInput() and
            self.widgets['sourcepackagename'].getInputValue()):
            raise UnexpectedFormData("A sourcepackagename is required")

        distribution = self.widgets['distribution'].getInputValue()
        return distribution.getSourcePackage(
            self.widgets['sourcepackagename'].getInputValue())

    def search(self, searchtext=None):
        distrosourcepackage = self.current_package
        return BugTaskSearchListingView.search(
            self, searchtext=searchtext, context=distrosourcepackage)

    @cachedproperty
    def total_bug_counts(self):
        """Return the totals of each type of package bug count as a dict."""
        totals = {
            'open_bugs_count': 0,
            'critical_bugs_count': 0,
            'unassigned_bugs_count': 0,
            'inprogress_bugs_count': 0,}

        for package_counts in self.package_bug_counts:
            for key in totals.keys():
                totals[key] += int(package_counts[key])

        return totals

    @cachedproperty
    def package_bug_counts(self):
        """Return a list of dicts used for rendering package bug counts."""
        L = []
        package_counts = getUtility(IBugTaskSet).getBugCountsForPackages(
            self.user, self.context.getBugSubscriberPackages())
        for package_counts in package_counts:
            package = package_counts['package']
            L.append({
                'package_name': package.displayname,
                'package_search_url':
                    self.getBugSubscriberPackageSearchURL(package),
                'open_bugs_count': package_counts['open'],
                'open_bugs_url': self.getOpenBugsURL(package),
                'critical_bugs_count': package_counts['open_critical'],
                'critical_bugs_url': self.getCriticalBugsURL(package),
                'unassigned_bugs_count': package_counts['open_unassigned'],
                'unassigned_bugs_url': self.getUnassignedBugsURL(package),
                'inprogress_bugs_count': package_counts['open_inprogress'],
                'inprogress_bugs_url': self.getInProgressBugsURL(package)
            })

        return sorted(L, key=itemgetter('package_name'))

    def getOtherBugSubscriberPackageLinks(self):
        """Return a list of the other packages for a bug subscriber.

        This excludes the current package.
        """
        current_package = self.current_package

        other_packages = [
            package for package in self.context.getBugSubscriberPackages()
            if package != current_package]

        package_links = []
        for other_package in other_packages:
            package_links.append({
                'title': other_package.displayname,
                'url': self.getBugSubscriberPackageSearchURL(other_package)})

        return package_links

    def getBugSubscriberPackageSearchURL(self, distributionsourcepackage=None,
                                      advanced=False, extra_params=None):
        """Construct a default search URL for a distributionsourcepackage.

        Optional filter parameters can be specified as a dict with the
        extra_params argument.
        """
        if distributionsourcepackage is None:
            distributionsourcepackage = self.current_package

        params = {
            "field.distribution": distributionsourcepackage.distribution.name,
            "field.sourcepackagename": distributionsourcepackage.name,
            "search": "Search"}

        if extra_params is not None:
            # We must UTF-8 encode searchtext to play nicely with
            # urllib.urlencode, because it may contain non-ASCII characters.
            if extra_params.has_key("field.searchtext"):
                extra_params["field.searchtext"] = (
                    extra_params["field.searchtext"].encode("utf8"))

            params.update(extra_params)

        person_url = canonical_url(self.context)
        query_string = urllib.urlencode(sorted(params.items()), doseq=True)

        if advanced:
            return (person_url + '/+packagebugs-search?advanced=1&%s'
                    % query_string)
        else:
            return person_url + '/+packagebugs-search?%s' % query_string

    def getBugSubscriberPackageAdvancedSearchURL(self,
                                              distributionsourcepackage=None):
        """Build the advanced search URL for a distributionsourcepackage."""
        return self.getBugSubscriberPackageSearchURL(advanced=True)

    def getOpenBugsURL(self, distributionsourcepackage):
        """Return the URL for open bugs on distributionsourcepackage."""
        status_params = {'field.status': []}

        for status in UNRESOLVED_BUGTASK_STATUSES:
            status_params['field.status'].append(status.title)

        return self.getBugSubscriberPackageSearchURL(
            distributionsourcepackage=distributionsourcepackage,
            extra_params=status_params)

    def getCriticalBugsURL(self, distributionsourcepackage):
        """Return the URL for critical bugs on distributionsourcepackage."""
        critical_bugs_params = {
            'field.status': [], 'field.importance': "Critical"}

        for status in UNRESOLVED_BUGTASK_STATUSES:
            critical_bugs_params["field.status"].append(status.title)

        return self.getBugSubscriberPackageSearchURL(
            distributionsourcepackage=distributionsourcepackage,
            extra_params=critical_bugs_params)

    def getUnassignedBugsURL(self, distributionsourcepackage):
        """Return the URL for unassigned bugs on distributionsourcepackage."""
        unassigned_bugs_params = {
            "field.status": [], "field.unassigned": "on"}

        for status in UNRESOLVED_BUGTASK_STATUSES:
            unassigned_bugs_params["field.status"].append(status.title)

        return self.getBugSubscriberPackageSearchURL(
            distributionsourcepackage=distributionsourcepackage,
            extra_params=unassigned_bugs_params)

    def getInProgressBugsURL(self, distributionsourcepackage):
        """Return the URL for unassigned bugs on distributionsourcepackage."""
        inprogress_bugs_params = {"field.status": "In Progress"}

        return self.getBugSubscriberPackageSearchURL(
            distributionsourcepackage=distributionsourcepackage,
            extra_params=inprogress_bugs_params)

    def shouldShowSearchWidgets(self):
        # XXX: Guilherme Salgado 2005-11-05:
        # It's not possible to search amongst the bugs on maintained
        # software, so for now I'll be simply hiding the search widgets.
        return False

    # Methods that customize the advanced search form.
    def getAdvancedSearchPageHeading(self):
        return (
            "Bugs in %s: Advanced Search" % self.current_package.displayname)

    def getAdvancedSearchButtonLabel(self):
        return "Search bugs in %s" % self.current_package.displayname

    def getSimpleSearchURL(self):
        return self.getBugSubscriberPackageSearchURL()


class PersonRelatedBugsView(BugTaskSearchListingView, FeedsMixin):
    """All bugs related to someone."""

    columns_to_show = ["id", "summary", "bugtargetdisplayname",
                       "importance", "status"]

    def search(self, extra_params=None):
        """Return the open bugs related to a person.

        :param extra_params: A dict that provides search params added to
            the search criteria taken from the request. Params in
            `extra_params` take precedence over request params.
        """
        context = self.context
        params = self.buildSearchParams(extra_params=extra_params)
        subscriber_params = copy.copy(params)
        subscriber_params.subscriber = context
        assignee_params = copy.copy(params)
        owner_params = copy.copy(params)
        commenter_params = copy.copy(params)

        # Only override the assignee, commenter and owner if they were not
        # specified by the user.
        if assignee_params.assignee is None:
            assignee_params.assignee = context
        if owner_params.owner is None:
            # Specify both owner and bug_reporter to try to prevent the same
            # bug (but different tasks) being displayed.
            owner_params.owner = context
            owner_params.bug_reporter = context
        if commenter_params.bug_commenter is None:
            commenter_params.bug_commenter = context

        tasks = self.context.searchTasks(
            assignee_params, subscriber_params, owner_params,
            commenter_params)
        return BugListingBatchNavigator(
            tasks, self.request, columns_to_show=self.columns_to_show,
            size=config.malone.buglist_batch_size)

    def getSearchPageHeading(self):
        return "Bugs related to %s" % self.context.displayname

    def getAdvancedSearchPageHeading(self):
        return "Bugs Related to %s: Advanced Search" % (
            self.context.displayname)

    def getAdvancedSearchButtonLabel(self):
        return "Search bugs related to %s" % self.context.displayname

    def getSimpleSearchURL(self):
        return canonical_url(self.context) + "/+bugs"


class PersonAssignedBugTaskSearchListingView(BugTaskSearchListingView):
    """All bugs assigned to someone."""

    columns_to_show = ["id", "summary", "bugtargetdisplayname",
                       "importance", "status"]

    def search(self):
        """Return the open bugs assigned to a person."""
        return BugTaskSearchListingView.search(
            self, extra_params={'assignee': self.context})

    def shouldShowAssigneeWidget(self):
        """Should the assignee widget be shown on the advanced search page?"""
        return False

    def shouldShowAssignedToTeamPortlet(self):
        """Should the team assigned bugs portlet be shown?"""
        return True

    def shouldShowTagsCombinatorWidget(self):
        """Should the tags combinator widget show on the search page?"""
        return False

    def getSearchPageHeading(self):
        """The header for the search page."""
        return "Bugs assigned to %s" % self.context.displayname

    def getAdvancedSearchPageHeading(self):
        """The header for the advanced search page."""
        return "Bugs Assigned to %s: Advanced Search" % (
            self.context.displayname)

    def getAdvancedSearchButtonLabel(self):
        """The Search button for the advanced search page."""
        return "Search bugs assigned to %s" % self.context.displayname

    def getSimpleSearchURL(self):
        """Return a URL that can be usedas an href to the simple search."""
        return canonical_url(self.context) + "/+assignedbugs"


class PersonCommentedBugTaskSearchListingView(BugTaskSearchListingView):
    """All bugs commented on by a Person."""

    columns_to_show = ["id", "summary", "bugtargetdisplayname",
                       "importance", "status"]

    def search(self):
        """Return the open bugs commented on by a person."""
        return BugTaskSearchListingView.search(
            self, extra_params={'bug_commenter': self.context})

    def getSearchPageHeading(self):
        """The header for the search page."""
        return "Bugs commented on by %s" % self.context.displayname

    def getAdvancedSearchPageHeading(self):
        """The header for the advanced search page."""
        return "Bugs commented on by %s: Advanced Search" % (
            self.context.displayname)

    def getAdvancedSearchButtonLabel(self):
        """The Search button for the advanced search page."""
        return "Search bugs commented on by %s" % self.context.displayname

    def getSimpleSearchURL(self):
        """Return a URL that can be used as an href to the simple search."""
        return canonical_url(self.context) + "/+commentedbugs"


class PersonVouchersView(LaunchpadFormView):
    """Form for displaying and redeeming commercial subscription vouchers."""

    custom_widget('voucher', LaunchpadDropdownWidget)
    custom_widget('project', SinglePopupWidget)

    def setUpFields(self):
        """Set up the fields for this view."""

        self.form_fields = []
        # Make the less expensive test for commercial projects first
        # to avoid the more costly fetching of unredeemed vouchers.
        if (self.has_commercial_projects and
            len(self.unredeemed_vouchers) > 0):
            self.form_fields = (self.createProjectField() +
                                self.createVoucherField())

    def createProjectField(self):
        """Create the project field for selection commercial projects.

        The vocabulary shows commercial projects owned by the current user.
        """
        field = FormFields(
            Choice(__name__='project',
                   title=_('Select the project you wish to subscribe'),
                   description=_('Commercial projects you administer'),
                   vocabulary="CommercialProjects",
                   required=True),
            render_context=self.render_context)
        return field

    def createVoucherField(self):
        """Create voucher field.

        Only unredeemed vouchers owned by the user are shown.
        """
        terms = []
        for voucher in self.unredeemed_vouchers:
            text = "%s (%d months)" % (
                voucher.voucher_id, voucher.term_months)
            terms.append(SimpleTerm(voucher, voucher.voucher_id, text))
        voucher_vocabulary = SimpleVocabulary(terms)
        field = FormFields(
            Choice(__name__='voucher',
                   title=_('Select a voucher'),
                   description=_('Choose one of these unredeemed vouchers'),
                   vocabulary=voucher_vocabulary,
                   required=True),
            render_context=self.render_context)
        return field

    @cachedproperty
    def unredeemed_vouchers(self):
        """Get the unredeemed vouchers owned by the user."""
        unredeemed, redeemed = (
            self.context.getCommercialSubscriptionVouchers())
        return unredeemed

    @cachedproperty
    def has_commercial_projects(self):
        """Does the user manage one or more commercial project?

        Users with launchpad.Commercial permission can manage vouchers for any
        project so the property is True always.  Otherwise it is true if the
        vocabulary is not empty.
        """
        if check_permission('launchpad.Commercial', self.context):
            return True
        vocabulary_registry = getVocabularyRegistry()
        vocabulary = vocabulary_registry.get(self.context,
                                             "CommercialProjects")
        return len(vocabulary) > 0

    @action(_("Cancel"), name="cancel",
            validator='validate_cancel')
    def cancel_action(self, action, data):
        """Simply redirect to the user's page."""
        self.next_url = canonical_url(self.context)

    @action(_("Redeem"), name="redeem")
    def redeem_action(self, action, data):
        salesforce_proxy = getUtility(ISalesforceVoucherProxy)
        project = data['project']
        voucher = data['voucher']

        try:
            # The call to redeemVoucher returns True if it succeeds or it
            # raises an exception.  Therefore the return value does not need
            # to be checked.
            result = salesforce_proxy.redeemVoucher(voucher.voucher_id,
                                                    self.context,
                                                    project)
            project.redeemSubscriptionVoucher(
                voucher=voucher.voucher_id,
                registrant=self.context,
                purchaser=self.context,
                subscription_months=voucher.term_months)
            self.request.response.addInfoNotification(
                _("Voucher redeemed successfully"))
            # Force the page to reload so the just consumed voucher is
            # not displayed again (since the field has already been
            # created).
            self.next_url = self.request.URL
        except SalesforceVoucherProxyException, error:
            self.addError(
                _("The voucher could not be redeemed at this time."))
            # Log an OOPS report without raising an error.
            info = (error.__class__, error, None)
            globalErrorUtility = getUtility(IErrorReportingUtility)
            globalErrorUtility.raising(info, self.request)


class SubscribedBugTaskSearchListingView(BugTaskSearchListingView):
    """All bugs someone is subscribed to."""

    columns_to_show = ["id", "summary", "bugtargetdisplayname",
                       "importance", "status"]

    def search(self):
        return BugTaskSearchListingView.search(
            self, extra_params={'subscriber': self.context})

    def getSearchPageHeading(self):
        """The header for the search page."""
        return "Bugs %s is subscribed to" % self.context.displayname

    def getAdvancedSearchPageHeading(self):
        """The header for the advanced search page."""
        return "Bugs %s is Cc'd to: Advanced Search" % (
            self.context.displayname)

    def getAdvancedSearchButtonLabel(self):
        """The Search button for the advanced search page."""
        return "Search bugs %s is Cc'd to" % self.context.displayname

    def getSimpleSearchURL(self):
        """Return a URL that can be used as an href to the simple search."""
        return canonical_url(self.context) + "/+subscribedbugs"


class PersonLanguagesView(LaunchpadView):

    def initialize(self):
        request = self.request
        if request.method == "POST" and "SAVE-LANGS" in request.form:
            self.submitLanguages()

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return (
            IRequestPreferredLanguages(self.request).getPreferredLanguages())

    def visible_checked_languages(self):
        return self.context.languages

    def visible_unchecked_languages(self):
        common_languages = getUtility(ILanguageSet).common_languages
        person_languages = self.context.languages
        return sorted(set(common_languages) - set(person_languages),
                      key=attrgetter('englishname'))

    def getRedirectionURL(self):
        request = self.request
        referrer = request.getHeader('referer')
        if referrer and referrer.startswith(request.getApplicationURL()):
            return referrer
        else:
            return ''

    @property
    def is_current_user(self):
        """Return True when the Context is also the User."""
        return self.user == self.context

    def submitLanguages(self):
        '''Process a POST request to the language preference form.

        This list of languages submitted is compared to the the list of
        languages the user has, and the latter is matched to the former.
        '''

        all_languages = getUtility(ILanguageSet)
        old_languages = self.context.languages
        new_languages = []

        for key in all_languages.keys():
            if self.request.has_key(key) and self.request.get(key) == u'on':
                new_languages.append(all_languages[key])

        if self.is_current_user:
            subject = "your"
        else:
            subject = "%s's" % self.context.displayname

        # Add languages to the user's preferences.
        for language in set(new_languages) - set(old_languages):
            self.context.addLanguage(language)
            self.request.response.addInfoNotification(
                "Added %(language)s to %(subject)s preferred languages." %
                {'language' : language.englishname, 'subject' : subject})

        # Remove languages from the user's preferences.
        for language in set(old_languages) - set(new_languages):
            self.context.removeLanguage(language)
            self.request.response.addInfoNotification(
                "Removed %(language)s from %(subject)s preferred languages." %
                {'language' : language.englishname, 'subject' : subject})

        redirection_url = self.request.get('redirection_url')
        if redirection_url:
            self.request.response.redirect(redirection_url)


class PersonView(LaunchpadView, FeedsMixin):
    """A View class used in almost all Person's pages."""

    @cachedproperty
    def recently_approved_members(self):
        members = self.context.getMembersByStatus(
            TeamMembershipStatus.APPROVED,
            orderBy='-TeamMembership.date_joined')
        return members[:5]

    @cachedproperty
    def recently_proposed_members(self):
        members = self.context.getMembersByStatus(
            TeamMembershipStatus.PROPOSED,
            orderBy='-TeamMembership.date_proposed')
        return members[:5]

    @cachedproperty
    def openpolls(self):
        assert self.context.isTeam()
        return IPollSubset(self.context).getOpenPolls()

    @cachedproperty
    def closedpolls(self):
        assert self.context.isTeam()
        return IPollSubset(self.context).getClosedPolls()

    @cachedproperty
    def notyetopenedpolls(self):
        assert self.context.isTeam()
        return IPollSubset(self.context).getNotYetOpenedPolls()

    @cachedproperty
    def contributions(self):
        """Cache the results of getProjectsAndCategoriesContributedTo()."""
        return self.context.getProjectsAndCategoriesContributedTo(
            limit=5)

    @cachedproperty
    def contributed_categories(self):
        """Return all karma categories in which this person has some karma."""
        categories = set()
        for contrib in self.contributions:
            categories.update(category for category in contrib['categories'])
        return sorted(categories, key=attrgetter('title'))

    @cachedproperty
    def context_is_probably_a_team(self):
        """Return True if we have any indication that context is a team.

        For now, all we do is check whether or not any email associated with
        our context contains the '@lists.' string as that's a very good
        indication this is a team which was automatically created.

        This can only be used when the context is an automatically created
        profile (account_status == NOACCOUNT).
        """
        assert self.context.account_status == AccountStatus.NOACCOUNT, (
            "This can only be used when the context has no account.")
        emails = getUtility(IEmailAddressSet).getByPerson(self.context)
        for email in emails:
            if '@lists.' in email.email:
                return True
        return False

    @cachedproperty
    def is_delegated_identity(self):
        """Should the page delegate identity to the OpenId identitier.

        We only do this if it's enabled for the vhost.
        """
        return (self.context.is_valid_person
                and config.vhost.mainsite.openid_delegate_profile)

    @cachedproperty
    def openid_identity_url(self):
        """The public OpenID identity URL. That's the profile page."""
        profile_url = URI(canonical_url(self.context))
        if not config.vhost.mainsite.openid_delegate_profile:
            # Change the host to point to the production site.
            profile_url.host = config.launchpad.non_restricted_hostname
        return str(profile_url)

    @property
    def subscription_policy_description(self):
        """Return the description of this team's subscription policy."""
        team = self.context
        assert team.isTeam(), (
            'This method can only be called when the context is a team.')
        if team.subscriptionpolicy == TeamSubscriptionPolicy.RESTRICTED:
            description = _(
                "This is a restricted team; new members can only be added "
                "by one of the team's administrators.")
        elif team.subscriptionpolicy == TeamSubscriptionPolicy.MODERATED:
            description = _(
                "This is a moderated team; all subscriptions are subjected "
                "to approval by one of the team's administrators.")
        elif team.subscriptionpolicy == TeamSubscriptionPolicy.OPEN:
            description = _(
                "This is an open team; any user can join and no approval "
                "is required.")
        else:
            raise AssertionError('Unknown subscription policy.')
        return description

    @property
    def user_can_subscribe_to_list(self):
        """Can the user subscribe to this team's mailing list?

        A user can subscribe to the list if the team has an active
        mailing list, and if they do not already have a subscription.
        """
        if self.team_has_mailing_list:
            # If we are already subscribed, then we can not subscribe again.
            return not self.user_is_subscribed_to_list
        else:
            return False

    @property
    def user_is_subscribed_to_list(self):
        """Is the user subscribed to the team's mailing list?

        Subscriptions hang around even if the list is deactivated, etc.

        It is an error to ask if the user is subscribed to a mailing list
        that doesn't exist.
        """
        if self.user is None:
            return False

        mailing_list = self.context.mailing_list
        assert mailing_list is not None, "This team has no mailing list."
        has_subscription = bool(mailing_list.getSubscription(self.user))
        return has_subscription

    @property
    def team_has_mailing_list(self):
        """Is the team mailing list available for subscription?"""
        mailing_list = self.context.mailing_list
        return mailing_list is not None and mailing_list.is_usable

    def getURLToAssignedBugsInProgress(self):
        """Return an URL to a page which lists all bugs assigned to this
        person that are In Progress.
        """
        query_string = urllib.urlencode(
            [('field.status', BugTaskStatus.INPROGRESS.title)])
        url = "%s/+assignedbugs" % canonical_url(self.context)
        return ("%(url)s?search=Search&%(query_string)s"
                % {'url': url, 'query_string': query_string})


    @cachedproperty
    def assigned_bugs_in_progress(self):
        """Return up to 5 assigned bugs that are In Progress."""
        params = BugTaskSearchParams(
            user=self.user, assignee=self.context, omit_dupes=True,
            status=BugTaskStatus.INPROGRESS, orderby='-date_last_updated')
        return self.context.searchTasks(params)[:5]

    @cachedproperty
    def assigned_specs_in_progress(self):
        """Return up to 5 assigned specs that are being worked on."""
        return self.context.assigned_specs_in_progress

    @property
    def has_assigned_bugs_or_specs_in_progress(self):
        """Does the user have any bugs or specs that are being worked on?"""
        bugtasks = self.assigned_bugs_in_progress
        specs = self.assigned_specs_in_progress
        return bugtasks.count() > 0 or specs.count() > 0

    @property
    def viewing_own_page(self):
        return self.user == self.context

    @property
    def can_contact(self):
        """Can the user contact this context (this person or team)?

        Users can contact other valid users and teams. Anonymous users
        cannot contact persons or teams, and no one can contact an invalid
        person (inactive or without a preferred email address).
        """
        return (
            self.user is not None and self.context.is_valid_person_or_team)

    @property
    def contact_link_title(self):
        """Return the appropriate +contactuser link title for the tooltip."""
        if self.context.is_team:
            if self.user.inTeam(self.context):
                return 'Send an email to your team through Launchpad'
            else:
                return "Send an email to this team's owner through Launchpad"
        elif self.viewing_own_page:
            return 'Send an email to yourself through Launchpad'
        else:
            return 'Send an email to this user through Launchpad'

    @property
    def specific_contact_text(self):
        """Return the appropriate link text."""
        if self.context.is_team:
            return 'Contact this team'
        else:
            # Note that we explicitly do not change the text to "Contact
            # yourself" when viewing your own page.
            return 'Contact this user'

    def hasCurrentPolls(self):
        """Return True if this team has any non-closed polls."""
        assert self.context.isTeam()
        return bool(self.openpolls) or bool(self.notyetopenedpolls)

    def no_bounties(self):
        return not (self.context.ownedBounties or
            self.context.reviewerBounties or
            self.context.subscribedBounties or
            self.context.claimedBounties)

    def userIsOwner(self):
        """Return True if the user is the owner of this Team."""
        if self.user is None:
            return False

        return self.user.inTeam(self.context.teamowner)

    def findUserPathToTeam(self):
        assert self.user is not None
        return self.user.findPathToTeam(self.context)

    def indirect_teams_via(self):
        """Return a list of dictionaries, where each dictionary has a team
        in which the person is an indirect member, and a path to membership
        in that team.
        """
        return [{'team': team,
                 'via': ', '.join(
                    [viateam.displayname for viateam in
                        self.context.findPathToTeam(team)[:-1]])}
                for team in self.context.teams_indirectly_participated_in]

    def userIsParticipant(self):
        """Return true if the user is a participant of this team.

        A person is said to be a team participant when he's a member
        of that team, either directly or indirectly via another team
        membership.
        """
        if self.user is None:
            return False
        return self.user.inTeam(self.context)

    def userIsActiveMember(self):
        """Return True if the user is an active member of this team."""
        return userIsActiveTeamMember(self.context)

    def userIsProposedMember(self):
        """Return True if the user is a proposed member of this team."""
        if self.user is None:
            return False
        return self.user in self.context.proposedmembers

    def userCanRequestToLeave(self):
        """Return true if the user can request to leave this team.

        A given user can leave a team only if he's an active member.
        """
        return self.userIsActiveMember()

    @cachedproperty
    def email_address_visibility(self):
        """The EmailAddressVisibleState of this person or team.

        :return: The state of what a logged in user may know of a
            person or team's email addresses.
        :rtype: `EmailAddressVisibleState`
        """
        return EmailAddressVisibleState(self)

    @property
    def visible_email_addresses(self):
        """The list of email address that can be shown.

        The list contains email addresses when the EmailAddressVisibleState's
        PUBLIC or ALLOWED attributes are True. The preferred email
        address is the first in the list, the other validated email addresses
        are not ordered.

        :return: A list of email address strings that can be seen.
        """
        visible_states = (
            EmailAddressVisibleState.PUBLIC, EmailAddressVisibleState.ALLOWED)
        if self.email_address_visibility.state in visible_states:
            emails = sorted(
                email.email for email in self.context.validatedemails)
            emails.insert(0, self.context.preferredemail.email)
            return emails
        else:
            return []

    @property
    def visible_email_address_description(self):
        """A description of who can see a user's email addresses.

        :return: A string, or None if the email addresses cannot be viewed
            by any user.
        """
        state = self.email_address_visibility.state
        if state is EmailAddressVisibleState.PUBLIC:
            return 'This email address is only visible to Launchpad users.'
        elif state is EmailAddressVisibleState.ALLOWED:
            return 'This email address is not disclosed to others.'
        else:
            return None

    def showSSHKeys(self):
        """Return a data structure used for display of raw SSH keys"""
        self.request.response.setHeader('Content-Type', 'text/plain')
        keys = []
        for key in self.context.sshkeys:
            if key.keytype == SSHKeyType.DSA:
                type_name = 'ssh-dss'
            elif key.keytype == SSHKeyType.RSA:
                type_name = 'ssh-rsa'
            else:
                type_name = 'Unknown key type'
            keys.append("%s %s %s" % (type_name, key.keytext, key.comment))
        return "\n".join(keys)

    @cachedproperty
    def archive_url(self):
        """Return a url to a mailing list archive for the team's list.

        If the person is not a team, does not have a mailing list, that
        mailing list has never been activated, or the team is private and the
        logged in user is not a team member, return None instead.
        """
        mailing_list = self.context.mailing_list
        if mailing_list is None:
            return None
        elif mailing_list.is_public:
            return mailing_list.archive_url
        elif self.user is None:
            return None
        elif self.user.inTeam(self.context):
            return mailing_list.archive_url
        else:
            return None


class EmailAddressVisibleState:
    """The state of a person's email addresses w.r.t. the logged in user.

    There are five states that describe the visibility of a person or
    team's addresses to a logged in user, only one will be True:

    * LOGIN_REQUIRED: The user is anonymous; email addresses are never
      visible to anonymous users.
    * NONE_AVAILABLE: The person has no validated email addresses or the
      team has no contact address registered, so there is nothing to show.
    * PUBLIC: The person is not hiding their email addresses, or the team
      has a contact address, so any logged in user may view them.
    * HIDDEN: The person is hiding their email address, so even logged in
      users cannot view them.  Teams cannot hide their contact address.
    * ALLOWED: The person is hiding their email address, but the logged in
      user has permission to see them.  This is either because the user is
      viewing their own page or because the user is a privileged
      administrator.
    """
    LOGIN_REQUIRED = object()
    NONE_AVAILABLE = object()
    PUBLIC = object()
    HIDDEN = object()
    ALLOWED = object()

    def __init__(self, view):
        """Set the state.

        :param view: The view that provides the current user and the
            context (person or team).
        :type view: `LaunchpadView`
        """
        if view.user is None:
            self.state = EmailAddressVisibleState.LOGIN_REQUIRED
        elif view.context.preferredemail is None:
            self.state = EmailAddressVisibleState.NONE_AVAILABLE
        elif not view.context.hide_email_addresses:
            self.state = EmailAddressVisibleState.PUBLIC
        elif check_permission('launchpad.View',  view.context.preferredemail):
            self.state = EmailAddressVisibleState.ALLOWED
        else:
            self.state = EmailAddressVisibleState.HIDDEN

    @property
    def is_login_required(self):
        """Is login required to see the person or team's addresses?"""
        return self.state is EmailAddressVisibleState.LOGIN_REQUIRED

    @property
    def are_none_available(self):
        """Does the person or team not have any email addresses?"""
        return self.state is EmailAddressVisibleState.NONE_AVAILABLE

    @property
    def are_public(self):
        """Are the person's or team's email addresses public to users?"""
        return self.state is EmailAddressVisibleState.PUBLIC

    @property
    def are_hidden(self):
        """Are the person's or team's email addresses hidden from the user?"""
        return self.state is EmailAddressVisibleState.HIDDEN

    @property
    def are_allowed(self):
        """Is the user allowed to see the person's or team's addresses?"""
        return self.state is EmailAddressVisibleState.ALLOWED


class PersonIndexView(XRDSContentNegotiationMixin, PersonView):
    """View class for person +index and +xrds pages."""

    xrds_template = ViewPageTemplateFile(
        "../templates/person-xrds.pt")

    def initialize(self):
        super(PersonIndexView, self).initialize()
        # This view requires the gmap2 Javascript in order to render the map
        # with the person's usual location.
        self.request.needs_gmap2 = True
        if self.request.method == "POST":
            self.processForm()

    @cachedproperty
    def enable_xrds_discovery(self):
        """Only enable discovery if person is OpenID enabled."""
        return self.is_delegated_identity

    @cachedproperty
    def openid_server_url(self):
        """The OpenID Server endpoint URL for Launchpad."""
        return CurrentOpenIDEndPoint.getOldServiceURL()

    @cachedproperty
    def openid_identity_url(self):
        return IOpenIDPersistentIdentity(
            self.context).old_openid_identity_url

    def processForm(self):
        if not self.request.form.get('unsubscribe'):
            raise UnexpectedFormData(
                "The mailing list form did not receive the expected form "
                "fields.")

        mailing_list = self.context.mailing_list
        if mailing_list is None:
            raise UnexpectedFormData(
                _("This team does not have a mailing list."))
        if not self.user:
            raise Unauthorized(
                _("You must be logged in to unsubscribe."))
        try:
            mailing_list.unsubscribe(self.user)
        except CannotUnsubscribe:
            self.request.response.addErrorNotification(
                _("You could not be unsubscribed from the team mailing "
                  "list."))
        else:
            self.request.response.addInfoNotification(
                _("You have been unsubscribed from the team "
                  "mailing list."))
        self.request.response.redirect(canonical_url(self.context))

    def map_portlet_html(self):
        """Generate the HTML which shows the map portlet."""
        assert self.request.needs_gmap2, (
            "To use this method a view must flag that it needs gmap2.")
        assert self.context.latitude is not None, (
            "Can't generate the map for a person who hasn't set a location.")

        replacements = {'center_lat': self.context.latitude,
                        'center_lng': self.context.longitude}
        return u"""
            <script type="text/javascript">
                renderPersonMapSmall(%(center_lat)s, %(center_lng)s);
            </script>""" % replacements

    @property
    def should_show_map_portlet(self):
        """Should the map portlet be displayed?

        The map portlet is displayed only if the person has no location
        specified, or if the user has permission to view the person's
        location.
        """
        if self.context.location is None:
            return True
        else:
            return check_permission('launchpad.View', self.context.location)


class PersonCodeOfConductEditView(LaunchpadView):

    def performCoCChanges(self):
        """Make changes to code-of-conduct signature records for this
        person.
        """
        sig_ids = self.request.form.get("DEACTIVATE_SIGNATURE")

        if sig_ids is not None:
            sCoC_util = getUtility(ISignedCodeOfConductSet)

            # verify if we have multiple entries to deactive
            if not isinstance(sig_ids, list):
                sig_ids = [sig_ids]

            for sig_id in sig_ids:
                sig_id = int(sig_id)
                # Deactivating signature
                comment = 'Deactivated by Owner'
                sCoC_util.modifySignature(sig_id, self.user, comment, False)

            return True


class PersonEditWikiNamesView(LaunchpadView):
    def _validateWikiURL(self, url):
        """Validate the URL.

        Make sure that the result is a valid URL with only the
        appropriate schemes.
        """
        try:
            uri = URI(url)
            if uri.scheme not in ('http', 'https'):
                self.error_message = structured(
                    'The URL scheme "%(scheme)s" is not allowed.  '
                    'Only http or https URLs may be used.', scheme=uri.scheme)
                return False
        except InvalidURIError, e:
            self.error_message = structured(
                '"%(url)s" is not a valid URL.', url=url)
            return False
        return True

    def _sanitizeWikiURL(self, url):
        """Strip whitespaces and make sure :url ends in a single '/'."""
        if not url:
            return url
        return '%s/' % url.strip().rstrip('/')

    def initialize(self):
        """Process the WikiNames form."""
        self.error_message = None
        if self.request.method != "POST":
            # Nothing to do
            return

        form = self.request.form
        context = self.context
        wikinameset = getUtility(IWikiNameSet)

        for w in context.wiki_names:
            # XXX: GuilhermeSalgado 2005-08-25:
            # We're exposing WikiName IDs here because that's the only
            # unique column we have. If we don't do this we'll have to
            # generate the field names using the WikiName.wiki and
            # WikiName.wikiname columns (because these two columns make
            # another unique identifier for WikiNames), but that's tricky and
            # not worth the extra work.
            if form.get('remove_%d' % w.id):
                w.destroySelf()
            else:
                wiki = self._sanitizeWikiURL(form.get('wiki_%d' % w.id))
                wikiname = form.get('wikiname_%d' % w.id)
                if not (wiki and wikiname):
                    self.error_message = structured(
                        "Neither Wiki nor WikiName can be empty.")
                    return
                if not self._validateWikiURL(wiki):
                    return
                w.wiki = wiki
                w.wikiname = wikiname

        wiki = self._sanitizeWikiURL(form.get('newwiki'))
        wikiname = form.get('newwikiname')
        if wiki or wikiname:
            if wiki and wikiname:
                existingwiki = wikinameset.getByWikiAndName(wiki, wikiname)
                if existingwiki and existingwiki.person != context:
                    self.error_message = structured(
                        'The WikiName %s%s is already registered by '
                        '<a href="%s">%s</a>.',
                        wiki, wikiname, canonical_url(existingwiki.person),
                        existingwiki.person.browsername)
                    return
                elif existingwiki:
                    self.error_message = structured(
                        'The WikiName %s%s already belongs to you.',
                        wiki, wikiname)
                    return
                if not self._validateWikiURL(wiki):
                    return
                wikinameset.new(context, wiki, wikiname)
            else:
                self.newwiki = wiki
                self.newwikiname = wikiname
                self.error_message = structured(
                    "Neither Wiki nor WikiName can be empty.")
                return


class PersonEditIRCNicknamesView(LaunchpadView):

    def initialize(self):
        """Process the IRC nicknames form."""
        self.error_message = None
        if self.request.method != "POST":
            # Nothing to do
            return

        form = self.request.form
        for ircnick in self.context.ircnicknames:
            # XXX: GuilhermeSalgado 2005-08-25:
            # We're exposing IrcID IDs here because that's the only
            # unique column we have, so we don't have anything else that we
            # can use to make field names that allow us to uniquely identify
            # them.
            if form.get('remove_%d' % ircnick.id):
                ircnick.destroySelf()
            else:
                nick = form.get('nick_%d' % ircnick.id)
                network = form.get('network_%d' % ircnick.id)
                if not (nick and network):
                    self.error_message = structured(
                        "Neither Nickname nor Network can be empty.")
                    return
                ircnick.nickname = nick
                ircnick.network = network

        nick = form.get('newnick')
        network = form.get('newnetwork')
        if nick or network:
            if nick and network:
                getUtility(IIrcIDSet).new(self.context, network, nick)
            else:
                self.newnick = nick
                self.newnetwork = network
                self.error_message = structured(
                    "Neither Nickname nor Network can be empty.")
                return


class PersonEditJabberIDsView(LaunchpadView):

    def initialize(self):
        """Process the Jabber ID form."""
        self.error_message = None
        if self.request.method != "POST":
            # Nothing to do
            return

        form = self.request.form
        for jabber in self.context.jabberids:
            if form.get('remove_%s' % jabber.jabberid):
                jabber.destroySelf()
            else:
                jabberid = form.get('jabberid_%s' % jabber.jabberid)
                if not jabberid:
                    self.error_message = structured(
                        "You cannot save an empty Jabber ID.")
                    return
                jabber.jabberid = jabberid

        jabberid = form.get('newjabberid')
        if jabberid:
            jabberset = getUtility(IJabberIDSet)
            existingjabber = jabberset.getByJabberID(jabberid)
            if existingjabber is None:
                jabberset.new(self.context, jabberid)
            elif existingjabber.person != self.context:
                self.error_message = structured(
                    'The Jabber ID %s is already registered by '
                    '<a href="%s">%s</a>.',
                    jabberid, canonical_url(existingjabber.person),
                    existingjabber.person.browsername)
                return
            else:
                self.error_message = structured(
                    'The Jabber ID %s already belongs to you.', jabberid)
                return


class PersonEditSSHKeysView(LaunchpadView):

    implements(IPersonEditMenu)

    info_message = None
    error_message = None

    def initialize(self):
        if self.request.method != "POST":
            # Nothing to do
            return

        action = self.request.form.get('action')

        if action == 'add_ssh':
            self.add_ssh()
        elif action == 'remove_ssh':
            self.remove_ssh()
        else:
            raise UnexpectedFormData("Unexpected action: %s" % action)

    def add_ssh(self):
        sshkey = self.request.form.get('sshkey')
        try:
            kind, keytext, comment = sshkey.split(' ', 2)
        except ValueError:
            self.error_message = structured('Invalid public key')
            return

        if not (kind and keytext and comment):
            self.error_message = structured('Invalid public key')
            return

        process = subprocess.Popen(
            '/usr/bin/ssh-vulnkey -', shell=True, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out, err) = process.communicate(sshkey.encode('utf-8'))
        if 'compromised' in out.lower():
            self.error_message = structured(
                'This key is known to be compromised due to a security flaw '
                'in the software used to generate it, so it will not be '
                'accepted by Launchpad. See the full '
                '<a href="http://www.ubuntu.com/usn/usn-612-2">Security '
                'Notice</a> for further information and instructions on how '
                'to generate another key.')
            return

        if kind == 'ssh-rsa':
            keytype = SSHKeyType.RSA
        elif kind == 'ssh-dss':
            keytype = SSHKeyType.DSA
        else:
            self.error_message = structured('Invalid public key')
            return

        getUtility(ISSHKeySet).new(self.user, keytype, keytext, comment)
        self.info_message = structured('SSH public key added.')

    def remove_ssh(self):
        key_id = self.request.form.get('key')
        if not key_id:
            raise UnexpectedFormData('SSH Key was not defined')

        sshkey = getUtility(ISSHKeySet).getByID(key_id)
        if sshkey is None:
            self.error_message = structured(
                "Cannot remove a key that doesn't exist")
            return

        if sshkey.person != self.user:
            raise UnexpectedFormData("Cannot remove someone else's key")

        comment = sshkey.comment
        sshkey.destroySelf()
        self.info_message = structured('Key "%s" removed' % comment)


class PersonTranslationView(LaunchpadView):
    """View for translation-related Person pages."""
    @cachedproperty
    def batchnav(self):
        batchnav = BatchNavigator(self.context.translation_history,
                                  self.request)
        # XXX: kiko 2006-03-17 bug=60320: Because of a template reference
        # to pofile.potemplate.displayname, it would be ideal to also
        # prejoin inside translation_history:
        #   potemplate.productseries
        #   potemplate.productseries.product
        #   potemplate.distroseries
        #   potemplate.distroseries.distribution
        #   potemplate.sourcepackagename
        # However, a list this long may be actually suggesting that
        # displayname be cached in a table field; particularly given the
        # fact that it won't be altered very often. At any rate, the
        # code below works around this by caching all the templates in
        # one shot. The list() ensures that we materialize the query
        # before passing it on to avoid reissuing it. Note also that the
        # fact that we iterate over currentBatch() here means that the
        # translation_history query is issued again. Tough luck.
        ids = set(record.pofile.potemplate.id
                  for record in batchnav.currentBatch())
        if ids:
            cache = list(getUtility(IPOTemplateSet).getByIDs(ids))

        return batchnav

    @cachedproperty
    def translation_groups(self):
        """Return translation groups a person is a member of."""
        return list(self.context.translation_groups)

    @cachedproperty
    def person_filter_querystring(self):
        """Return person's name appropriate for including in links."""
        return urllib.urlencode({'person': self.context.name})

    def should_display_message(self, translationmessage):
        """Should a certain `TranslationMessage` be displayed.

        Return False if user is not logged in and message may contain
        sensitive data such as email addresses.

        Otherwise, return True.
        """
        if self.user:
            return True
        return not (
            translationmessage.potmsgset.hide_translations_from_anonymous)


class PersonTranslationRelicensingView(LaunchpadFormView):
    """View for Person's translation relicensing page."""
    schema = ITranslationRelicensingAgreementEdit
    field_names = ['allow_relicensing', 'back_to']
    custom_widget(
        'allow_relicensing', LaunchpadRadioWidget, orientation='vertical')
    custom_widget('back_to', TextWidget, visible=False)

    @property
    def initial_values(self):
        """Set the default value for the relicensing radio buttons."""
        # If the person has previously made a choice, we default to that.
        # Otherwise, we default to BSD, because that's what we'd prefer.
        if self.context.translations_relicensing_agreement == False:
            default = TranslationRelicensingAgreementOptions.REMOVE
        else:
            default = TranslationRelicensingAgreementOptions.BSD
        return {
            "allow_relicensing": default,
            "back_to": self.request.get('back_to'),
            }

    @property
    def relicensing_url(self):
        """Return an URL for this view."""
        return canonical_url(self.context, view_name='+licensing')

    def getSafeRedirectURL(self, url):
        """Successful form submission should send to this URL."""
        if url and url.startswith(self.request.getApplicationURL()):
            return url
        else:
            return canonical_url(self.context)

    @action(_("Confirm"), name="submit")
    def submit_action(self, action, data):
        """Store person's decision about translations relicensing.

        Decision is stored through
        `IPerson.translations_relicensing_agreement`
        which uses TranslationRelicensingAgreement table.
        """
        allow_relicensing = data['allow_relicensing']
        if allow_relicensing == TranslationRelicensingAgreementOptions.BSD:
            self.context.translations_relicensing_agreement = True
            self.request.response.addInfoNotification(_(
                "Thank you for BSD-licensing your translations."))
        elif (allow_relicensing ==
            TranslationRelicensingAgreementOptions.REMOVE):
            self.context.translations_relicensing_agreement = False
            self.request.response.addInfoNotification(_(
                "We respect your choice. "
                "Your translations will be removed once we complete the "
                "switch to the BSD license. "
                "Thanks for trying out Launchpad Translations."))
        else:
            raise AssertionError(
                "Unknown allow_relicensing value: %r" % allow_relicensing)
        self.next_url = self.getSafeRedirectURL(data['back_to'])


class PersonGPGView(LaunchpadView):
    """View for the GPG-related actions for a Person

    Supports claiming (importing) a key, validating it and deactivating
    it. Also supports removing the token generated for validation (in
    the case you want to give up on importing the key).
    """

    implements(IPersonEditMenu)

    key = None
    fingerprint = None

    key_ok = False
    invalid_fingerprint = False
    key_retrieval_failed = False
    key_already_imported = False

    error_message = None
    info_message = None

    def keyserver_url(self):
        assert self.fingerprint
        return getUtility(
            IGPGHandler).getURLForKeyInServer(self.fingerprint, public=True)

    def form_action(self):
        permitted_actions = ['claim_gpg', 'deactivate_gpg',
                             'remove_gpgtoken', 'reactivate_gpg']
        if self.request.method != "POST":
            return ''
        action = self.request.form.get('action')
        if action and (action not in permitted_actions):
            raise UnexpectedFormData("Action was not defined")
        getattr(self, action)()

    def claim_gpg(self):
        # XXX cprov 2005-04-01: As "Claim GPG key" takes a lot of time, we
        # should process it throught the NotificationEngine.
        gpghandler = getUtility(IGPGHandler)
        fingerprint = self.request.form.get('fingerprint')
        self.fingerprint = gpghandler.sanitizeFingerprint(fingerprint)

        if not self.fingerprint:
            self.invalid_fingerprint = True
            return

        gpgkeyset = getUtility(IGPGKeySet)
        if gpgkeyset.getByFingerprint(self.fingerprint):
            self.key_already_imported = True
            return

        try:
            key = gpghandler.retrieveKey(self.fingerprint)
        except GPGKeyNotFoundError:
            self.key_retrieval_failed = True
            return

        self.key = key
        if not key.expired and not key.revoked:
            self._validateGPG(key)
            self.key_ok = True

    def deactivate_gpg(self):
        key_ids = self.request.form.get('DEACTIVATE_GPGKEY')

        if key_ids is None:
            self.error_message = structured(
                'No key(s) selected for deactivation.')
            return

        # verify if we have multiple entries to deactive
        if not isinstance(key_ids, list):
            key_ids = [key_ids]

        gpgkeyset = getUtility(IGPGKeySet)

        deactivated_keys = []
        for key_id in key_ids:
            gpgkey = gpgkeyset.get(key_id)
            if gpgkey is None:
                continue
            if gpgkey.owner != self.user:
                self.error_message = structured(
                    "Cannot deactivate someone else's key")
                return
            gpgkey.active = False
            deactivated_keys.append(gpgkey.displayname)

        flush_database_updates()
        self.info_message = structured(
           'Deactivated key(s): %s', ", ".join(deactivated_keys))

    def remove_gpgtoken(self):
        token_fingerprints = self.request.form.get('REMOVE_GPGTOKEN')

        if token_fingerprints is None:
            self.error_message = structured(
                'No key(s) pending validation selected.')
            return

        logintokenset = getUtility(ILoginTokenSet)
        if not isinstance(token_fingerprints, list):
            token_fingerprints = [token_fingerprints]

        cancelled_fingerprints = []
        for fingerprint in token_fingerprints:
            logintokenset.deleteByFingerprintRequesterAndType(
                fingerprint, self.user, LoginTokenType.VALIDATEGPG)
            logintokenset.deleteByFingerprintRequesterAndType(
                fingerprint, self.user, LoginTokenType.VALIDATESIGNONLYGPG)
            cancelled_fingerprints.append(fingerprint)

        self.info_message = structured(
            'Cancelled validation of key(s): %s',
            ", ".join(cancelled_fingerprints))

    def reactivate_gpg(self):
        key_ids = self.request.form.get('REACTIVATE_GPGKEY')

        if key_ids is None:
            self.error_message = structured(
                'No key(s) selected for reactivation.')
            return

        found = []
        notfound = []
        # verify if we have multiple entries to deactive
        if not isinstance(key_ids, list):
            key_ids = [key_ids]

        gpghandler = getUtility(IGPGHandler)
        keyset = getUtility(IGPGKeySet)

        for key_id in key_ids:
            gpgkey = keyset.get(key_id)
            try:
                key = gpghandler.retrieveKey(gpgkey.fingerprint)
            except GPGKeyNotFoundError:
                notfound.append(gpgkey.fingerprint)
            else:
                found.append(key.displayname)
                self._validateGPG(key)

        comments = []
        if len(found) > 0:
            comments.append(
                'A message has been sent to %s with instructions to '
                'reactivate these key(s): %s'
                % (self.context.preferredemail.email, ', '.join(found)))
        if len(notfound) > 0:
            if len(notfound) == 1:
                comments.append(
                    'Launchpad failed to retrieve this key from '
                    'the keyserver: %s. Please make sure the key is '
                    'published in a keyserver (such as '
                    '<a href="http://pgp.mit.edu">pgp.mit.edu</a>) before '
                    'trying to reactivate it again.' % (', '.join(notfound)))
            else:
                comments.append(
                    'Launchpad failed to retrieve these keys from '
                    'the keyserver: %s. Please make sure the keys '
                    'are published in a keyserver (such as '
                    '<a href="http://pgp.mit.edu">pgp.mit.edu</a>) '
                    'before trying to reactivate them '
                    'again.' % (', '.join(notfound)))

        self.info_message = structured('\n<br />\n'.join(comments))

    def _validateGPG(self, key):
        logintokenset = getUtility(ILoginTokenSet)
        bag = getUtility(ILaunchBag)

        preferredemail = bag.user.preferredemail.email
        login = bag.login

        if key.can_encrypt:
            tokentype = LoginTokenType.VALIDATEGPG
        else:
            tokentype = LoginTokenType.VALIDATESIGNONLYGPG

        token = logintokenset.new(self.context, login,
                                  preferredemail,
                                  tokentype,
                                  fingerprint=key.fingerprint)

        token.sendGPGValidationRequest(key)


class PersonChangePasswordView(LaunchpadFormView):

    implements(IPersonEditMenu)

    label = "Change your password"
    schema = IPersonChangePassword
    field_names = ['currentpassword', 'password']
    custom_widget('password', PasswordChangeWidget)

    @property
    def next_url(self):
        return canonical_url(self.context)

    def validate(self, form_values):
        currentpassword = form_values.get('currentpassword')
        encryptor = getUtility(IPasswordEncryptor)
        if not encryptor.validate(currentpassword, self.context.password):
            self.setFieldError('currentpassword', _(
                "The provided password doesn't match your current password."))

    @action(_("Change Password"), name="submit")
    def submit_action(self, action, data):
        password = data['password']
        self.context.password = password
        self.request.response.addInfoNotification(_(
            "Password changed successfully"))


class BasePersonEditView(LaunchpadEditFormView):

    schema = IPerson
    field_names = []

    @action(_("Save"), name="save")
    def action_save(self, action, data):
        self.updateContextFromData(data)
        self.next_url = canonical_url(self.context)


class PersonEditHomePageView(BasePersonEditView):

    field_names = ['homepage_content']
    custom_widget(
        'homepage_content', TextAreaWidget, height=30, width=30)


class PersonEditView(BasePersonEditView):
    """The Person 'Edit' page."""

    field_names = ['displayname', 'name', 'mugshot', 'homepage_content',
                   'hide_email_addresses', 'verbose_bugnotifications']
    custom_widget('mugshot', ImageChangeWidget, ImageChangeWidget.EDIT_STYLE)

    implements(IPersonEditMenu)

    # Will contain an hidden input when the user is renaming his
    # account with full knowledge of the consequences.
    i_know_this_is_an_openid_security_issue_input = None

    @property
    def cancel_url(self):
        """The URL that the 'Cancel' link should return to."""
        return canonical_url(self.context)

    def validate(self, data):
        """If the name changed, warn the user about the implications."""
        new_name = data.get('name')
        bypass_check = self.request.form_ng.getOne(
            'i_know_this_is_an_openid_security_issue', 0)
        if (new_name and new_name != self.context.name and
            len(self.unknown_trust_roots_user_logged_in) > 0
            and not bypass_check):
            # Warn the user that they might shoot themselves in the foot.
            self.setFieldError('name', structured(dedent("""
            <div class="inline-warning">
              <p>Changing your name will change your
                  public OpenID identifier. This means that you might be
                  locked out of certain sites where you used it, or that
                  somebody could create a new profile with the same name and
                  log in as you on these third-party sites. See
                  <a href="https://help.launchpad.net/OpenID#rename-account"
                    >https://help.launchpad.net/OpenID#rename-account</a>
                  for more information.
              </p>
              <p> You may have used your identifier on the following
                  sites:<br> %s.
              </p>
              <p>If you click 'Save' again, we will rename your account
                 anyway.
              </p>
            </div>"""),
             ", ".join(self.unknown_trust_roots_user_logged_in)))
            self.i_know_this_is_an_openid_security_issue_input = dedent("""\
                <input type="hidden"
                       id="i_know_this_is_an_openid_security_issue"
                       name="i_know_this_is_an_openid_security_issue"
                       value="1">""")

    @cachedproperty
    def unknown_trust_roots_user_logged_in(self):
        """The unknown trust roots the user has logged in using OpenID.

        We assume that they logged in using their delegated profile OpenID,
        since that's the one we advertise.
        """
        identifier = IOpenIDPersistentIdentity(self.context)
        unknown_trust_root_login_records = list(
            getUtility(IOpenIDRPSummarySet).getByIdentifier(
                identifier.old_openid_identity_url, True))
        if identifier.new_openid_identifier is not None:
            unknown_trust_root_login_records.extend(list(
                getUtility(IOpenIDRPSummarySet).getByIdentifier(
                    identifier.new_openid_identity_url, True)))
        return sorted([
            record.trust_root
            for record in unknown_trust_root_login_records])

    @action(_("Save Changes"), name="save")
    def action_save(self, action, data):
        self.updateContextFromData(data)
        self.next_url = canonical_url(self.context)


class PersonBrandingView(BrandingChangeView):

    field_names = ['logo', 'mugshot']
    schema = IPerson


class TeamJoinView(PersonView):

    def initialize(self):
        super(TeamJoinView, self).initialize()
        if self.request.method == "POST":
            self.processForm()

    @property
    def join_allowed(self):
        """Is the logged in user allowed to join this team?

        The answer is yes if this team's subscription policy is not RESTRICTED
        and this team's visibility is either None or PUBLIC.
        """
        # Joining a moderated team will put you on the proposed_members
        # list. If it is a private membership team, you are not allowed
        # to view the proposed_members attribute until you are an
        # active member; therefore, it would look like the join button
        # is broken. Either private membership teams should always have a
        # restricted subscription policy, or we need a more complicated
        # permission model.
        if not (self.context.visibility is None
                or self.context.visibility == PersonVisibility.PUBLIC):
            return False

        restricted = TeamSubscriptionPolicy.RESTRICTED
        return self.context.subscriptionpolicy != restricted

    @property
    def user_can_request_to_join(self):
        """Can the logged in user request to join this team?

        The user can request if he's allowed to join this team and if he's
        not yet an active member of this team.
        """
        if not self.join_allowed:
            return False
        return not (self.userIsActiveMember() or self.userIsProposedMember())

    @property
    def user_wants_list_subscriptions(self):
        """Is the user interested in subscribing to mailing lists?"""
        return (self.user.mailing_list_auto_subscribe_policy !=
                MailingListAutoSubscribePolicy.NEVER)

    @property
    def team_is_moderated(self):
        """Is this team a moderated team?

        Return True if the team's subscription policy is MODERATED.
        """
        policy = self.context.subscriptionpolicy
        return policy == TeamSubscriptionPolicy.MODERATED

    def processForm(self):
        request = self.request
        user = self.user
        context = self.context
        response = self.request.response

        notification = None
        if 'join' in request.form and self.user_can_request_to_join:
            # Shut off mailing list auto-subscription - we want direct
            # control over it.
            user.join(context, may_subscribe_to_list=False)

            if self.team_is_moderated:
                response.addInfoNotification(
                    _('Your request to join ${team} is awaiting '
                      'approval.',
                      mapping={'team': context.displayname}))
            else:
                response.addInfoNotification(
                    _('You have successfully joined ${team}.',
                      mapping={'team': context.displayname}))

            if 'mailinglist_subscribe' in request.form:
                self._subscribeToList()

        elif 'join' in request.form:
            response.addErrorNotification(
                _('You cannot join ${team}.',
                  mapping={'team': context.displayname}))
        elif 'goback' in request.form:
            # User clicked on the 'Go back' button, so we'll simply redirect.
            pass
        else:
            raise UnexpectedFormData(
                "Couldn't find any of the expected actions.")
        self.request.response.redirect(canonical_url(context))

    def _subscribeToList(self):
        """Subscribe the user to the team's mailing list."""
        response = self.request.response

        if self.user_can_subscribe_to_list:
            # 'user_can_subscribe_to_list' should have dealt with
            # all of the error cases.
            self.context.mailing_list.subscribe(self.user)

            if self.team_is_moderated:
                response.addInfoNotification(
                    _('Your mailing list subscription is '
                      'awaiting approval.'))
            else:
                response.addInfoNotification(
                    structured(
                        _("You have been subscribed to this "
                          "team&#x2019;s mailing list.")))
        else:
            # A catch-all case, perhaps from stale or mangled
            # form data.
            response.addErrorNotification(
                _('Mailing list subscription failed.'))


class TeamAddMyTeamsView(LaunchpadFormView):
    """Propose/add to this team any team that you're an administrator of."""

    custom_widget('teams', LabeledMultiCheckBoxWidget)

    def initialize(self):
        context = self.context
        if context.subscriptionpolicy == TeamSubscriptionPolicy.MODERATED:
            self.label = 'Propose these teams as members'
        else:
            self.label = 'Add these teams to %s' % context.displayname
        self.next_url = canonical_url(context)
        super(TeamAddMyTeamsView, self).initialize()

    def setUpFields(self):
        terms = []
        for team in self.candidate_teams:
            text = '<a href="%s">%s</a>' % (
                canonical_url(team), team.displayname)
            terms.append(SimpleTerm(team, team.name, text))
        self.form_fields = FormFields(
            List(__name__='teams',
                 title=_(''),
                 value_type=Choice(vocabulary=SimpleVocabulary(terms)),
                 required=False),
            render_context=self.render_context)

    def setUpWidgets(self, context=None):
        super(TeamAddMyTeamsView, self).setUpWidgets(context)
        self.widgets['teams'].display_label = False

    @cachedproperty
    def candidate_teams(self):
        """Return the set of teams that can be added/proposed for the context.

        We return only teams that the user can administer, that aren't already
        a member in the context or that the context isn't a member of. (Of
        course, the context is also omitted.)
        """
        candidates = []
        for team in self.user.getAdministratedTeams():
            if team == self.context:
                continue
            elif team in self.context.activemembers:
                continue
            elif self.context.hasParticipationEntryFor(team):
                continue
            candidates.append(team)
        return candidates

    @action(_("Cancel"), name="cancel",
            validator=LaunchpadFormView.validate_none)
    def cancel_action(self, action, data):
        """Simply redirect to the team's page."""
        pass

    def validate(self, data):
        if len(data.get('teams', [])) == 0:
            self.setFieldError('teams',
                               'Please select the team(s) you want to be '
                               'member(s) of this team.')

    def hasCandidates(self, action):
        """Return whether the user has teams to propose."""
        return len(self.candidate_teams) > 0

    @action(_("Continue"), name="continue", condition=hasCandidates)
    def continue_action(self, action, data):
        """Make the selected teams join this team."""
        context = self.context
        for team in data['teams']:
            team.join(context, requester=self.user)
        if context.subscriptionpolicy == TeamSubscriptionPolicy.MODERATED:
            msg = 'proposed to this team.'
        else:
            msg = 'added to this team.'
        if len(data['teams']) > 1:
            msg = "have been %s" % msg
        else:
            msg = "has been %s" % msg
        team_names = ', '.join(team.displayname for team in data['teams'])
        self.request.response.addInfoNotification("%s %s" % (team_names, msg))


class TeamLeaveView(PersonView):

    def processForm(self):
        if self.request.method != "POST" or not self.userCanRequestToLeave():
            # Nothing to do
            return

        if self.request.form.get('leave'):
            self.user.leave(self.context)

        self.request.response.redirect('./')


class PersonEditEmailsView(LaunchpadFormView):
    """A view for editing a person's email settings.

    The user can associate emails with their account, verify emails
    the system associated with their account, and remove associated
    emails.
    """

    implements(IPersonEditMenu)

    schema = IEmailAddress

    custom_widget('VALIDATED_SELECTED', LaunchpadRadioWidget,
                  orientation='vertical')
    custom_widget('UNVALIDATED_SELECTED', LaunchpadRadioWidget,
                  orientation='vertical')
    custom_widget('mailing_list_auto_subscribe_policy',
                  LaunchpadRadioWidgetWithDescription)

    def initialize(self):
        if self.context.is_team:
            # +editemails is not available on teams.
            name = self.request['PATH_INFO'].split('/')[-1]
            raise NotFound(self, name, request=self.request)
        super(PersonEditEmailsView, self).initialize()

    def setUpFields(self):
        """Set up fields for this view.

        The main fields of interest are the selection fields with custom
        vocabularies for the lists of validated and unvalidated email
        addresses.
        """
        super(PersonEditEmailsView, self).setUpFields()
        self.form_fields = (self._validated_emails_field() +
                            self._unvalidated_emails_field() +
                            FormFields(TextLine(__name__='newemail',
                                                title=u'Add a new address'))
                            + self._mailing_list_fields()
                            + self._autosubscribe_policy_fields())

    @property
    def initial_values(self):
        """Set up default values for the radio widgets.

        A radio widget must have a selected value, so we select the
        first unvalidated and validated email addresses in the lists
        to be the default for the corresponding widgets.

        The only exception is if the user has a preferred email
        address: then, that address is used as the default validated
        email address.
        """
        # Defaults for the user's email addresses.
        validated = self.context.preferredemail
        if validated is None and self.context.validatedemails.count() > 0:
            validated = self.context.validatedemails[0]
        unvalidated = self.unvalidated_addresses
        if len(unvalidated) > 0:
            unvalidated = unvalidated.pop()
        initial = dict(VALIDATED_SELECTED=validated,
                       UNVALIDATED_SELECTED=unvalidated)

        # Defaults for the mailing list autosubscribe buttons.
        policy = self.context.mailing_list_auto_subscribe_policy
        initial.update(mailing_list_auto_subscribe_policy=policy)

        return initial

    def setUpWidgets(self, context=None):
        """See `LaunchpadFormView`."""
        super(PersonEditEmailsView, self).setUpWidgets(context)
        widget = self.widgets['mailing_list_auto_subscribe_policy']
        widget.display_label = False

    def _validated_emails_field(self):
        """Create a field with a vocabulary of validated emails.

        :return: A Choice field containing the list of validated emails
        """
        terms = [SimpleTerm(term, term.email)
                 for term in self.context.validatedemails]
        preferred = self.context.preferredemail
        if preferred:
            terms.insert(0, SimpleTerm(preferred, preferred.email))

        return FormFields(
            Choice(__name__='VALIDATED_SELECTED',
                   title=_('These addresses are confirmed as being yours'),
                   source=SimpleVocabulary(terms),
                   ),
            custom_widget = self.custom_widgets['VALIDATED_SELECTED'])

    def _unvalidated_emails_field(self):
        """Create a field with a vocabulary of unvalidated and guessed emails.

        :return: A Choice field containing the list of emails
        """
        terms = []
        for term in self.unvalidated_addresses:
            if isinstance(term, unicode):
                term = SimpleTerm(term)
            else:
                term = SimpleTerm(term, term.email)
            terms.append(term)
        if self.validated_addresses:
            title = _('These addresses may also be yours')
        else:
            title = _('These addresses may be yours')

        return FormFields(
            Choice(__name__='UNVALIDATED_SELECTED', title=title,
                   source=SimpleVocabulary(terms)),
            custom_widget = self.custom_widgets['UNVALIDATED_SELECTED'])

    def _mailing_list_subscription_type(self, mailing_list):
        """Return the context user's subscription type for the given list.

        This is 'Preferred address' if the user is subscribed using her
        preferred address and 'Don't subscribe' if the user is not
        subscribed at all. Otherwise it's the EmailAddress under
        which the user is subscribed to this mailing list.
        """
        subscription = mailing_list.getSubscription(self.context)
        if subscription is not None:
            if subscription.email_address is None:
                return "Preferred address"
            else:
                return subscription.email_address
        else:
            return "Don't subscribe"

    def _mailing_list_fields(self):
        """Creates a field for each mailing list the user can subscribe to.

        If a team doesn't have a mailing list, or the mailing list
        isn't usable, it's not included.
        """
        mailing_list_set = getUtility(IMailingListSet)
        fields = []
        terms = [SimpleTerm("Preferred address"),
                 SimpleTerm("Don't subscribe")]
        terms += [SimpleTerm(email, email.email)
                   for email in self.validated_addresses]
        for team in self.context.teams_participated_in:
            mailing_list = mailing_list_set.get(team.name)
            if mailing_list is not None and mailing_list.is_usable:
                name = 'subscription.%s' % team.name
                value = self._mailing_list_subscription_type(mailing_list)
                field = Choice(__name__=name,
                               title=team.name,
                               source=SimpleVocabulary(terms), default=value)
                fields.append(field)
        return FormFields(*fields)

    def _autosubscribe_policy_fields(self):
        """Create a field for each mailing list auto-subscription option."""
        return FormFields(
            Choice(__name__='mailing_list_auto_subscribe_policy',
                   title=_('When should launchpad automatically subscribe '
                           'you to a team&#x2019;s mailing list?'),
                   source=MailingListAutoSubscribePolicy))

    @property
    def mailing_list_widgets(self):
        """Return all the mailing list subscription widgets."""
        return [widget for widget in self.widgets
                if 'field.subscription.' in widget.name]

    def _validate_selected_address(self, data, field='VALIDATED_SELECTED'):
        """A generic validator for this view's actions.

        Makes sure one (and only one) email address is selected and that
        the selected address belongs to the context person. The address may
        be represented by an EmailAddress object or (for unvalidated
        addresses) a LoginToken object.
        """
        self.validate_widgets(data, [field])

        email = data.get(field)
        if email is None:
            return None
        elif isinstance(data[field], list):
            self.addError("You must not select more than one address.")
            return None

        # Make sure the selected address or login token actually
        # belongs to this person.
        if IEmailAddress.providedBy(email):
            person = email.person

            assert person == self.context, (
                "differing ids in emailaddress.person.id(%s,%d) == "
                "self.context.id(%s,%d) (%s)"
                % (person.name, person.id, self.context.name, self.context.id,
                   email.email))
        elif isinstance(email, unicode):
            tokenset = getUtility(ILoginTokenSet)
            email = tokenset.searchByEmailRequesterAndType(
                email, self.context, LoginTokenType.VALIDATEEMAIL)
            assert email is not None, "Couldn't find login token!"
        else:
            raise AssertionError("Selected address was not EmailAddress "
                                 "or unicode string!")

        # Return the EmailAddress/LoginToken object for use in any
        # further validation.
        return email

    @property
    def validated_addresses(self):
        """All of this person's validated email addresses, including
        their preferred address (if any).
        """
        addresses = []
        if self.context.preferredemail:
            addresses.append(self.context.preferredemail)
        addresses += [email for email in self.context.validatedemails]
        return addresses

    @property
    def unvalidated_addresses(self):
        """All of this person's unvalidated and guessed emails.

        The guessed emails will be EmailAddress objects, and the
        unvalidated emails will be unicode strings.
        """
        emailset = set(self.context.unvalidatedemails)
        emailset = emailset.union(
            [guessed for guessed in self.context.guessedemails
             if not guessed.email in emailset])
        return emailset

    # Actions to do with validated email addresses.

    def validate_action_remove_validated(self, action, data):
        """Make sure the user selected an email address to remove."""
        emailaddress = self._validate_selected_address(data,
                                                       'VALIDATED_SELECTED')
        if emailaddress is None:
            return self.errors

        if self.context.preferredemail == emailaddress:
            self.addError(
                "You can't remove %s because it's your contact email "
                "address." % self.context.preferredemail.email)
            return self.errors
        return self.errors

    @action(_("Remove"), name="remove_validated",
            validator=validate_action_remove_validated)
    def action_remove_validated(self, action, data):
        """Delete the selected (validated) email address."""
        emailaddress = data['VALIDATED_SELECTED']
        emailaddress.destroySelf()
        self.request.response.addInfoNotification(
            "The email address '%s' has been removed." % emailaddress.email)
        self.next_url = self.action_url

    def validate_action_set_preferred(self, action, data):
        """Make sure the user selected an address."""
        emailaddress = self._validate_selected_address(data,
                                                       'VALIDATED_SELECTED')
        if emailaddress is None:
            return self.errors

        if emailaddress.status == EmailAddressStatus.PREFERRED:
            self.request.response.addInfoNotification(
                "%s is already set as your contact address." % (
                    emailaddress.email))
        return self.errors

    @action(_("Set as Contact Address"), name="set_preferred",
            validator=validate_action_set_preferred)
    def action_set_preferred(self, action, data):
        """Set the selected email as preferred for the person in context."""
        emailaddress = data['VALIDATED_SELECTED']
        if emailaddress.status != EmailAddressStatus.PREFERRED:
            self.context.setPreferredEmail(emailaddress)
            self.request.response.addInfoNotification(
                "Your contact address has been changed to: %s" % (
                    emailaddress.email))
        self.next_url = self.action_url

    # Actions to do with unvalidated email addresses.

    def validate_action_confirm(self, action, data):
        """Make sure the user selected an email address to confirm."""
        self._validate_selected_address(data, 'UNVALIDATED_SELECTED')
        return self.errors

    @action(_('Confirm'), name='validate', validator=validate_action_confirm)
    def action_confirm(self, action, data):
        """Mail a validation URL to the selected email address."""
        email = data['UNVALIDATED_SELECTED']
        if IEmailAddress.providedBy(email):
            email = email.email
        token = getUtility(ILoginTokenSet).new(
                    self.context, getUtility(ILaunchBag).login, email,
                    LoginTokenType.VALIDATEEMAIL)
        token.sendEmailValidationRequest(self.request.getApplicationURL())
        self.request.response.addInfoNotification(
            "An e-mail message was sent to '%s' with "
            "instructions on how to confirm that "
            "it belongs to you." % email)
        self.next_url = self.action_url

    def validate_action_remove_unvalidated(self, action, data):
        """Make sure the user selected an email address to remove."""
        email = self._validate_selected_address(data, 'UNVALIDATED_SELECTED')
        if email is not None and IEmailAddress.providedBy(email):
            assert self.context.preferredemail.id != email.id
        return self.errors

    @action(_("Remove"), name="remove_unvalidated",
            validator=validate_action_remove_unvalidated)
    def action_remove_unvalidated(self, action, data):
        """Delete the selected (un-validated) email address.

        This selected address can be either on the EmailAddress table
        marked with status NEW, or in the LoginToken table.
        """
        emailaddress = data['UNVALIDATED_SELECTED']
        if IEmailAddress.providedBy(emailaddress):
            emailaddress.destroySelf()
            email = emailaddress.email
        elif isinstance(emailaddress, unicode):
            logintokenset = getUtility(ILoginTokenSet)
            logintokenset.deleteByEmailRequesterAndType(
                emailaddress, self.context, LoginTokenType.VALIDATEEMAIL)
            email = emailaddress
        else:
            raise AssertionError("Selected address was not EmailAddress "
                                 "or Unicode string!")

        self.request.response.addInfoNotification(
            "The email address '%s' has been removed." % email)
        self.next_url = self.action_url

    # Actions to do with new email addresses

    def validate_action_add_email(self, action, data):
        """Make sure the user entered a valid email address.

        The email address must be syntactically valid and must not already
        be in use.
        """
        has_errors = bool(self.validate_widgets(data, ['newemail']))
        if has_errors:
            # We know that 'newemail' is empty.
            return self.errors

        newemail = data['newemail']
        if not valid_email(newemail):
            self.addError(
                "'%s' doesn't seem to be a valid email address." % newemail)
            return self.errors

        email = getUtility(IEmailAddressSet).getByEmail(newemail)
        person = self.context
        if email is not None:
            if email.person == person:
                self.addError(
                    "The email address '%s' is already registered as your "
                    "email address. This can be either because you already "
                    "added this email address before or because our system "
                    "detected it as being yours. If it was detected by our "
                    "system, it's probably shown on this page and is waiting "
                    "to be confirmed as yours." % newemail)
            else:
                owner = email.person
                owner_name = urllib.quote(owner.name)
                merge_url = (
                    '%s/+requestmerge?field.dupeaccount=%s'
                    % (canonical_url(getUtility(IPersonSet)), owner_name))
                self.addError(
                    structured(
                        "The email address '%s' is already registered to "
                        '<a href="%s">%s</a>. If you think that is a '
                        'duplicated account, you can <a href="%s">merge it'
                        "</a> into your account.",
                        newemail, canonical_url(owner), owner.browsername,
                        merge_url))
        return self.errors

    @action(_("Add"), name="add_email", validator=validate_action_add_email)
    def action_add_email(self, action, data):
        """Register a new email for the person in context."""
        newemail = data['newemail']
        logintokenset = getUtility(ILoginTokenSet)
        token = logintokenset.new(
                    self.context, getUtility(ILaunchBag).login, newemail,
                    LoginTokenType.VALIDATEEMAIL)
        token.sendEmailValidationRequest(self.request.getApplicationURL())

        self.request.response.addInfoNotification(
                "A confirmation message has been sent to '%s'. "
                "Follow the instructions in that message to confirm that the "
                "address is yours. "
                "(If the message doesn't arrive in a few minutes, your mail "
                "provider might use 'greylisting', which could delay the "
                "message for up to an hour or two.)" % newemail)
        self.next_url = self.action_url

    # Actions to do with subscription management.

    def validate_action_update_subscriptions(self, action, data):
        """Make sure the user is subscribing using a valid address.

        Valid addresses are the ones presented as options for the mailing
        list widgets.
        """
        names = [w.context.getName() for w in self.mailing_list_widgets]
        self.validate_widgets(data, names)
        return self.errors

    @action(_("Update Subscriptions"), name="update_subscriptions",
            validator=validate_action_update_subscriptions)
    def action_update_subscriptions(self, action, data):
        """Change the user's mailing list subscriptions."""
        mailing_list_set = getUtility(IMailingListSet)
        dirty = False
        prefix_length = len('subscription.')
        for widget in self.mailing_list_widgets:
            mailing_list_name = widget.context.getName()[prefix_length:]
            mailing_list = mailing_list_set.get(mailing_list_name)
            new_value = data[widget.context.getName()]
            old_value = self._mailing_list_subscription_type(mailing_list)
            if IEmailAddress.providedBy(new_value):
                new_value_string = new_value.email
            else:
                new_value_string = new_value
            if new_value_string != old_value:
                dirty = True
                if new_value == "Don't subscribe":
                    # Delete the subscription.
                    mailing_list.unsubscribe(self.context)
                else:
                    if new_value == "Preferred address":
                        # If the user is subscribed but not under any
                        # particular address, her current preferred
                        # address will always be used.
                        new_value = None
                    subscription = mailing_list.getSubscription(self.context)
                    if subscription is None:
                        mailing_list.subscribe(self.context, new_value)
                    else:
                        mailing_list.changeAddress(self.context, new_value)
        if dirty:
            self.request.response.addInfoNotification(
                "Subscriptions updated.")
        self.next_url = self.action_url

    def validate_action_update_autosubscribe_policy(self, action, data):
        """Ensure that the requested auto-subscribe setting is valid."""
        # XXX mars 2008-04-27 bug=223303:
        # This validator appears pointless and untestable, but it is
        # required for LaunchpadFormView to tell apart the three <form>
        # elements on the page.

        widget = self.widgets['mailing_list_auto_subscribe_policy']
        self.validate_widgets(data, widget.name)
        return self.errors

    @action(
        _('Update Policy'),
        name="update_autosubscribe_policy",
        validator=validate_action_update_autosubscribe_policy)
    def action_update_autosubscribe_policy(self, action, data):
        newpolicy = data['mailing_list_auto_subscribe_policy']
        self.context.mailing_list_auto_subscribe_policy = newpolicy
        self.request.response.addInfoNotification(
            'Your auto-subscription policy has been updated.')
        self.next_url = self.action_url


class TeamMugshotView(LaunchpadView):
    """A view for the team mugshot (team photo) page"""
    def initialize(self):
        """Cache images to avoid dying from a million cuts."""
        getUtility(IPersonSet).cacheBrandingForPeople(self.allmembers)

    @cachedproperty
    def allmembers(self):
        return list(self.context.allmembers)


class TeamReassignmentView(ObjectReassignmentView):

    ownerOrMaintainerAttr = 'teamowner'
    schema = ITeamReassignment

    def __init__(self, context, request):
        ObjectReassignmentView.__init__(self, context, request)
        self.callback = self._addOwnerAsMember

    @property
    def contextName(self):
        return self.context.browsername

    def _addOwnerAsMember(self, team, oldOwner, newOwner):
        """Add the new and the old owners as administrators of the team.

        When a user creates a new team, he is added as an administrator of
        that team. To be consistent with this, we must make the new owner an
        administrator of the team. This rule is ignored only if the new owner
        is an inactive member of the team, as that means he's not interested
        in being a member. The same applies to the old owner.
        """
        # Both new and old owners won't be added as administrators of the team
        # only if they're inactive members. If they're either active or
        # proposed members they'll be made administrators of the team.
        if newOwner not in team.inactivemembers:
            team.addMember(
                newOwner, reviewer=oldOwner,
                status=TeamMembershipStatus.ADMIN, force_team_add=True)
        if oldOwner not in team.inactivemembers:
            team.addMember(
                oldOwner, reviewer=oldOwner,
                status=TeamMembershipStatus.ADMIN, force_team_add=True)


class PersonLatestQuestionsView(LaunchpadView):
    """View used by the porlet displaying the latest questions made by
    a person.
    """

    @cachedproperty
    def getLatestQuestions(self, quantity=5):
        """Return <quantity> latest questions created for this target. """
        return self.context.searchQuestions(
            participation=QuestionParticipation.OWNER)[:quantity]


class PersonSearchQuestionsView(SearchQuestionsView):
    """View used to search and display questions in which an IPerson is
    involved.
    """

    display_target_column = True

    @property
    def pageheading(self):
        """See `SearchQuestionsView`."""
        return _('Questions involving $name',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See `SearchQuestionsView`."""
        return _('No questions  involving $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchAnsweredQuestionsView(SearchQuestionsView):
    """View used to search and display questions answered by an IPerson."""

    display_target_column = True

    def getDefaultFilter(self):
        """See `SearchQuestionsView`."""
        return dict(participation=QuestionParticipation.ANSWERER)

    @property
    def pageheading(self):
        """See `SearchQuestionsView`."""
        return _('Questions answered by $name',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See `SearchQuestionsView`."""
        return _('No questions answered by $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchAssignedQuestionsView(SearchQuestionsView):
    """View used to search and display questions assigned to an IPerson."""

    display_target_column = True

    def getDefaultFilter(self):
        """See `SearchQuestionsView`."""
        return dict(participation=QuestionParticipation.ASSIGNEE)

    @property
    def pageheading(self):
        """See `SearchQuestionsView`."""
        return _('Questions assigned to $name',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See `SearchQuestionsView`."""
        return _('No questions assigned to $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchCommentedQuestionsView(SearchQuestionsView):
    """View used to search and show questions commented on by an IPerson."""

    display_target_column = True

    def getDefaultFilter(self):
        """See `SearchQuestionsView`."""
        return dict(participation=QuestionParticipation.COMMENTER)

    @property
    def pageheading(self):
        """See `SearchQuestionsView`."""
        return _('Questions commented on by $name ',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See `SearchQuestionsView`."""
        return _('No questions commented on by $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchCreatedQuestionsView(SearchQuestionsView):
    """View used to search and display questions created by an IPerson."""

    display_target_column = True

    def getDefaultFilter(self):
        """See `SearchQuestionsView`."""
        return dict(participation=QuestionParticipation.OWNER)

    @property
    def pageheading(self):
        """See `SearchQuestionsView`."""
        return _('Questions asked by $name',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See `SearchQuestionsView`."""
        return _('No questions asked by $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class SearchNeedAttentionQuestionsView(SearchQuestionsView):
    """View used to search and show questions needing an IPerson attention."""

    display_target_column = True

    def getDefaultFilter(self):
        """See `SearchQuestionsView`."""
        return dict(needs_attention=True)

    @property
    def pageheading(self):
        """See `SearchQuestionsView`."""
        return _("Questions needing $name's attention",
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See `SearchQuestionsView`."""
        return _("No questions need $name's attention.",
                 mapping=dict(name=self.context.displayname))


class SearchSubscribedQuestionsView(SearchQuestionsView):
    """View used to search and show questions subscribed to by an IPerson."""

    display_target_column = True

    def getDefaultFilter(self):
        """See `SearchQuestionsView`."""
        return dict(participation=QuestionParticipation.SUBSCRIBER)

    @property
    def pageheading(self):
        """See `SearchQuestionsView`."""
        return _('Questions $name is subscribed to',
                 mapping=dict(name=self.context.displayname))

    @property
    def empty_listing_message(self):
        """See `SearchQuestionsView`."""
        return _('No questions subscribed to by $name found with the '
                 'requested statuses.',
                 mapping=dict(name=self.context.displayname))


class PersonAnswerContactForView(LaunchpadView):
    """View used to show all the IQuestionTargets that an IPerson is an answer
    contact for.
    """

    @cachedproperty
    def direct_question_targets(self):
        """List of targets that the IPerson is a direct answer contact.

        Return a list of IQuestionTargets sorted alphabetically by title.
        """
        return sorted(
            self.context.getDirectAnswerQuestionTargets(),
            key=attrgetter('title'))

    @cachedproperty
    def team_question_targets(self):
        """List of IQuestionTargets for the context's team membership.

        Sorted alphabetically by title.
        """
        return sorted(
            self.context.getTeamAnswerQuestionTargets(),
            key=attrgetter('title'))

    def showRemoveYourselfLink(self):
        """The link is shown when the page is in the user's own profile."""
        return self.user == self.context


class PersonAnswersMenu(ApplicationMenu):

    usedfor = IPerson
    facet = 'answers'
    links = ['answered', 'assigned', 'created', 'commented', 'need_attention',
             'subscribed', 'answer_contact_for']

    def answer_contact_for(self):
        summary = "Projects for which %s is an answer contact for" % (
            self.context.displayname)
        return Link('+answer-contact-for', 'Answer contact for', summary)

    def answered(self):
        summary = 'Questions answered by %s' % self.context.displayname
        return Link(
            '+answeredquestions', 'Answered', summary, icon='question')

    def assigned(self):
        summary = 'Questions assigned to %s' % self.context.displayname
        return Link(
            '+assignedquestions', 'Assigned', summary, icon='question')

    def created(self):
        summary = 'Questions asked by %s' % self.context.displayname
        return Link('+createdquestions', 'Asked', summary, icon='question')

    def commented(self):
        summary = 'Questions commented on by %s' % (
            self.context.displayname)
        return Link(
            '+commentedquestions', 'Commented', summary, icon='question')

    def need_attention(self):
        summary = 'Questions needing %s attention' % (
            self.context.displayname)
        return Link('+needattentionquestions', 'Need attention', summary,
                    icon='question')

    def subscribed(self):
        text = 'Subscribed'
        summary = 'Questions subscribed to by %s' % (
                self.context.displayname)
        return Link('+subscribedquestions', text, summary, icon='question')


class PersonBranchesView(BranchListingView, PersonBranchCountMixin):
    """View for branch listing for a person."""

    no_sort_by = (BranchListingSort.DEFAULT,)
    heading_template = 'Bazaar branches related to %(displayname)s'


class PersonRegisteredBranchesView(BranchListingView, PersonBranchCountMixin):
    """View for branch listing for a person's registered branches."""

    heading_template = 'Bazaar branches registered by %(displayname)s'
    no_sort_by = (BranchListingSort.DEFAULT, BranchListingSort.REGISTRANT)

    @property
    def branch_search_context(self):
        """See `BranchListingView`."""
        return BranchPersonSearchContext(
            self.context, BranchPersonSearchRestriction.REGISTERED)


class PersonOwnedBranchesView(BranchListingView, PersonBranchCountMixin):
    """View for branch listing for a person's owned branches."""

    heading_template = 'Bazaar branches owned by %(displayname)s'
    no_sort_by = (BranchListingSort.DEFAULT, BranchListingSort.REGISTRANT)

    @property
    def branch_search_context(self):
        """See `BranchListingView`."""
        return BranchPersonSearchContext(
            self.context, BranchPersonSearchRestriction.OWNED)


class SourcePackageReleaseWithStats:
    """An ISourcePackageRelease, with extra stats added."""

    implements(ISourcePackageRelease)
    delegates(ISourcePackageRelease)
    failed_builds = None
    needs_building = None

    def __init__(self, sourcepackage_release, open_bugs, open_questions,
                 failed_builds, needs_building):
        self.context = sourcepackage_release
        self.open_bugs = open_bugs
        self.open_questions = open_questions
        self.failed_builds = failed_builds
        self.needs_building = needs_building


class PersonRelatedSoftwareView(LaunchpadView):
    """View for +related-software."""
    implements(IPersonRelatedSoftwareMenu)

    SUMMARY_PAGE_PACKAGE_LIMIT = 30
    # Safety net for the Registry Admins case which is the owner/driver of
    # lots of projects.
    max_results_to_display = config.launchpad.default_batch_size

    @cachedproperty
    def related_projects(self):
        """Return a list of project dicts owned or driven by this person.

        The number of projects returned is limited by max_results_to_display.
        A project dict has the following keys: title, url, bug_count,
        spec_count, and question_count.
        """
        projects = []
        user = getUtility(ILaunchBag).user
        max_projects = self.max_results_to_display
        pillarnames = self._related_projects()[:max_projects]
        products = [pillarname.pillar for pillarname in pillarnames
                    if IProduct.providedBy(pillarname.pillar)]
        bugtask_set = getUtility(IBugTaskSet)
        product_bugtask_counts = bugtask_set.getOpenBugTasksPerProduct(
            user, products)
        for pillarname in pillarnames:
            pillar = pillarname.pillar
            project = {}
            project['title'] = pillar.title
            project['url'] = canonical_url(pillar)
            if IProduct.providedBy(pillar):
                project['bug_count'] = product_bugtask_counts.get(pillar.id,
                                                                  0)
            else:
                project['bug_count'] = pillar.open_bugtasks.count()
            project['spec_count'] = pillar.specifications().count()
            project['question_count'] = pillar.searchQuestions().count()
            projects.append(project)
        return projects

    @cachedproperty
    def first_five_related_projects(self):
        """Return first five projects owned or driven by this person."""
        return list(self._related_projects()[:5])

    @cachedproperty
    def related_projects_count(self):
        """The number of project owned or driven by this person."""
        return self._related_projects().count()

    @property
    def too_many_related_projects_found(self):
        """Does the user have more related projects than can be displayed?"""
        return self.related_projects_count > self.max_results_to_display

    def _related_projects(self):
        """Return all projects owned or driven by this person."""
        return self.context.getOwnedOrDrivenPillars()

    def _tableHeaderMessage(self, count):
        """Format a header message for the tables on the summary page."""
        if count > self.SUMMARY_PAGE_PACKAGE_LIMIT:
            packages_header_message = (
                "Displaying first %d packages out of %d total" % (
                    self.SUMMARY_PAGE_PACKAGE_LIMIT, count))
        else:
            packages_header_message = "%d package" % count
            if count > 1:
                packages_header_message += "s"

        return packages_header_message

    def filterPPAPackageList(self, packages):
        """Remove packages that the user is not allowed to see.

        Given a list of PPA packages, some might be in a PPA that the
        user is not allowed to see, so they are filtered out of the list.
        """
        # For each package we find out which archives it was published in.
        # If the user has permission to see any of those archives then
        # the user is permitted to see the package.
        #
        # Ideally this check should be done in
        # IPerson.getLatestUploadedPPAPackages() but formulating the SQL
        # query is virtually impossible!
        results = []
        for package in packages:
            # Make a shallow copy to remove the Zope security.
            archives = set(package.published_archives)
            # Ensure the SPR.upload_archive is also considered.
            archives.add(package.upload_archive)
            for archive in archives:
                if check_permission('launchpad.View', archive):
                    results.append(package)
                    break

        return results

    def _getDecoratedPackagesSummary(self, packages):
        """Helper returning decorated packages for the summary page.

        :param packages: A SelectResults that contains the query
        :return: A tuple of (packages, header_message).

        The packages returned are limited to self.SUMMARY_PAGE_PACKAGE_LIMIT
        and decorated with the stats required in the page template.
        The header_message is the text to be displayed at the top of the
        results table in the template.
        """
        # This code causes two SQL queries to be generated.
        results = self._addStatsToPackages(
            packages[:self.SUMMARY_PAGE_PACKAGE_LIMIT])
        header_message = self._tableHeaderMessage(packages.count())
        return results, header_message

    @property
    def get_latest_uploaded_ppa_packages_with_stats(self):
        """Return the sourcepackagereleases uploaded to PPAs by this person.

        Results are filtered according to the permission of the requesting
        user to see private archives.
        """
        packages = self.context.getLatestUploadedPPAPackages()
        results, header_message = self._getDecoratedPackagesSummary(packages)
        self.ppa_packages_header_message = header_message
        return self.filterPPAPackageList(results)

    @property
    def get_latest_maintained_packages_with_stats(self):
        """Return the latest maintained packages, including stats."""
        packages = self.context.getLatestMaintainedPackages()
        results, header_message = self._getDecoratedPackagesSummary(packages)
        self.maintained_packages_header_message = header_message
        return results

    @property
    def get_latest_uploaded_but_not_maintained_packages_with_stats(self):
        """Return the latest uploaded packages, including stats.

        Don't include packages that are maintained by the user.
        """
        packages = self.context.getLatestUploadedButNotMaintainedPackages()
        results, header_message = self._getDecoratedPackagesSummary(packages)
        self.uploaded_packages_header_message = header_message
        return results

    def _calculateBuildStats(self, package_releases):
        """Calculate failed builds and needs_build state.

        For each of the package_releases, calculate the failed builds
        and the needs_build state, and return a tuple of two dictionaries,
        one containing the failed builds and the other containing
        True or False according to the needs_build state, both keyed by
        the source package release.
        """
        # Calculate all the failed builds with one query.
        build_set = getUtility(IBuildSet)
        package_release_ids = [
            package_release.id for package_release in package_releases]
        all_builds = build_set.getBuildsBySourcePackageRelease(
            package_release_ids)
        # Make a dictionary of lists of builds keyed by SourcePackageRelease
        # and a dictionary of "needs build" state keyed by the same.
        builds_by_package = {}
        needs_build_by_package = {}
        for package in package_releases:
            builds_by_package[package] = []
            needs_build_by_package[package] = False
        for build in all_builds:
            if build.buildstate == BuildStatus.FAILEDTOBUILD:
                builds_by_package[build.sourcepackagerelease].append(build)
            needs_build = build.buildstate in [
                BuildStatus.NEEDSBUILD,
                BuildStatus.MANUALDEPWAIT,
                BuildStatus.CHROOTWAIT,
                ]
            needs_build_by_package[build.sourcepackagerelease] = needs_build

        return (builds_by_package, needs_build_by_package)

    def _addStatsToPackages(self, package_releases):
        """Add stats to the given package releases, and return them."""
        distro_packages = [
            package_release.distrosourcepackage
            for package_release in package_releases]
        package_bug_counts = getUtility(IBugTaskSet).getBugCountsForPackages(
            self.user, distro_packages)
        open_bugs = {}
        for bug_count in package_bug_counts:
            distro_package = bug_count['package']
            open_bugs[distro_package] = bug_count['open']

        question_set = getUtility(IQuestionSet)
        package_question_counts = question_set.getOpenQuestionCountByPackages(
            distro_packages)

        builds_by_package, needs_build_by_package = self._calculateBuildStats(
            package_releases)

        return [
            SourcePackageReleaseWithStats(
                package, open_bugs[package.distrosourcepackage],
                package_question_counts[package.distrosourcepackage],
                builds_by_package[package],
                needs_build_by_package[package])
            for package in package_releases]

    def setUpBatch(self, packages):
        """Set up the batch navigation for the page being viewed.

        This method creates the BatchNavigator and converts its
        results batch into a list of decorated sourcepackagereleases.
        """
        self.batchnav = BatchNavigator(packages, self.request)
        packages_batch = list(self.batchnav.currentBatch())
        self.batch = self._addStatsToPackages(packages_batch)


class PersonMaintainedPackagesView(PersonRelatedSoftwareView):
    """View for +maintained-packages."""

    def initialize(self):
        """Set up the batch navigation."""
        packages = self.context.getLatestMaintainedPackages()
        self.setUpBatch(packages)


class PersonUploadedPackagesView(PersonRelatedSoftwareView):
    """View for +uploaded-packages."""

    def initialize(self):
        """Set up the batch navigation."""
        packages = self.context.getLatestUploadedButNotMaintainedPackages()
        self.setUpBatch(packages)


class PersonPPAPackagesView(PersonRelatedSoftwareView):
    """View for +ppa-packages."""

    def initialize(self):
        """Set up the batch navigation."""
        # We can't use the base class's setUpBatch() here because
        # the batch needs to be filtered.  It would be nice to not have
        # to filter like this, but as the comment in filterPPAPackage() says,
        # it's very hard to write the SQL for the original query.
        packages = self.context.getLatestUploadedPPAPackages()
        self.batchnav = BatchNavigator(packages, self.request)
        packages_batch = list(self.batchnav.currentBatch())
        packages_batch = self.filterPPAPackageList(packages_batch)
        self.batch = self._addStatsToPackages(packages_batch)


class PersonRelatedProjectsView(PersonRelatedSoftwareView):
    """View for +related-projects."""

    def initialize(self):
        """Set up the batch navigation."""
        self.batchnav = BatchNavigator(
            self.related_projects, self.request)
        self.batch = list(self.batchnav.currentBatch())


class PersonSubscribedBranchesView(BranchListingView, PersonBranchCountMixin):
    """View for branch listing for a person's subscribed branches."""

    heading_template = 'Bazaar branches subscribed to by %(displayname)s'
    no_sort_by = (BranchListingSort.DEFAULT,)

    @property
    def branch_search_context(self):
        """See `BranchListingView`."""
        return BranchPersonSearchContext(
            self.context, BranchPersonSearchRestriction.SUBSCRIBED)


class PersonTeamBranchesView(LaunchpadView):
    """View for team branches portlet."""

    @cachedproperty
    def teams_with_branches(self):
        def team_has_branches(team):
            branches = getUtility(IBranchSet).getBranchesForContext(
                team, visible_by_user=self.user)
            return branches.count() > 0
        return [team for team in self.context.teams_participated_in
                if team_has_branches(team) and team != self.context]


class PersonOAuthTokensView(LaunchpadView):
    """Where users can see/revoke their non-expired access tokens."""

    def initialize(self):
        if self.request.method == 'POST':
            self.expireToken()

    @property
    def access_tokens(self):
        return sorted(
            self.context.oauth_access_tokens,
            key=lambda token: token.consumer.key)

    @property
    def request_tokens(self):
        return sorted(
            self.context.oauth_request_tokens,
            key=lambda token: token.consumer.key)

    def expireToken(self):
        """Expire the token with the key contained in the request's form."""
        form = self.request.form
        consumer = getUtility(IOAuthConsumerSet).getByKey(
            form.get('consumer_key'))
        token_key = form.get('token_key')
        token_type = form.get('token_type')
        if token_type == 'access_token':
            token = consumer.getAccessToken(token_key)
        elif token_type == 'request_token':
            token = consumer.getRequestToken(token_key)
        else:
            raise UnexpectedFormData("Invalid form value for token_type: %r"
                                     % token_type)
        if token is not None:
            token.date_expires = datetime.now(pytz.timezone('UTC'))
            self.request.response.addInfoNotification(
                "Authorization revoked successfully.")
            self.request.response.redirect(canonical_url(self.user))
        else:
            self.request.response.addInfoNotification(
                "Couldn't find authorization given to %s. Maybe it has been "
                "revoked already?" % consumer.key)


class PersonCodeSummaryView(LaunchpadView, PersonBranchCountMixin):
    """A view to render the code page summary for a person."""

    __used_for__ = IPerson

    @property
    def show_summary(self):
        """Right now we show the summary if the person has branches.

        When we add support for reviews commented on, we'll want to add
        support for showing the summary even if there are no branches.
        """
        return self.total_branch_count


class PersonActiveReviewsView(BranchMergeProposalListingView):
    """Branch merge proposals for the person that are needing review."""

    extra_columns = ['date_review_requested', 'vote_summary']
    _queue_status = [BranchMergeProposalStatus.NEEDS_REVIEW]

    @property
    def heading(self):
        return "Active code reviews for %s" % self.context.displayname

    @property
    def no_proposal_message(self):
        """Shown when there is no table to show."""
        return "%s has no active code reviews." % self.context.displayname


class PersonApprovedMergesView(BranchMergeProposalListingView):
    """Branch merge proposals that have been approved for the person."""

    extra_columns = ['date_reviewed']
    _queue_status = [BranchMergeProposalStatus.CODE_APPROVED]

    @property
    def heading(self):
        return "Approved merges for %s" % self.context.displayname

    @property
    def no_proposal_message(self):
        """Shown when there is no table to show."""
        return "%s has no approved merges." % self.context.displayname


class PersonLocationForm(Interface):

    location = LocationField(
        title=_('Use the map to indicate default location'),
        required=True)
    hide = Bool(
        title=_("Hide my location details from others."),
        required=True, default=False)


class PersonEditLocationView(LaunchpadFormView):
    """Edit a person's location."""

    schema = PersonLocationForm
    custom_widget('location', LocationWidget)

    @property
    def field_names(self):
        """See `LaunchpadFormView`.

        If the user has launchpad.Edit on this context, then allow him to set
        whether or not the location should be visible.  The field for setting
        the person's location is always shown.
        """
        if check_permission('launchpad.Edit', self.context):
            return ['location', 'hide']
        else:
            return ['location']

    @property
    def initial_values(self):
        """See `LaunchpadFormView`.

        Set the initial value for the 'hide' field.  The initial value for the
        'location' field is set by its widget.
        """
        if self.context.location is None:
            return {}
        else:
            return {'hide': not self.context.location.visible}

    def initialize(self):
        self.next_url = canonical_url(self.context)
        self.for_team_name = self.request.form.get('for_team')
        if self.for_team_name is not None:
            for_team = getUtility(IPersonSet).getByName(self.for_team_name)
            if for_team is not None:
                self.next_url = canonical_url(for_team) + '/+map'
        super(PersonEditLocationView, self).initialize()
        self.cancel_url = self.next_url

    @action(_("Update"), name="update")
    def action_update(self, action, data):
        """Set the coordinates and time zone for the person."""
        new_location = data.get('location')
        if new_location is None:
            raise UnexpectedFormData('No location received.')
        latitude = new_location.latitude
        longitude = new_location.longitude
        time_zone = new_location.time_zone
        self.context.setLocation(latitude, longitude, time_zone, self.user)
        if 'hide' in self.field_names:
            visible = not data['hide']
            self.context.setLocationVisibility(visible)


class TeamEditLocationView(LaunchpadView):
    """Redirect to the team's +map page.

    We do that because it doesn't make sense to specify the location of a
    team."""

    def initialize(self):
        self.request.response.redirect(
            canonical_url(self.context, view_name="+map"))


def archive_to_person(archive):
    """Adapts an `IArchive` to an `IPerson`."""
    return IPerson(archive.owner)


class IEmailToPerson(Interface):
    """Schema for contacting a user via email through Launchpad."""

    from_ = TextLine(
        title=_('From'), required=True, readonly=False)

    subject = TextLine(
        title=_('Subject'), required=True, readonly=False)

    message = Text(
        title=_('Message'), required=True, readonly=False)


class ContactViaWebNotificationRecipientSet:
    """A set of notification recipients and rationales from ContactViaWeb."""
    implements(INotificationRecipientSet)

    # Primary reason enumerations.
    TO_USER = object()
    TO_TEAM = object()
    TO_MEMBERS = object()
    TO_OWNER = object()

    def __init__(self, user, person_or_team):
        """Initialize the state based on the context and the user.

        The recipients are determined by the relationship between the user
        and the context that he is contacting: another user, himself, his
        team, another team.

        :param user: The person doing the contacting.
        :type user: an `IPerson`.
        :param person_or_team: The party that is the context of the email.
        :type person_or_team: `IPerson`.
        """
        self.user = user
        self.description = None
        self._primary_reason = None
        self._primary_recipient = None
        self._reason = None
        self._header = None
        self._count_recipients = None
        self.add(person_or_team, None, None)

    def _reset_state(self):
        """Reset the cache because the recipients changed."""
        self._count_recipients = None
        if safe_hasattr(self, '_all_recipients_cached'):
            # The clear the cache of _all_recipients. The caching will fail
            # if this method creates the attribute before _all_recipients.
            del self._all_recipients_cached

    def _getPrimaryReason(self, person_or_team):
        """Return the primary reason enumeration.

        :param person_or_team: The party that is the context of the email.
        :type person_or_team: `IPerson`.
        """
        if person_or_team.is_team:
            if self.user.inTeam(person_or_team):
                if removeSecurityProxy(person_or_team).preferredemail is None:
                    # Send to each team member.
                    return self.TO_MEMBERS
                else:
                    # Send to the team's contact address.
                    return self.TO_TEAM
            else:
                # A non-member can only send emails to a single person to
                # hinder spam and to prevent leaking membership
                # information for private teams when the members reply.
                return self.TO_OWNER
        else:
            # Send to the user
            return self.TO_USER

    def _getPrimaryRecipient(self, person_or_team):
        """Return the primary recipient.

        The primary recipient is the ``person_or_team`` in all cases
        except for then the email is restricted to a team owner.

        :param person_or_team: The party that is the context of the email.
        :type person_or_team: `IPerson`.
        """
        if self._primary_reason is self.TO_OWNER:
            person_or_team = person_or_team.teamowner
            while person_or_team.is_team:
                person_or_team = person_or_team.teamowner
        return person_or_team

    def _getReasonAndHeader(self, person_or_team):
        """Return the reason and header why the email was received.

        :param person_or_team: The party that is the context of the email.
        :type person_or_team: `IPerson`.
        """
        if self._primary_reason is self.TO_USER:
            reason = 'the "Contact this user" link on your profile page'
            header = 'ContactViaWeb user'
        elif self._primary_reason is self.TO_OWNER:
            reason = (
                'the "Contact this team" owner link on the '
                '%s team page' %  person_or_team.displayname)
            header = 'ContactViaWeb owner (%s team)' % person_or_team.name
        elif self._primary_reason is self.TO_TEAM:
            reason = (
                'the "Contact this team" link on the '
                '%s team page' %  person_or_team.displayname)
            header = 'ContactViaWeb member (%s team)' % person_or_team.name
        else:
            # self._primary_reason is self.TO_MEMBERS.
            reason = (
                'the "Contact this team" link on the ' '%s team page '
                'to each\nmember directly' % person_or_team.displayname)
            header = 'ContactViaWeb member (%s team)' % person_or_team.name
        return (reason, header)

    def _getDescription(self, person_or_team):
        """Return the description of the recipients being contacted.

        :param person_or_team: The party that is the context of the email.
        :type person_or_team: `IPerson`.
        """
        if self._primary_reason is self.TO_USER:
            return (
                'You are contacting %s (%s).' %
                (person_or_team.displayname, person_or_team.name))
        elif self._primary_reason is self.TO_OWNER:
            return (
                'You are contacting the %s (%s) team owner, %s (%s).' %
                (person_or_team.displayname, person_or_team.name,
                 self._primary_recipient.displayname,
                 self._primary_recipient.name))
        elif self._primary_reason is self.TO_TEAM:
            return (
                'You are contacting the %s (%s) team.' %
                (person_or_team.displayname, person_or_team.name))
        else:
            # This is a team without a contact address (self.TO_MEMBERS).
            recipients_count = len(self)
            if recipients_count == 1:
                plural_suffix = ''
            else:
                plural_suffix = 's'
            text = '%d member%s' % (recipients_count, plural_suffix)
            return (
                'You are contacting %s of the %s (%s) team directly.'
                % (text, person_or_team.displayname, person_or_team.name))

    @cachedproperty('_all_recipients_cached')
    def _all_recipients(self):
        """Set the cache of all recipients."""
        all_recipients = {}
        if self._primary_reason is self.TO_MEMBERS:
            team = self._primary_recipient
            for recipient in team.getMembersWithPreferredEmails():
                email = removeSecurityProxy(recipient).preferredemail.email
                all_recipients[email] = recipient
        elif self._primary_recipient.is_valid_person_or_team:
            email = removeSecurityProxy(
                self._primary_recipient).preferredemail.email
            all_recipients[email] = self._primary_recipient
        else:
            # The user or team owner is not active.
            pass
        return all_recipients

    def getEmails(self):
        """See `INotificationRecipientSet`."""
        for email in sorted(self._all_recipients.keys()):
            yield email

    def getRecipients(self):
        """See `INotificationRecipientSet`."""
        for recipient in sorted(
            self._all_recipients.values(), key=attrgetter('displayname')):
            yield recipient

    def getRecipientPersons(self):
        """See `INotificationRecipientSet`."""
        for email, person in self._all_recipients.items():
            yield (email, person)

    def __iter__(self):
        """See `INotificationRecipientSet`."""
        return iter(self.getRecipients())

    def __contains__(self, person_or_email):
        """See `INotificationRecipientSet`."""
        if IPerson.implementedBy(person_or_email):
            return person_or_email in self._all_recipients.values()
        else:
            return person_or_email in self._all_recipients.keys()

    def __len__(self):
        """The number of recipients in the set."""
        if self._count_recipients is None:
            recipient = self._primary_recipient
            if self._primary_reason is self.TO_MEMBERS:
                self._count_recipients = (
                    recipient.getMembersWithPreferredEmailsCount())
            elif recipient.is_valid_person_or_team:
                self._count_recipients = 1
            else:
                # The user or team owner is deactivated.
                self._count_recipients = 0
        return self._count_recipients

    def __nonzero__(self):
        """See `INotificationRecipientSet`."""
        return len(self) > 0

    def getReason(self, person_or_email):
        """See `INotificationRecipientSet`."""
        if person_or_email not in self:
            raise UnknownRecipientError(
                '%s in not in the recipients' % person_or_email)
        # All users have the same reason based on the primary recipient.
        return (self._reason, self._header)

    def add(self, person, reason, header):
        """See `INotificationRecipientSet`.

        This method sets the primary recipient of the email. If the primary
        recipient is a team without a contact address, all the members will
        be recipients. Calling this method more than once resets the
        recipients.
        """
        self._reset_state()
        self._primary_reason = self._getPrimaryReason(person)
        self._primary_recipient = self._getPrimaryRecipient(person)
        if reason is None:
            reason, header = self._getReasonAndHeader(person)
        self._reason = reason
        self._header = header
        self.description = self._getDescription(person)

    def update(self, recipient_set):
        """See `INotificationRecipientSet`.

        This method is is not relevant to this implementation because the
        set is generated based on the primary recipient. use the add() to
        set the primary recipient.
        """
        pass


class EmailToPersonView(LaunchpadFormView):
    """The 'Contact this user' page."""

    schema = IEmailToPerson
    field_names = ['subject', 'message']
    custom_widget('subject', TextWidget, displayWidth=60)

    def initialize(self):
        """See `ILaunchpadFormView`."""
        # Send the user to the profile page if contact is not possible.
        if self.user is None or not self.context.is_valid_person_or_team:
            return self.request.response.redirect(canonical_url(self.context))
        LaunchpadFormView.initialize(self)

    def setUpFields(self):
        """Set up fields for this view.

        The field needing special set up is the 'From' fields, which contains
        a vocabulary of the user's preferred (first) and validated
        (subsequent) email addresses.
        """
        super(EmailToPersonView, self).setUpFields()
        usable_addresses = [self.user.preferredemail]
        usable_addresses.extend(self.user.validatedemails)
        terms = [SimpleTerm(email, email.email) for email in usable_addresses]
        field = Choice(__name__='field.from_',
                       title=_('From'),
                       source=SimpleVocabulary(terms),
                       default=terms[0].value)
        # Get the order right; the From field should be first, followed by the
        # Subject and then Message fields.
        self.form_fields = FormFields(*chain((field,), self.form_fields))

    @property
    def label(self):
        """The form label."""
        return 'Contact ' + self.context.displayname

    @cachedproperty
    def recipients(self):
        """The recipients of the email message.

        :return: the recipients of the message.
        :rtype: `ContactViaWebNotificationRecipientSet`.
        """
        return ContactViaWebNotificationRecipientSet(self.user, self.context)

    @action(_('Send'), name='send')
    def action_send(self, action, data):
        """Send an email to the user."""
        sender_email = data['field.from_'].email
        subject = data['subject']
        message = data['message']

        if not self.recipients:
            self.request.response.addErrorNotification(
                _('Your message was not sent because the recipient '
                  'does not have a preferred email address.'))
            self.next_url = canonical_url(self.context)
            return
        try:
            send_direct_contact_email(
                sender_email, self.recipients, subject, message)
        except QuotaReachedError, error:
            fmt_date = DateTimeFormatterAPI(self.next_try)
            self.request.response.addErrorNotification(
                _('Your message was not sent because you have exceeded your '
                  'daily quota of $quota messages to contact users. '
                  'Try again $when.', mapping=dict(
                      quota=error.authorization.message_quota,
                      when=fmt_date.approximatedate(),
                      )))
        else:
            self.request.response.addInfoNotification(
                _('Message sent to $name',
                  mapping=dict(name=self.context.displayname)))
        self.next_url = canonical_url(self.context)

    @property
    def cancel_url(self):
        """The return URL."""
        return canonical_url(self.context)

    @property
    def contact_is_allowed(self):
        """Whether the sender is allowed to send this email or not."""
        return IDirectEmailAuthorization(self.user).is_allowed

    @property
    def has_valid_email_address(self):
        """Whether there is a contact address."""
        return len(self.recipients) > 0

    @property
    def contact_is_possible(self):
        """Whether there is a contact address and the user can send email."""
        return self.contact_is_allowed and self.has_valid_email_address

    @property
    def next_try(self):
        """When can the user try again?"""
        throttle_date = IDirectEmailAuthorization(self.user).throttle_date
        interval = as_timedelta(
            config.launchpad.user_to_user_throttle_interval)
        return throttle_date + interval

    @property
    def specific_contact_title_text(self):
        """Return the appropriate pagetitle."""
        if self.context.is_team:
            if self.user.inTeam(self.context):
                return 'Contact your team'
            else:
                return 'Contact this team'
        elif self.context == self.user:
            return 'Contact yourself'
        else:
            return 'Contact this user'
