# Copyright 2004 Canonical Ltd

__metaclass__ = type

__all__ = [
    'ProposedTeamMembersEditView',
    'TeamAddView',
    'TeamBrandingView',
    'TeamContactAddressView',
    'TeamEditView',
    'TeamMemberAddView',
    ]

from zope.event import notify
from zope.app.event.objectevent import ObjectCreatedEvent
from zope.app.form.browser import TextAreaWidget
from zope.component import getUtility
from zope.formlib import form
from zope.schema import Choice

from canonical.database.sqlbase import flush_database_updates
from canonical.widgets import (
    HiddenUserWidget, LaunchpadRadioWidget, SinglePopupWidget)

from canonical.config import config
from canonical.launchpad import _
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.webapp import (
    action, canonical_url, custom_widget, LaunchpadEditFormView,
    LaunchpadFormView)
from canonical.launchpad.browser.branding import BrandingChangeView
from canonical.launchpad.interfaces import (
    IEmailAddressSet, ILaunchBag, ILoginTokenSet, IMailingListSet, IPersonSet,
    ITeamContactAddressForm, ITeamCreation, ITeamMember, ITeam,
    LoginTokenType, MailingListStatus, TeamContactMethod, TeamMembershipStatus,
    UnexpectedFormData)
from canonical.launchpad.interfaces.validation import validate_new_team_email


class HasRenewalPolicyMixin:
    """Mixin to be used on forms which contain ITeam.renewal_policy.

    This mixin will short-circuit Launchpad*FormView when defining whether
    the renewal_policy widget should be displayed in a single or multi-line
    layout. We need that because that field has a very long title, thus
    breaking the page layout.

    Since this mixin short-circuits Launchpad*FormView in some cases, it must
    always precede Launchpad*FormView in the inheritance list.
    """

    def isMultiLineLayout(self, field_name):
        if field_name == 'renewal_policy':
            return True
        return super(HasRenewalPolicyMixin, self).isMultiLineLayout(
            field_name)

    def isSingleLineLayout(self, field_name):
        if field_name == 'renewal_policy':
            return False
        return super(HasRenewalPolicyMixin, self).isSingleLineLayout(
            field_name)


class TeamEditView(HasRenewalPolicyMixin, LaunchpadEditFormView):

    schema = ITeam
    field_names = [
        'teamowner', 'name', 'displayname', 'teamdescription',
        'subscriptionpolicy', 'defaultmembershipperiod',
        'renewal_policy', 'defaultrenewalperiod']
    custom_widget('teamowner', SinglePopupWidget, visible=False)
    custom_widget(
        'renewal_policy', LaunchpadRadioWidget, orientation='vertical')
    custom_widget(
        'subscriptionpolicy', LaunchpadRadioWidget, orientation='vertical')

    @action('Save', name='save')
    def action_save(self, action, data):
        self.updateContextFromData(data)
        self.next_url = canonical_url(self.context)


def generateTokenAndValidationEmail(email, team):
    """Send a validation message to the given email."""
    login = getUtility(ILaunchBag).login
    token = getUtility(ILoginTokenSet).new(
        team, login, email, LoginTokenType.VALIDATETEAMEMAIL)

    user = getUtility(ILaunchBag).user
    token.sendTeamEmailAddressValidationEmail(user)


class TeamContactAddressView(LaunchpadFormView):

    schema = ITeamContactAddressForm
    label = "Contact address"
    custom_widget(
        'contact_method', LaunchpadRadioWidget, orientation='vertical')

    def getListInState(self, *statuses):
        """Return this team's mailing list if it's in one of the given states.

        :param statuses: The states that the mailing list must be in for it to
            be returned.
        :return: This team's IMailingList or None if the team doesn't have
            a mailing list, or if it isn't in one of the given states.
        """
        mailing_list = getUtility(IMailingListSet).get(self.context.name)
        if mailing_list is not None and mailing_list.status in statuses:
            return mailing_list
        return None

    def shouldRenderHostedListOptionManually(self):
        """Should the HOSTED_LIST option be rendered manually?

        It's rendered manually only if mailman.expose_hosted_mailing_lists
        is False and this team doesn't have an active mailing list yet. In
        this case we'll render it as a disabled radio button with a submit
        button which allows the user to request the mailing list creation.

        If expose_hosted_mailing_lists is True and the team has an active
        mailing list, then the option will be rendered by zope3 as an
        enabled radio button, which means we don't need to do anything.
        """
        if not config.mailman.expose_hosted_mailing_lists:
            return False
        if self.getListInState(MailingListStatus.ACTIVE) is None:
            return True
        return False

    @property
    def mailing_list_status_message(self):
        mailing_list = getUtility(IMailingListSet).get(self.context.name)
        if mailing_list is None:
            return ("Not available because you haven't applied for a "
                    "mailing list.")

        msg = "Not available because "
        if mailing_list.status in [MailingListStatus.APPROVED,
                                   MailingListStatus.CONSTRUCTING]:
            msg += "mailing list is being constructed."
        elif mailing_list.status == MailingListStatus.REGISTERED:
            msg += ("the application for a mailing list is pending "
                    "approval.")
        elif mailing_list.status == MailingListStatus.DECLINED:
            msg += "the application for a mailing list has been declined."
        elif mailing_list.status in [MailingListStatus.INACTIVE,
                                     MailingListStatus.DEACTIVATING]:
            msg += "mailing list is currently deactivated."
        elif mailing_list.status == MailingListStatus.FAILED:
            msg += "mailing list creation failed."
        elif mailing_list.status in [MailingListStatus.MODIFIED,
                                     MailingListStatus.UPDATING]:
            msg += "mailing list is undergoing some maintenance."
        elif mailing_list.status == MailingListStatus.ACTIVE:
            # Mailing list is active and the option will be enabled; there's
            # no need to display a status message.
            msg = ''
        else:
            raise AssertionError(
                "Unknown mailing list status: %s" % mailing_list.status)
        return msg

    @property
    def list_application_can_be_cancelled(self):
        return self.getListInState(MailingListStatus.REGISTERED) is not None

    @property
    def list_can_be_requested(self):
        mailing_list = getUtility(IMailingListSet).get(self.context.name)
        return (mailing_list is None
                or mailing_list.status == MailingListStatus.INACTIVE)

    @property
    def mailinglist_address(self):
        return '%s@lists.launchpad.net' % self.context.name

    def setUpWidgets(self, context=None):
        """Check if the HOSTED_LIST option of our contact_method widget
        should be rendered by zope3, manually (by ourselves) in the
        template or not rendered at all and change the vocabulary
        accordingly.
        """
        vocab_items = TeamContactMethod.items.items[:]
        if (not config.mailman.expose_hosted_mailing_lists
            or self.shouldRenderHostedListOptionManually()):
            # Either we'll render the HOSTED_LIST option manually or not
            # render it at all, so remove it from vocab_items.
            vocab_items.remove(TeamContactMethod.HOSTED_LIST)
        else:
            # The HOSTED_LIST option will be rendered normally by zope3, so
            # we just need to change its title to include the actual email
            # address of the mailing list.
            index = vocab_items.index(TeamContactMethod.HOSTED_LIST)
            item = vocab_items.pop(index)
            item.title = ('The Launchpad mailing list for this team - '
                          '<strong>%s</strong>' % self.mailinglist_address)
            vocab_items.insert(index, item)
        contact_method = form.FormField(
            Choice(__name__='contact_method',
                   title=_("How do people contact these team's members?"),
                   required=True, values=vocab_items),
            custom_widget=self.custom_widgets['contact_method'])
        self.form_fields = form.Fields(
            contact_method, self.form_fields['contact_address'])
        super(TeamContactAddressView, self).setUpWidgets(context=context)

    def validate(self, data):
        """Validate the email address only if the user wants to use an external
        address and the given email address is not already in use by this team.

        Also ensures the mailing list is active if the HOSTED_LIST option
        has been chosen.
        """
        if data['contact_method'] == TeamContactMethod.EXTERNAL_ADDRESS:
            email = data['contact_address']
            if not email:
                self.setFieldError(
                    'contact_address',
                    'Enter the contact address you want to use for this team.')
                return
            email = getUtility(IEmailAddressSet).getByEmail(
                data['contact_address'])
            if email is None or email.person != self.context:
                try:
                    validate_new_team_email(data['contact_address'])
                except LaunchpadValidationError, error:
                    self.setFieldError('contact_address', str(error))
        elif data['contact_method'] == TeamContactMethod.HOSTED_LIST:
            mailing_list = getUtility(IMailingListSet).get(self.context.name)
            if (mailing_list is None
                or mailing_list.status != MailingListStatus.ACTIVE):
                self.addError(
                    "This team's mailing list is not active and may not be "
                    "used as its contact address yet")
        else:
            # Nothing to validate!
            pass

    def request_list_creation_validator(self, action, data):
        if self.getListInState(MailingListStatus.DECLINED,
                               MailingListStatus.INACTIVE):
            self.addError(
                "There is an application for a mailing list already.")

    def cancel_list_creation_validator(self, action, data):
        mailing_list = getUtility(IMailingListSet).get(self.context.name)
        if (mailing_list is None
            or mailing_list.status != MailingListStatus.REGISTERED):
            self.addError("This application can't be cancelled.")

    @property
    def initial_values(self):
        """Infer the contact method from this team's preferredemail and
        return a dict representing that in terms of the fields we use here.
        """
        context = self.context
        if context.preferredemail is None:
            return dict(contact_method=TeamContactMethod.NONE)
        mailing_list = getUtility(IMailingListSet).get(context.name)
        if (mailing_list is not None 
            and mailing_list.address == context.preferredemail.email):
            return dict(contact_method=TeamContactMethod.HOSTED_LIST)
        return dict(contact_address=context.preferredemail.email,
                    contact_method=TeamContactMethod.EXTERNAL_ADDRESS)

    @action('Cancel Application', name='cancel_list_creation',
            validator=cancel_list_creation_validator)
    def cancel_list_creation(self, action, data):
        getUtility(IMailingListSet).get(self.context.name).cancelRegistration()
        self.request.response.addInfoNotification(
            "Mailing list application cancelled.")
        self.next_url = canonical_url(self.context)

    @action('Apply for Mailing List', name='request_list',
            validator=request_list_creation_validator)
    def request_list_creation(self, action, data):
        list_set = getUtility(IMailingListSet)
        mailing_list = list_set.get(self.context.name)
        if mailing_list is None:
            list_set.new(self.context)
            self.request.response.addInfoNotification(
                "Mailing list requested and queued for approval.")
        else:
            mailing_list.reactivate()
            self.request.response.addInfoNotification(
                "This team's Launchpad mailing list is currently "
                "inactive and will be reactivated shortly.")
        self.next_url = canonical_url(self.context)

    @action('Change', name='change')
    def change_action(self, action, data):
        context = self.context
        email_set = getUtility(IEmailAddressSet)
        list_set = getUtility(IMailingListSet)
        contact_method = data['contact_method']
        if contact_method == TeamContactMethod.NONE:
            if context.preferredemail is not None:
                context.preferredemail.destroySelf()
        elif contact_method == TeamContactMethod.HOSTED_LIST:
            mailing_list = list_set.get(context.name)
            assert (mailing_list is not None 
                    and mailing_list.status == MailingListStatus.ACTIVE), (
                "A team can only use an active mailing list as its contact "
                "address.")
            context.setContactAddress(
                email_set.getByEmail(mailing_list.address))
        elif contact_method == TeamContactMethod.EXTERNAL_ADDRESS:
            contact_address = data['contact_address']
            email = email_set.getByEmail(contact_address)
            if email is None:
                generateTokenAndValidationEmail(contact_address, context)
                self.request.response.addInfoNotification(
                    "A confirmation message has been sent to '%s'. Follow "
                    "the instructions in that message to confirm the new "
                    "contact address for this team. (If the message "
                    "doesn't arrive in a few minutes, your mail provider "
                    "might use 'greylisting', which could delay the "
                    "message for up to an hour or two.)" % contact_address)
            else:
                context.setContactAddress(email)
        else:
            raise UnexpectedFormData(
                "Unknown contact_method: %s" % contact_method)

        self.next_url = canonical_url(self.context)


class TeamAddView(HasRenewalPolicyMixin, LaunchpadFormView):

    schema = ITeamCreation
    label = ''
    field_names = ["name", "displayname", "contactemail", "teamdescription",
                   "subscriptionpolicy", "defaultmembershipperiod",
                   "renewal_policy", "defaultrenewalperiod", "teamowner"]
    custom_widget('teamowner', HiddenUserWidget)
    custom_widget('teamdescription', TextAreaWidget, height=10, width=30)
    custom_widget(
        'renewal_policy', LaunchpadRadioWidget, orientation='vertical')
    custom_widget(
        'subscriptionpolicy', LaunchpadRadioWidget, orientation='vertical')

    @action('Create', name='create')
    def create_action(self, action, data):
        name = data.get('name')
        displayname = data.get('displayname')
        teamdescription = data.get('teamdescription')
        defaultmembershipperiod = data.get('defaultmembershipperiod')
        defaultrenewalperiod = data.get('defaultrenewalperiod')
        subscriptionpolicy = data.get('subscriptionpolicy')
        teamowner = data.get('teamowner')
        team = getUtility(IPersonSet).newTeam(
            teamowner, name, displayname, teamdescription,
            subscriptionpolicy, defaultmembershipperiod, defaultrenewalperiod)
        notify(ObjectCreatedEvent(team))

        email = data.get('contactemail')
        if email is not None:
            generateTokenAndValidationEmail(email, team)
            self.request.response.addNotification(
                "A confirmation message has been sent to '%s'. Follow the "
                "instructions in that message to confirm the new "
                "contact address for this team. "
                "(If the message doesn't arrive in a few minutes, your mail "
                "provider might use 'greylisting', which could delay the "
                "message for up to an hour or two.)" % email)

        self.next_url = canonical_url(team)


class ProposedTeamMembersEditView:

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.user = getUtility(ILaunchBag).user

    def processProposed(self):
        if self.request.method != "POST":
            return

        team = self.context
        expires = team.defaultexpirationdate
        for person in team.proposedmembers:
            action = self.request.form.get('action_%d' % person.id)
            if action == "approve":
                status = TeamMembershipStatus.APPROVED
            elif action == "decline":
                status = TeamMembershipStatus.DECLINED
            elif action == "hold":
                continue

            team.setMembershipData(
                person, status, reviewer=self.user, expires=expires)

        # Need to flush all changes we made, so subsequent queries we make
        # with this transaction will see this changes and thus they'll be
        # displayed on the page that calls this method.
        flush_database_updates()
        self.request.response.redirect('%s/+members' % canonical_url(team))


class TeamBrandingView(BrandingChangeView):

    schema = ITeam
    field_names = ['icon', 'logo', 'mugshot']


class TeamMemberAddView(LaunchpadFormView):

    schema = ITeamMember
    label = "Select the new member"

    def validate(self, data):
        """Verify new member.

        This checks that the new member has some active members and is not
        already an active team member.
        """
        newmember = data.get('newmember')
        error = None
        if newmember is not None:
            if newmember.isTeam() and not newmember.activemembers:
                error = _("You can't add a team that doesn't have any active"
                          " members.")
            elif newmember in self.context.activemembers:
                error = _("%s (%s) is already a member of %s." % (
                    newmember.browsername, newmember.name,
                    self.context.browsername))

        if error:
            self.setFieldError("newmember", error)

    @action(u"Add Member", name="add")
    def add_action(self, action, data):
        """Add the new member to the team."""
        newmember = data['newmember']
        # If we get to this point with the member being the team itself,
        # it means the ValidTeamMemberVocabulary is broken.
        assert newmember != self.context, (
            "Can't add team to itself: %s" % newmember)

        self.context.addMember(newmember, reviewer=self.user,
                               status=TeamMembershipStatus.APPROVED)
        if newmember.isTeam():
            msg = "%s has been invited to join this team." % (
                  newmember.unique_displayname)
        else:
            msg = "%s has been added as a member of this team." % (
                  newmember.unique_displayname)
        self.request.response.addInfoNotification(msg)

