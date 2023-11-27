# Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Git reference views."""

__all__ = [
    "GitRefContextMenu",
    "GitRefRegisterMergeProposalView",
    "GitRefView",
]

import json
from urllib.parse import quote_plus, urlsplit, urlunsplit

from breezy import urlutils
from lazr.restful.interface import copy_field
from zope.component import getUtility
from zope.formlib.widget import CustomWidgetFactory
from zope.formlib.widgets import TextAreaWidget
from zope.interface import Interface
from zope.publisher.interfaces import NotFound
from zope.schema import Bool, Text

from lp import _
from lp.app.browser.launchpadform import LaunchpadFormView, action
from lp.charms.browser.hascharmrecipes import (
    HasCharmRecipesMenuMixin,
    HasCharmRecipesViewMixin,
)
from lp.code.browser.branchmergeproposal import (
    latest_proposals_for_each_branch,
)
from lp.code.browser.revisionstatus import HasRevisionStatusReportsMixin
from lp.code.browser.sourcepackagerecipelisting import HasRecipesMenuMixin
from lp.code.browser.widgets.gitref import GitRefWidget
from lp.code.enums import GitRepositoryType
from lp.code.errors import GitRepositoryScanFault, InvalidBranchMergeProposal
from lp.code.interfaces.branchmergeproposal import IBranchMergeProposal
from lp.code.interfaces.codereviewvote import ICodeReviewVoteReference
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import (
    ContributorGitIdentity,
    IGitRepositorySet,
)
from lp.registry.interfaces.person import IPerson
from lp.services.config import config
from lp.services.helpers import english_list
from lp.services.propertycache import cachedproperty
from lp.services.scripts import log
from lp.services.webapp import ContextMenu, LaunchpadView, Link, canonical_url
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.escaping import structured
from lp.snappy.browser.hassnaps import HasSnapsMenuMixin, HasSnapsViewMixin


class GitRefContextMenu(
    ContextMenu,
    HasRecipesMenuMixin,
    HasSnapsMenuMixin,
    HasCharmRecipesMenuMixin,
):
    """Context menu for Git references."""

    usedfor = IGitRef
    facet = "branches"
    links = [
        "browse_commits",
        "create_charm_recipe",
        "create_recipe",
        "create_snap",
        "register_merge",
        "source",
        "view_charm_recipes",
        "view_recipes",
    ]

    def source(self):
        """Return a link to the branch's browsing interface."""
        text = "Browse the code"
        url = self.context.getCodebrowseUrl()
        return Link(url, text, icon="info")

    def browse_commits(self):
        """Return a link to the branch's commit log."""
        text = "All commits"
        url = "%s/log/?h=%s" % (
            self.context.repository.getCodebrowseUrl(),
            quote_plus(self.context.name.encode("UTF-8")),
        )
        return Link(url, text)

    def register_merge(self):
        text = "Propose for merging"
        enabled = self.context.namespace.supports_merge_proposals
        return Link("+register-merge", text, icon="add", enabled=enabled)

    def create_recipe(self):
        # You can't create a recipe for a reference in a private repository.
        enabled = not self.context.private
        text = "Create packaging recipe"
        return Link("+new-recipe", text, enabled=enabled, icon="add")


class GitRefView(
    LaunchpadView,
    HasSnapsViewMixin,
    HasCharmRecipesViewMixin,
    HasRevisionStatusReportsMixin,
):
    # This is set at self.commit_infos, and should be accessed by the view
    # as self.commit_info_message.
    _commit_info_message = None

    @property
    def label(self):
        return self.context.display_name

    @property
    def git_ssh_url(self):
        """The git+ssh:// URL for this branch, adjusted for this user."""
        base_url = urlsplit(self.context.repository.git_ssh_url)
        url = list(base_url)
        url[1] = f"{self.user.name}@{base_url.hostname}"
        return urlunsplit(url)

    @property
    def git_ssh_url_non_owner(self):
        """The git+ssh:// URL for this repository, adjusted for this user.

        The user is not the owner of the repository.
        """
        contributor = ContributorGitIdentity(
            owner=self.user,
            target=self.context.repository.target,
            repository=self.context.repository,
        )
        base_url = urlutils.join(
            config.codehosting.git_ssh_root, contributor.shortened_path
        )
        url = list(urlsplit(base_url))
        url[1] = f"{self.user.name}@{url[1]}"
        return urlunsplit(url)

    @property
    def user_can_push(self):
        """Whether the user can push to this branch."""
        return (
            self.context.repository.repository_type == GitRepositoryType.HOSTED
            and check_permission("launchpad.Edit", self.context)
        )

    @property
    def show_merge_links(self):
        """Return whether or not merge proposal links should be shown.

        Merge proposal links should not be shown if there is only one
        reference in the entire target.
        """
        if not self.context.namespace.supports_merge_proposals:
            return False
        if IPerson.providedBy(self.context.namespace.target):
            # XXX pappacena 2020-07-21: For personal repositories, we enable
            # the link even if the user will only be allowed to merge
            # their personal repositories' branch into another personal repo
            # with the same name. But checking if there is another
            # repository with the same name might be a bit expensive query for
            # such a simple operation. Currently, we only have db index for
            # repo's name when searching together with owner.
            return True

        repositories = self.context.namespace.collection.getRepositories()
        if repositories.count() > 1:
            return True
        repository = repositories.one()
        if repository is None:
            return False
        return repository.refs.count() > 1

    @property
    def propose_merge_notes(self):
        messages = []
        if IPerson.providedBy(self.context.namespace.target):
            messages.append(
                "You will only be able to propose a merge to another personal "
                "repository with the same name."
            )
        return messages

    @cachedproperty
    def landing_targets(self):
        """Return a filtered list of landing targets."""
        targets = self.context.getPrecachedLandingTargets(self.user)
        return latest_proposals_for_each_branch(targets)

    @cachedproperty
    def landing_candidates(self):
        """Return a decorated list of landing candidates."""
        candidates = self.context.getPrecachedLandingCandidates(self.user)
        return [
            proposal
            for proposal in candidates
            if check_permission("launchpad.View", proposal)
        ]

    def _getBranchCountText(self, count):
        """Help to show user friendly text."""
        if count == 0:
            return "No branches"
        elif count == 1:
            return "1 branch"
        else:
            return "%s branches" % count

    @cachedproperty
    def landing_candidate_count_text(self):
        return self._getBranchCountText(len(self.landing_candidates))

    @cachedproperty
    def dependent_landings(self):
        return [
            proposal
            for proposal in self.context.dependent_landings
            if check_permission("launchpad.View", proposal)
        ]

    @cachedproperty
    def dependent_landing_count_text(self):
        return self._getBranchCountText(len(self.dependent_landings))

    @cachedproperty
    def commit_infos(self):
        try:
            self._commit_info_message = ""
            return self.context.getLatestCommits(
                extended_details=True,
                user=self.user,
                handle_timeout=True,
                logger=log,
            )
        except GitRepositoryScanFault as e:
            log.error("There was an error fetching git commit info: %s" % e)
            self._commit_info_message = (
                "There was an error while fetching commit information from "
                "code hosting service. Please try again in a few minutes. "
                'If the problem persists, <a href="/launchpad/+addquestion">'
                "contact Launchpad support</a>."
            )
            return []
        except Exception as e:
            log.error(
                "There was an error scanning %s: (%s) %s"
                % (self.context, e.__class__, e)
            )
            raise

    def commit_infos_message(self):
        if self._commit_info_message is None:
            # Evaluating self.commit infos so it updates
            # self._commit_info_message.
            self.commit_infos
        return self._commit_info_message

    @property
    def recipes_link(self):
        """A link to recipes for this reference."""
        count = self.context.recipes.count()
        if count == 0:
            # Nothing to link to.
            return "No recipes using this branch."
        elif count == 1:
            # Link to the single recipe.
            return structured(
                '<a href="%s">1 recipe</a> using this branch.',
                canonical_url(self.context.recipes.one()),
            ).escapedtext
        else:
            # Link to a recipe listing.
            return structured(
                '<a href="+recipes">%s recipes</a> using this branch.', count
            ).escapedtext


class GitRefRegisterMergeProposalSchema(Interface):
    """The schema to define the form for registering a new merge proposal."""

    target_git_ref = copy_field(
        IBranchMergeProposal["target_git_ref"], required=True
    )

    prerequisite_git_ref = copy_field(
        IBranchMergeProposal["prerequisite_git_ref"],
        required=False,
        description=_(
            "If the source branch is based on a different branch, "
            "you can add this as a prerequisite. "
            "The changes from that branch will not show "
            "in the diff."
        ),
    )

    comment = Text(
        title=_("Description of the change"),
        required=False,
        description=_(
            "Describe what changes your branch introduces, "
            "what bugs it fixes, or what features it implements. "
            "Ideally include rationale and how to test. "
            "You do not need to repeat information from the commit "
            "message here."
        ),
    )

    reviewer = copy_field(ICodeReviewVoteReference["reviewer"], required=False)

    review_type = copy_field(
        ICodeReviewVoteReference["review_type"],
        description="Lowercase keywords describing the type of review you "
        "would like to be performed.",
    )

    commit_message = IBranchMergeProposal["commit_message"]

    needs_review = Bool(
        title=_("Needs review"),
        required=True,
        default=True,
        description=_("Is the proposal ready for review now?"),
    )


class GitRefRegisterMergeProposalView(LaunchpadFormView):
    """The view to register new Git merge proposals."""

    schema = GitRefRegisterMergeProposalSchema
    next_url = None
    for_input = True

    custom_widget_target_git_ref = CustomWidgetFactory(
        GitRefWidget, require_branch=True
    )
    custom_widget_prerequisite_git_ref = CustomWidgetFactory(
        GitRefWidget, require_branch=True
    )
    custom_widget_commit_message = CustomWidgetFactory(
        TextAreaWidget, cssClass="comment-text"
    )
    custom_widget_comment = CustomWidgetFactory(
        TextAreaWidget, cssClass="comment-text"
    )

    page_title = label = "Propose for merging"

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    def initialize(self):
        """Show a 404 if the repository namespace doesn't support proposals."""
        if not self.context.namespace.supports_merge_proposals:
            raise NotFound(self.context, "+register-merge")
        super().initialize()

    def setUpWidgets(self, context=None):
        super().setUpWidgets(context=context)

        if not self.widgets["target_git_ref"].hasInput():
            if self.context.repository.namespace.has_defaults:
                repo_set = getUtility(IGitRepositorySet)
                default_repo = repo_set.getDefaultRepository(
                    self.context.repository.target
                )
            else:
                default_repo = None
            if not default_repo:
                default_repo = self.context.repository
            if default_repo.default_branch:
                default_ref = default_repo.getRefByPath(
                    default_repo.default_branch
                )
                with_path = True
            else:
                default_ref = self.context
                with_path = False
            self.widgets["target_git_ref"].setRenderedValue(
                default_ref, with_path=with_path
            )

    @action(
        "Propose Merge",
        name="register",
        failure=LaunchpadFormView.ajax_failure_handler,
    )
    def register_action(self, action, data):
        """Register the new merge proposal."""

        registrant = self.user
        source_ref = self.context
        target_ref = data["target_git_ref"]
        prerequisite_ref = data.get("prerequisite_git_ref")

        review_requests = []
        reviewer = data.get("reviewer")
        review_type = data.get("review_type")
        if reviewer is None:
            reviewer = target_ref.code_reviewer
        if reviewer is not None:
            review_requests.append((reviewer, review_type))

        repository_names = [
            ref.repository.unique_name for ref in (source_ref, target_ref)
        ]
        repository_set = getUtility(IGitRepositorySet)
        visibility_info = repository_set.getRepositoryVisibilityInfo(
            self.user, reviewer, repository_names
        )
        visible_repositories = list(visibility_info["visible_repositories"])
        if self.request.is_ajax and len(visible_repositories) < 2:
            self.request.response.setStatus(400, "Repository Visibility")
            self.request.response.setHeader("Content-Type", "application/json")
            return json.dumps(
                {
                    "person_name": visibility_info["person_name"],
                    "repositories_to_check": repository_names,
                    "visible_repositories": visible_repositories,
                }
            )

        try:
            proposal = source_ref.addLandingTarget(
                registrant=registrant,
                merge_target=target_ref,
                merge_prerequisite=prerequisite_ref,
                needs_review=data["needs_review"],
                description=data.get("comment"),
                review_requests=review_requests,
                commit_message=data.get("commit_message"),
            )
            if len(visible_repositories) < 2:
                invisible_repositories = [
                    ref.repository.unique_name
                    for ref in (source_ref, target_ref)
                    if ref.repository.unique_name not in visible_repositories
                ]
                self.request.response.addNotification(
                    "To ensure visibility, %s is now subscribed to: %s"
                    % (
                        visibility_info["person_name"],
                        english_list(invisible_repositories),
                    )
                )
            # Success so we do a client redirect to the new mp page.
            if self.request.is_ajax:
                self.request.response.setStatus(201)
                self.request.response.setHeader(
                    "Location", canonical_url(proposal)
                )
                return None
            else:
                self.next_url = canonical_url(proposal)
        except InvalidBranchMergeProposal as error:
            self.addError(str(error))

    def _validateRef(self, data, name):
        ref = data[f"{name}_git_ref"]
        if ref == self.context:
            self.setFieldError(
                "%s_git_ref" % name,
                "The %s repository and path together cannot be the same "
                "as the source repository and path." % name,
            )
        return ref.repository

    def validate(self, data):
        source_ref = self.context
        # The existence of target_git_repository is handled by the form
        # machinery.
        if data.get("target_git_ref") is not None:
            target_repository = self._validateRef(data, "target")
            if not target_repository.isRepositoryMergeable(
                source_ref.repository
            ):
                self.setFieldError(
                    "target_git_ref",
                    "%s is not mergeable into this repository."
                    % source_ref.repository.identity,
                )
        if data.get("prerequisite_git_ref") is not None:
            prerequisite_repository = self._validateRef(data, "prerequisite")
            if not target_repository.isRepositoryMergeable(
                prerequisite_repository
            ):
                self.setFieldError(
                    "prerequisite_git_ref",
                    "This repository is not mergeable into %s."
                    % target_repository.identity,
                )
