# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "get_git_repository_privacy_filter",
    "GitRepository",
    "GitRepositorySet",
    "parse_git_commits",
]

import email
import logging
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from functools import partial
from itertools import chain, groupby
from operator import attrgetter
from urllib.parse import quote_plus, urlsplit, urlunsplit

import six
from breezy import urlutils
from lazr.enum import DBItem
from lazr.lifecycle.event import ObjectModifiedEvent
from lazr.lifecycle.snapshot import Snapshot
from storm.databases.postgres import Returning
from storm.expr import SQL, And, Coalesce, Desc, Insert, Join, Not, Or, Select
from storm.info import ClassAlias, get_cls_info
from storm.locals import Bool, DateTime, Int, Reference, Unicode
from storm.store import EmptyResultSet, Store
from zope.component import getUtility
from zope.event import notify
from zope.interface import implementer, providedBy
from zope.security.interfaces import Unauthorized
from zope.security.proxy import ProxyFactory, removeSecurityProxy

from lp import _ as msg
from lp.app.enums import (
    PRIVATE_INFORMATION_TYPES,
    PUBLIC_INFORMATION_TYPES,
    InformationType,
)
from lp.app.errors import (
    SubscriptionPrivacyViolation,
    UserCannotUnsubscribePerson,
)
from lp.app.interfaces.informationtype import IInformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.app.interfaces.services import IService
from lp.charms.interfaces.charmrecipe import ICharmRecipeSet
from lp.code.adapters.branch import BranchMergeProposalNoPreviewDiffDelta
from lp.code.enums import (
    BranchMergeProposalStatus,
    GitGranteeType,
    GitListingSort,
    GitObjectType,
    GitPermissionType,
    GitRepositoryStatus,
    GitRepositoryType,
)
from lp.code.errors import (
    CannotDeleteGitRepository,
    CannotModifyNonHostedGitRepository,
    GitDefaultConflict,
    GitTargetError,
    NoSuchGitReference,
)
from lp.code.event.git import GitRefsCreatedEvent, GitRefsUpdatedEvent
from lp.code.interfaces.branchmergeproposal import (
    BRANCH_MERGE_PROPOSAL_FINAL_STATES,
)
from lp.code.interfaces.cibuild import ICIBuildSet
from lp.code.interfaces.codeimport import ICodeImportSet
from lp.code.interfaces.gitactivity import IGitActivitySet
from lp.code.interfaces.gitcollection import (
    IAllGitRepositories,
    IGitCollection,
)
from lp.code.interfaces.githosting import IGitHostingClient
from lp.code.interfaces.gitjob import IGitRefScanJobSource
from lp.code.interfaces.gitlookup import IGitLookup
from lp.code.interfaces.gitnamespace import (
    IGitNamespacePolicy,
    get_git_namespace,
)
from lp.code.interfaces.gitrepository import (
    GitIdentityMixin,
    IGitRepository,
    IGitRepositorySet,
    user_has_special_git_repository_access,
)
from lp.code.interfaces.gitrule import describe_git_permissions, is_rule_exact
from lp.code.interfaces.revision import IRevisionSet
from lp.code.interfaces.revisionstatus import (
    IRevisionStatusReportSet,
    RevisionStatusReportsFeatureDisabled,
)
from lp.code.mail.branch import send_git_repository_modified_notifications
from lp.code.model.branchmergeproposal import BranchMergeProposal
from lp.code.model.gitactivity import GitActivity
from lp.code.model.gitref import GitRef, GitRefDefault, GitRefFrozen
from lp.code.model.gitrule import GitRule, GitRuleGrant
from lp.code.model.gitsubscription import GitSubscription
from lp.code.model.reciperegistry import recipe_registry
from lp.code.model.revisionstatus import RevisionStatusReport
from lp.crafts.interfaces.craftrecipe import ICraftRecipeSet
from lp.registry.enums import PersonVisibility
from lp.registry.errors import CannotChangeInformationType
from lp.registry.interfaces.accesspolicy import (
    IAccessArtifactGrantSource,
    IAccessArtifactSource,
    IAccessPolicySource,
)
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.person import IPerson, IPersonSet
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.role import IHasOwner
from lp.registry.interfaces.sharingjob import (
    IRemoveArtifactSubscriptionsJobSource,
)
from lp.registry.model.accesspolicy import (
    AccessPolicyGrant,
    reconcile_access_for_artifacts,
)
from lp.registry.model.person import Person
from lp.registry.model.teammembership import TeamParticipation
from lp.rocks.interfaces.rockrecipe import IRockRecipeSet
from lp.services.auth.model import AccessTokenTargetMixin
from lp.services.config import config
from lp.services.database import bulk
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import (
    Array,
    ArrayAgg,
    ArrayIntersects,
    BulkUpdate,
    ImmutablePgJSON,
    Values,
)
from lp.services.features import getFeatureFlag
from lp.services.identity.interfaces.account import AccountStatus, IAccountSet
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.model.job import Job
from lp.services.macaroons.interfaces import IMacaroonIssuer
from lp.services.macaroons.model import MacaroonIssuerBase
from lp.services.mail.notificationrecipientset import NotificationRecipientSet
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.interfaces import ILaunchBag
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.model import WebhookTargetMixin
from lp.snappy.interfaces.snap import ISnapSet

REVISION_STATUS_REPORT_ALLOW_CREATE = "revision_status_report.allow_create"

logger = logging.getLogger(__name__)

object_type_map = {
    "commit": GitObjectType.COMMIT,
    "tree": GitObjectType.TREE,
    "blob": GitObjectType.BLOB,
    "tag": GitObjectType.TAG,
}


def parse_git_commits(commits):
    """Parse commit information returned by turnip.

    :param commits: A list of turnip-formatted commit object dicts.
    :return: A dict mapping sha1 identifiers of commits to parsed commit
        dicts: keys may include "sha1", "author_date", "author_addr",
        "author", "committer_date", "committer_addr", "committer",
        "commit_message", and "blobs".
    """
    parsed = {}
    authors_to_acquire = []
    committers_to_acquire = []
    for commit in commits:
        if "sha1" not in commit:
            continue
        info = {"sha1": commit["sha1"]}
        author = commit.get("author")
        if author is not None:
            if "time" in author:
                info["author_date"] = datetime.fromtimestamp(
                    author["time"], tz=timezone.utc
                )
            if "name" in author and "email" in author:
                try:
                    author_addr = email.utils.formataddr(
                        (author["name"], author["email"])
                    )
                except UnicodeEncodeError:
                    # Addresses must be ASCII; formataddr raises
                    # UnicodeEncodeError if they aren't.  Just skip the
                    # author in that case.
                    pass
                else:
                    info["author_addr"] = author_addr
                    authors_to_acquire.append(author_addr)
        committer = commit.get("committer")
        if committer is not None:
            if "time" in committer:
                info["committer_date"] = datetime.fromtimestamp(
                    committer["time"], tz=timezone.utc
                )
            if "name" in committer and "email" in committer:
                try:
                    committer_addr = email.utils.formataddr(
                        (committer["name"], committer["email"])
                    )
                except UnicodeEncodeError:
                    # Addresses must be ASCII; formataddr raises
                    # UnicodeEncodeError if they aren't.  Just skip the
                    # committer in that case.
                    pass
                else:
                    info["committer_addr"] = committer_addr
                    committers_to_acquire.append(committer_addr)
        if "message" in commit:
            info["commit_message"] = commit["message"]
        if "blobs" in commit:
            info["blobs"] = commit["blobs"]
        parsed[commit["sha1"]] = info
    revision_authors = getUtility(IRevisionSet).acquireRevisionAuthors(
        authors_to_acquire + committers_to_acquire
    )
    for info in parsed.values():
        author = revision_authors.get(info.get("author_addr"))
        if author is not None:
            info["author"] = author
        committer = revision_authors.get(info.get("committer_addr"))
        if committer is not None:
            info["committer"] = committer
    return parsed


def git_repository_modified(repository, event):
    """Update the date_last_modified property when a GitRepository is modified.

    This method is registered as a subscriber to `IObjectModifiedEvent`
    events on Git repositories.
    """
    if event.edited_fields:
        repository.date_last_modified = UTC_NOW
    send_git_repository_modified_notifications(repository, event)


@implementer(IGitRepository, IHasOwner, IInformationType)
class GitRepository(
    StormBase, WebhookTargetMixin, AccessTokenTargetMixin, GitIdentityMixin
):
    """See `IGitRepository`."""

    __storm_table__ = "GitRepository"

    id = Int(primary=True)

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )
    date_last_modified = DateTime(
        name="date_last_modified", tzinfo=timezone.utc, allow_none=False
    )

    repository_type = DBEnum(
        name="repository_type", enum=GitRepositoryType, allow_none=False
    )

    status = DBEnum(
        name="status",
        enum=GitRepositoryStatus,
        allow_none=False,
        default=GitRepositoryStatus.AVAILABLE,
    )

    registrant_id = Int(name="registrant", allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    owner_id = Int(name="owner", allow_none=False)
    owner = Reference(owner_id, "Person.id")

    reviewer_id = Int(name="reviewer", allow_none=True)
    reviewer = Reference(reviewer_id, "Person.id")

    project_id = Int(name="project", allow_none=True)
    project = Reference(project_id, "Product.id")

    distribution_id = Int(name="distribution", allow_none=True)
    distribution = Reference(distribution_id, "Distribution.id")

    sourcepackagename_id = Int(name="sourcepackagename", allow_none=True)
    sourcepackagename = Reference(sourcepackagename_id, "SourcePackageName.id")

    oci_project_id = Int(name="oci_project", allow_none=True)
    oci_project = Reference(oci_project_id, "OCIProject.id")

    name = Unicode(name="name", allow_none=False)

    description = Unicode(name="description", allow_none=True)

    information_type = DBEnum(enum=InformationType, allow_none=False)
    owner_default = Bool(name="owner_default", allow_none=False)
    target_default = Bool(name="target_default", allow_none=False)

    _default_branch = Unicode(name="default_branch", allow_none=True)

    loose_object_count = Int(name="loose_object_count", allow_none=True)
    pack_count = Int(name="pack_count", allow_none=True)

    date_last_repacked = DateTime(
        name="date_last_repacked", tzinfo=timezone.utc, allow_none=True
    )
    date_last_scanned = DateTime(
        name="date_last_scanned", tzinfo=timezone.utc, allow_none=True
    )

    builder_constraints = ImmutablePgJSON(
        name="builder_constraints", allow_none=True
    )

    def __init__(
        self,
        repository_type,
        registrant,
        owner,
        target,
        name,
        information_type,
        date_created,
        reviewer=None,
        description=None,
        status=None,
        loose_object_count=None,
        pack_count=None,
        date_last_scanned=None,
        date_last_repacked=None,
        builder_constraints=None,
    ):
        super().__init__()
        self.repository_type = repository_type
        self.registrant = registrant
        self.owner = owner
        self.reviewer = reviewer
        self.name = name
        self.description = description
        self.information_type = information_type
        self.date_created = date_created
        self.date_last_modified = date_created
        self.project = None
        self.distribution = None
        self.sourcepackagename = None
        if IProduct.providedBy(target):
            self.project = target
        elif IDistributionSourcePackage.providedBy(target):
            self.distribution = target.distribution
            self.sourcepackagename = target.sourcepackagename
        elif IOCIProject.providedBy(target):
            self.oci_project = target
        # XXX pappacena 2020-06-08: We should simplify this once the value of
        # GitRepository.status column is backfilled.
        self.status = (
            status if status is not None else GitRepositoryStatus.AVAILABLE
        )
        self.owner_default = False
        self.target_default = False
        self.loose_object_count = loose_object_count
        self.pack_count = pack_count
        self.date_last_repacked = date_last_repacked
        self.date_last_scanned = date_last_scanned
        self.builder_constraints = builder_constraints

    def _createOnHostingService(
        self, clone_from_repository=None, async_create=False
    ):
        """Create this repository on the hosting service."""
        hosting_path = self.getInternalPath()
        if clone_from_repository is not None:
            clone_from_path = clone_from_repository.getInternalPath()
        else:
            clone_from_path = None
        getUtility(IGitHostingClient).create(
            hosting_path, clone_from=clone_from_path, async_create=async_create
        )

    def getClonedFrom(self):
        """See `IGitRepository`"""
        repository_set = getUtility(IGitRepositorySet)
        registrant = self.registrant

        # If repository has target_default, clone from default.
        clone_from_repository = None
        try:
            default = repository_set.getDefaultRepository(self.target)
            if default is not None and default.visibleByUser(registrant):
                clone_from_repository = default
            else:
                default = repository_set.getDefaultRepositoryForOwner(
                    self.owner, self.target
                )
                if default is not None and default.visibleByUser(registrant):
                    clone_from_repository = default
        except GitTargetError:
            pass  # Ignore Personal repositories.
        if clone_from_repository == self:
            clone_from_repository = None

        return clone_from_repository

    @property
    def valid_webhook_event_types(self):
        return [
            "ci:build:0.1",
            "git:push:0.1",
            "merge-proposal:0.1",
            "merge-proposal:0.1::create",
            "merge-proposal:0.1::push",
            "merge-proposal:0.1::review",
            "merge-proposal:0.1::edit",
            "merge-proposal:0.1::status-change",
            "merge-proposal:0.1::delete",
        ]

    @property
    def default_webhook_event_types(self):
        return ["git:push:0.1"]

    # Marker for references to Git URL layouts: ##GITNAMESPACE##
    @property
    def unique_name(self):
        names = {"owner": self.owner.name, "repository": self.name}
        if self.project is not None:
            fmt = "~%(owner)s/%(project)s"
            names["project"] = self.project.name
        elif (
            self.distribution is not None
            and self.sourcepackagename is not None
        ):
            fmt = "~%(owner)s/%(distribution)s/+source/%(source)s"
            names["distribution"] = self.distribution.name
            names["source"] = self.sourcepackagename.name
        elif self.oci_project is not None:
            fmt = "~%(owner)s/%(pillar)s/+oci/%(ociproject)s"
            names["pillar"] = self.oci_project.pillar.name
            names["ociproject"] = self.oci_project.ociprojectname.name
        else:
            fmt = "~%(owner)s"
        fmt += "/+git/%(repository)s"
        return fmt % names

    def __repr__(self):
        return "<GitRepository %r (%d)>" % (self.unique_name, self.id)

    @cachedproperty
    def target(self):
        """See `IGitRepository`."""
        if self.project is not None:
            return self.project
        elif (
            self.distribution is not None
            and self.sourcepackagename is not None
        ):
            return self.distribution.getSourcePackage(self.sourcepackagename)
        elif self.oci_project is not None:
            return self.oci_project
        else:
            return self.owner

    def _checkPersonalPrivateOwnership(self, new_owner):
        if self.information_type in PRIVATE_INFORMATION_TYPES and (
            not new_owner.is_team
            or new_owner.visibility != PersonVisibility.PRIVATE
        ):
            raise GitTargetError(
                "Only private teams may have personal private " "repositories."
            )

    def setTarget(self, target, user):
        """See `IGitRepository`."""
        if IPerson.providedBy(target):
            new_owner = IPerson(target)
            self._checkPersonalPrivateOwnership(new_owner)
        else:
            new_owner = self.owner
        namespace = get_git_namespace(target, new_owner)
        if self.information_type not in namespace.getAllowedInformationTypes(
            user
        ):
            raise GitTargetError(
                "%s repositories are not allowed for target %s."
                % (self.information_type.title, target.displayname)
            )
        namespace.moveRepository(self, user, rename_if_necessary=True)
        self._reconcileAccess()

    def repackRepository(self):
        getUtility(IGitHostingClient).repackRepository(self.getInternalPath())
        self.date_last_repacked = UTC_NOW

    def collectGarbage(self):
        getUtility(IGitHostingClient).collectGarbage(self.getInternalPath())

    def newStatusReport(
        self,
        user,
        title,
        commit_sha1,
        url=None,
        result_summary=None,
        result=None,
    ):
        if not getFeatureFlag(REVISION_STATUS_REPORT_ALLOW_CREATE):
            raise RevisionStatusReportsFeatureDisabled()

        report = RevisionStatusReport(
            self, user, title, commit_sha1, url, result_summary, result
        )
        return report

    def getStatusReports(self, commit_sha1):
        return getUtility(IRevisionStatusReportSet).findByCommit(
            self, commit_sha1
        )

    def fork(self, requester, new_owner):
        if not requester.inTeam(new_owner):
            raise Unauthorized(
                "The owner of the new repository must be you or a team of "
                "which you are a member."
            )
        namespace = get_git_namespace(self.target, new_owner)
        name = namespace.findUnusedName(self.name)
        repository = getUtility(IGitRepositorySet).new(
            repository_type=GitRepositoryType.HOSTED,
            registrant=requester,
            owner=new_owner,
            target=self.target,
            name=name,
            information_type=self.information_type,
            date_created=UTC_NOW,
            description=self.description,
            with_hosting=True,
            async_hosting=True,
            status=GitRepositoryStatus.CREATING,
            clone_from_repository=self,
        )
        if self.target_default or self.owner_default:
            try:
                # If the origin is the default for its target or for its
                # owner and target, then try to set the new repo as
                # owner-default.
                repository.setOwnerDefault(True)
            except GitDefaultConflict:
                # If there is already a owner-default for this owner/target,
                # just move on.
                pass
        return repository

    @property
    def namespace(self):
        """See `IGitRepository`."""
        return get_git_namespace(self.target, self.owner)

    def setOwnerDefault(self, value):
        """See `IGitRepository`."""
        if value:
            # Check for an existing owner-target default.
            repository_set = getUtility(IGitRepositorySet)
            existing = repository_set.getDefaultRepositoryForOwner(
                self.owner, self.target
            )
            if existing is not None and existing != self:
                raise GitDefaultConflict(
                    existing, self.target, owner=self.owner
                )
        self.owner_default = value

    def setTargetDefault(self, value):
        """See `IGitRepository`."""
        if value:
            # Check for an existing target default.
            existing = getUtility(IGitRepositorySet).getDefaultRepository(
                self.target
            )
            if existing is not None and existing != self:
                raise GitDefaultConflict(existing, self.target)
        self.target_default = value
        if IProduct.providedBy(self.target):
            get_property_cache(self.target)._default_git_repository = (
                self if value else None
            )

    @property
    def display_name(self):
        return self.git_identity

    @property
    def code_reviewer(self):
        """See `IGitRepository`."""
        if self.reviewer:
            return self.reviewer
        else:
            return self.owner

    def isPersonTrustedReviewer(self, reviewer):
        """See `IGitRepository`."""
        if reviewer is None:
            return False
        # We trust Launchpad admins.
        lp_admins = getUtility(ILaunchpadCelebrities).admin
        # Both the branch owner and the review team are checked.
        owner = self.owner
        review_team = self.code_reviewer
        return (
            reviewer.inTeam(owner)
            or reviewer.inTeam(review_team)
            or reviewer.inTeam(lp_admins)
        )

    def getInternalPath(self):
        """See `IGitRepository`."""
        # This may need to change later to improve support for sharding.
        # See also `IGitLookup.getByHostingPath`.
        return str(self.id)

    def getCodebrowseUrl(self, username=None, password=None):
        """See `IGitRepository`."""
        url = urlutils.join(
            config.codehosting.git_browse_root, self.shortened_path
        )
        if username is None and password is None:
            return url
        # XXX cjwatson 2019-03-07: This is ugly and needs
        # refactoring once we support more general HTTPS
        # authentication; see also comment in
        # GitRepository.git_https_url.
        split = urlsplit(url)
        netloc = "%s:%s@%s" % (username or "", password or "", split.hostname)
        if split.port:
            netloc += ":%s" % split.port
        return urlunsplit([split.scheme, netloc, split.path, "", ""])

    def getCodebrowseUrlForRevision(self, commit):
        return "%s/commit/?id=%s" % (
            self.getCodebrowseUrl(),
            quote_plus(str(commit)),
        )

    @property
    def git_https_url(self):
        """See `IGitRepository`."""
        # XXX wgrant 2015-06-12: This guard should be removed once we
        # support Git HTTPS auth.
        if self.visibleByUser(None):
            return urlutils.join(
                config.codehosting.git_browse_root, self.shortened_path
            )
        else:
            return None

    @property
    def git_ssh_url(self):
        """See `IGitRepository`."""
        return urlutils.join(
            config.codehosting.git_ssh_root, self.shortened_path
        )

    @property
    def private(self):
        return self.information_type in PRIVATE_INFORMATION_TYPES

    def _reconcileAccess(self):
        """Reconcile the repository's sharing information.

        Takes the information_type and target and makes the related
        AccessArtifact and AccessPolicyArtifacts match.
        """
        wanted_links = None
        pillars = []
        # For private personal repositories, we calculate the wanted grants.
        if (
            not self.project
            and not self.distribution
            and self.information_type not in PUBLIC_INFORMATION_TYPES
        ):
            aasource = getUtility(IAccessArtifactSource)
            [abstract_artifact] = aasource.ensure([self])
            wanted_links = {
                (abstract_artifact, policy)
                for policy in getUtility(IAccessPolicySource).findByTeam(
                    [self.owner]
                )
            }
        else:
            if self.project is not None:
                pillars = [self.project]
            elif self.distribution is not None:
                pillars = [self.distribution]
        reconcile_access_for_artifacts(
            [self], self.information_type, pillars, wanted_links
        )

    @property
    def refs(self):
        """See `IGitRepository`."""
        return (
            Store.of(self)
            .find(GitRef, GitRef.repository_id == self.id)
            .order_by(GitRef.path)
        )

    @property
    def branches(self):
        """See `IGitRepository`."""
        return (
            Store.of(self)
            .find(
                GitRef,
                GitRef.repository_id == self.id,
                GitRef.path.startswith("refs/heads/"),
            )
            .order_by(GitRef.path)
        )

    @property
    def branches_by_date(self):
        """See `IGitRepository`."""
        return self.branches.order_by(Desc(GitRef.committer_date))

    def setRepackData(self, loose_object_count, pack_count):
        self.loose_object_count = loose_object_count
        self.pack_count = pack_count
        self.date_last_scanned = UTC_NOW

    @property
    def default_branch(self):
        """See `IGitRepository`."""
        return self._default_branch

    @default_branch.setter
    def default_branch(self, value):
        """See `IGitRepository`."""
        if self.repository_type != GitRepositoryType.HOSTED:
            raise CannotModifyNonHostedGitRepository(self)
        if value is None:
            raise NoSuchGitReference(self, value)
        ref = self.getRefByPath(value)
        if ref is None:
            raise NoSuchGitReference(self, value)
        if self._default_branch != ref.path:
            self._default_branch = ref.path
            getUtility(IGitHostingClient).setProperties(
                self.getInternalPath(), default_branch=ref.path
            )

    def getRefByPath(self, path):
        if path == "HEAD":
            return GitRefDefault(self)
        paths = [path]
        if not path.startswith("refs/heads/"):
            paths.append("refs/heads/%s" % path)
        refs = Store.of(self).find(
            GitRef, GitRef.repository_id == self.id, GitRef.path.is_in(paths)
        )
        refs_by_path = {r.path: r for r in refs}
        for path in paths:
            ref = refs_by_path.get(path)
            if ref is not None:
                return ref
        return None

    @staticmethod
    def _convertRefInfo(info):
        """Validate and canonicalise ref info from the hosting service.

        :param info: A dict of {"object":
            {"sha1": sha1, "type": "commit"/"tree"/"blob"/"tag"}}.

        :raises ValueError: if the dict is malformed.
        :return: A dict of {"sha1": sha1, "type": `GitObjectType`}.
        """
        if "object" not in info:
            raise ValueError('ref info does not contain "object" key')
        obj = info["object"]
        if "sha1" not in obj:
            raise ValueError('ref info object does not contain "sha1" key')
        if "type" not in obj:
            raise ValueError('ref info object does not contain "type" key')
        if not isinstance(obj["sha1"], str) or len(obj["sha1"]) != 40:
            raise ValueError("ref info sha1 is not a 40-character string")
        if obj["type"] not in object_type_map:
            raise ValueError("ref info type is not a recognised object type")
        sha1 = six.ensure_text(obj["sha1"], encoding="US-ASCII")
        return {"sha1": sha1, "type": object_type_map[obj["type"]]}

    def createOrUpdateRefs(self, refs_info, get_objects=False, logger=None):
        """See `IGitRepository`."""

        def dbify_values(values):
            return [
                list(
                    chain.from_iterable(
                        bulk.dbify_value(col, val)
                        for col, val in zip(columns, value)
                    )
                )
                for value in values
            ]

        # Flush everything up to here, as we may need to invalidate the
        # cache after updating.
        store = Store.of(self)
        store.flush()

        # Try a bulk update first.
        column_names = [
            "repository_id",
            "path",
            "commit_sha1",
            "object_type",
            "author_id",
            "author_date",
            "committer_id",
            "committer_date",
            "commit_message",
        ]
        column_types = [
            ("repository", "integer"),
            ("path", "text"),
            ("commit_sha1", "character(40)"),
            ("object_type", "integer"),
            ("author", "integer"),
            ("author_date", "timestamp without time zone"),
            ("committer", "integer"),
            ("committer_date", "timestamp without time zone"),
            ("commit_message", "text"),
        ]
        columns = [getattr(GitRef, name) for name in column_names]
        values = [
            (
                self.id,
                path,
                info["sha1"],
                info["type"],
                info["author"].id if "author" in info else None,
                info.get("author_date"),
                info["committer"].id if "committer" in info else None,
                info.get("committer_date"),
                info.get("commit_message"),
            )
            for path, info in refs_info.items()
        ]
        db_values = dbify_values(values)
        new_refs_expr = Values("new_refs", column_types, db_values)
        new_refs = ClassAlias(GitRef, "new_refs")
        updated_columns = {
            getattr(GitRef, name): getattr(new_refs, name)
            for name in column_names
            if name not in ("repository_id", "path")
        }
        update_filter = And(
            GitRef.repository_id == new_refs.repository_id,
            GitRef.path == new_refs.path,
        )
        primary_key = get_cls_info(GitRef).primary_key
        updated = list(
            store.execute(
                Returning(
                    BulkUpdate(
                        updated_columns,
                        table=GitRef,
                        values=new_refs_expr,
                        where=update_filter,
                        primary_columns=primary_key,
                    )
                )
            )
        )
        if updated:
            # Some existing GitRef objects may no longer be valid.  Without
            # knowing which ones we already have, it's safest to just
            # invalidate everything.
            store.invalidate()

        # If there are any remaining items, create them.
        create_db_values = dbify_values(
            [value for value in values if (value[0], value[1]) not in updated]
        )
        if create_db_values:
            created = list(
                store.execute(
                    Returning(
                        Insert(
                            columns,
                            values=create_db_values,
                            primary_columns=primary_key,
                        )
                    )
                )
            )
        else:
            created = []

        self.date_last_modified = UTC_NOW
        if created:
            notify(
                GitRefsCreatedEvent(
                    self, [path for _, path in created], logger
                )
            )
        if updated:
            notify(
                GitRefsUpdatedEvent(
                    self, [path for _, path in updated], logger
                )
            )
        if get_objects:
            return bulk.load(GitRef, updated + created)

    def removeRefs(self, paths):
        """See `IGitRepository`."""
        Store.of(self).find(
            GitRef, GitRef.repository == self, GitRef.path.is_in(paths)
        ).remove()
        # Clear cached references to the removed refs.
        # XXX cjwatson 2021-06-08: We should probably do something similar
        # for OCIRecipe, and for Snap if we start caching git_ref there.
        # XXX jugmac00 2024-09-16: once we also include OCI and snaps, we
        # should refactor this to a for loop in a for loop
        for recipe in getUtility(ICharmRecipeSet).findByGitRepository(
            self, paths=paths
        ):
            get_property_cache(recipe)._git_ref = None
        for recipe in getUtility(IRockRecipeSet).findByGitRepository(
            self, paths=paths
        ):
            get_property_cache(recipe)._git_ref = None
        for recipe in getUtility(ICraftRecipeSet).findByGitRepository(
            self, paths=paths
        ):
            get_property_cache(recipe)._git_ref = None
        self.date_last_modified = UTC_NOW

    def planRefChanges(self, hosting_path, logger=None):
        """See `IGitRepository`."""
        hosting_client = getUtility(IGitHostingClient)
        new_refs = {}
        exclude_prefixes = config.codehosting.git_exclude_ref_prefixes.split()
        for path, info in hosting_client.getRefs(
            hosting_path, exclude_prefixes=exclude_prefixes
        ).items():
            try:
                new_refs[path] = self._convertRefInfo(info)
            except ValueError as e:
                if logger is not None:
                    logger.warning(
                        "Unconvertible ref %s %s: %s" % (path, info, e)
                    )
        # GitRef rows can be large (especially commit_message), and we don't
        # need the whole thing.
        current_refs = {
            ref[0]: ref[1:]
            for ref in Store.of(self).find(
                (
                    GitRef.path,
                    GitRef.commit_sha1,
                    GitRef.object_type,
                    And(
                        GitRef.author_id != None,
                        GitRef.author_date != None,
                        GitRef.committer_id != None,
                        GitRef.committer_date != None,
                        GitRef.commit_message != None,
                    ),
                ),
                GitRef.repository_id == self.id,
            )
        }
        refs_to_upsert = {}
        for path, info in new_refs.items():
            current_ref = current_refs.get(path)
            if (
                current_ref is None
                or info["sha1"] != current_ref[0]
                or info["type"] != current_ref[1]
            ):
                refs_to_upsert[path] = info
            elif info["type"] == GitObjectType.COMMIT and not current_ref[2]:
                # Only request detailed commit metadata for refs that point
                # to commits.
                refs_to_upsert[path] = info
        refs_to_remove = set(current_refs) - set(new_refs)
        return refs_to_upsert, refs_to_remove

    def fetchRefCommits(self, refs, filter_paths=None, logger=None):
        """See `IGitRepository`."""
        oids = sorted({info["sha1"] for info in refs.values()})
        if not oids:
            return
        commits = parse_git_commits(
            getUtility(IGitHostingClient).getCommits(
                self.getInternalPath(),
                oids,
                filter_paths=filter_paths,
                logger=logger,
            )
        )
        for info in refs.values():
            commit = commits.get(info["sha1"])
            if commit is not None:
                info.update(commit)

    def synchroniseRefs(self, refs_to_upsert, refs_to_remove, logger=None):
        """See `IGitRepository`."""
        if refs_to_upsert:
            self.createOrUpdateRefs(refs_to_upsert, logger=logger)
        if refs_to_remove:
            self.removeRefs(refs_to_remove)

    def scan(self, log=None):
        """See `IGitRepository`"""
        log = log if log is not None else logger
        hosting_path = self.getInternalPath()
        refs_to_upsert, refs_to_remove = self.planRefChanges(
            hosting_path, logger=log
        )
        self.fetchRefCommits(refs_to_upsert, logger=log)
        self.synchroniseRefs(refs_to_upsert, refs_to_remove, logger=log)
        props = getUtility(IGitHostingClient).getProperties(hosting_path)
        # We don't want ref canonicalisation, nor do we want to send
        # this change back to the hosting service.
        self._default_branch = props["default_branch"]
        return refs_to_upsert, refs_to_remove

    def rescan(self):
        """See `IGitRepository`."""
        getUtility(IGitRefScanJobSource).create(self)

    @cachedproperty
    def _known_viewers(self):
        """A set of known persons able to view this repository.

        This method must return an empty set or repository searches will
        trigger late evaluation.  Any 'should be set on load' properties
        must be done by the repository search.

        If you are tempted to change this method, don't. Instead see
        visibleByUser which defines the just-in-time policy for repository
        visibility, and IGitCollection which honours visibility rules.
        """
        return set()

    def getLatestScanJob(self):
        """See `IGitRepository`."""
        from lp.code.model.gitjob import GitJob, GitRefScanJob

        latest_job = (
            IStore(GitJob)
            .find(
                GitJob,
                GitJob.repository == self,
                GitJob.job_type == GitRefScanJob.class_job_type,
                GitJob.job == Job.id,
            )
            .order_by(Desc(Job.date_finished))
            .first()
        )
        return latest_job

    def visibleByUser(self, user):
        """See `IGitRepository`."""
        if self.information_type in PUBLIC_INFORMATION_TYPES:
            return True
        elif user is None:
            return False
        elif user.id in self._known_viewers:
            return True
        else:
            return (
                not getUtility(IAllGitRepositories)
                .withIds(self.id)
                .visibleByUser(user)
                .is_empty()
            )

    def getAllowedInformationTypes(self, user):
        """See `IGitRepository`."""
        if user_has_special_git_repository_access(user):
            # Admins can set any type.
            types = set(PUBLIC_INFORMATION_TYPES + PRIVATE_INFORMATION_TYPES)
        else:
            # Otherwise the permitted types are defined by the namespace.
            policy = IGitNamespacePolicy(self.namespace)
            types = set(policy.getAllowedInformationTypes(user))
        return types

    def transitionToInformationType(
        self, information_type, user, verify_policy=True
    ):
        """See `IGitRepository`."""
        if self.information_type == information_type:
            return
        if (
            verify_policy
            and information_type not in self.getAllowedInformationTypes(user)
        ):
            raise CannotChangeInformationType("Forbidden by project policy.")
        # XXX cjwatson 2019-03-29: Check privacy rules on snaps that use
        # this repository.
        self.information_type = information_type
        self._reconcileAccess()
        if (
            information_type in PRIVATE_INFORMATION_TYPES
            and not self.subscribers.is_empty()
        ):
            # Grant the subscriber access if they can't see the repository.
            service = getUtility(IService, "sharing")
            blind_subscribers = service.getPeopleWithoutAccess(
                self, self.subscribers
            )
            if len(blind_subscribers):
                service.ensureAccessGrants(
                    blind_subscribers,
                    user,
                    gitrepositories=[self],
                    ignore_permissions=True,
                )
        # As a result of the transition, some subscribers may no longer have
        # access to the repository.  We need to run a job to remove any such
        # subscriptions.
        getUtility(IRemoveArtifactSubscriptionsJobSource).create(user, [self])

    def setName(self, new_name, user):
        """See `IGitRepository`."""
        self.namespace.moveRepository(self, user, new_name=new_name)

    def setOwner(self, new_owner, user):
        """See `IGitRepository`."""
        if self.owner == self.target:
            self._checkPersonalPrivateOwnership(new_owner)
            new_target = new_owner
        else:
            new_target = self.target
        new_namespace = get_git_namespace(new_target, new_owner)
        new_namespace.moveRepository(self, user, rename_if_necessary=True)
        self._reconcileAccess()

    @property
    def subscriptions(self):
        return Store.of(self).find(
            GitSubscription, GitSubscription.repository == self
        )

    @property
    def subscribers(self):
        return Store.of(self).find(
            Person,
            GitSubscription.person_id == Person.id,
            GitSubscription.repository == self,
        )

    def userCanBeSubscribed(self, person):
        """See `IGitRepository`."""
        return not (
            person.is_team
            and self.information_type in PRIVATE_INFORMATION_TYPES
            and person.anyone_can_join()
        )

    def subscribe(
        self,
        person,
        notification_level,
        max_diff_lines,
        code_review_level,
        subscribed_by,
    ):
        """See `IGitRepository`."""
        if not self.userCanBeSubscribed(person):
            raise SubscriptionPrivacyViolation(
                "Open and delegated teams cannot be subscribed to private "
                "repositories."
            )
        # If the person is already subscribed, update the subscription with
        # the specified notification details.
        subscription = self.getSubscription(person)
        if subscription is None:
            subscription = GitSubscription(
                person=person,
                repository=self,
                notification_level=notification_level,
                max_diff_lines=max_diff_lines,
                review_level=code_review_level,
                subscribed_by=subscribed_by,
            )
            Store.of(subscription).flush()
        else:
            subscription.notification_level = notification_level
            subscription.max_diff_lines = max_diff_lines
            subscription.review_level = code_review_level
        # Grant the subscriber access if they can't see the repository.
        service = getUtility(IService, "sharing")
        repositories = service.getVisibleArtifacts(
            person, gitrepositories=[self], ignore_permissions=True
        )["gitrepositories"]
        if not repositories:
            service.ensureAccessGrants(
                [person],
                subscribed_by,
                gitrepositories=[self],
                ignore_permissions=True,
            )
        return subscription

    def getSubscription(self, person):
        """See `IGitRepository`."""
        if person is None:
            return None
        return (
            Store.of(self)
            .find(
                GitSubscription,
                GitSubscription.person == person,
                GitSubscription.repository == self,
            )
            .one()
        )

    def getSubscriptionsByLevel(self, notification_levels):
        """See `IGitRepository`."""
        # XXX: JonathanLange 2009-05-07 bug=373026: This is only used by real
        # code to determine whether there are any subscribers at the given
        # notification levels. The only code that cares about the actual
        # object is in a test:
        # test_only_nodiff_subscribers_means_no_diff_generated.
        return Store.of(self).find(
            GitSubscription,
            GitSubscription.repository == self,
            GitSubscription.notification_level.is_in(notification_levels),
        )

    def hasSubscription(self, person):
        """See `IGitRepository`."""
        return self.getSubscription(person) is not None

    def unsubscribe(self, person, unsubscribed_by, ignore_permissions=False):
        """See `IGitRepository`."""
        subscription = self.getSubscription(person)
        if subscription is None:
            # Silent success seems order of the day (like bugs).
            return
        if (
            not ignore_permissions
            and not subscription.canBeUnsubscribedByUser(unsubscribed_by)
        ):
            raise UserCannotUnsubscribePerson(
                "%s does not have permission to unsubscribe %s."
                % (unsubscribed_by.displayname, person.displayname)
            )
        store = Store.of(subscription)
        store.remove(subscription)
        artifact = getUtility(IAccessArtifactSource).find([self])
        getUtility(IAccessArtifactGrantSource).revokeByArtifact(
            artifact, [person]
        )
        store.flush()

    def getNotificationRecipients(self):
        """See `IGitRepository`."""
        recipients = NotificationRecipientSet()
        for subscription in self.subscriptions:
            if subscription.person.is_team:
                rationale = "Subscriber @%s" % subscription.person.name
            else:
                rationale = "Subscriber"
            recipients.add(subscription.person, subscription, rationale)
        return recipients

    @property
    def landing_targets(self):
        """See `IGitRepository`."""
        return Store.of(self).find(
            BranchMergeProposal,
            BranchMergeProposal.source_git_repository == self,
        )

    def getPrecachedLandingTargets(self, user, only_active=False):
        """See `IGitRepository`."""
        results = self.landing_targets
        if only_active:
            results = self.landing_targets.find(
                Not(
                    BranchMergeProposal.queue_status.is_in(
                        BRANCH_MERGE_PROPOSAL_FINAL_STATES
                    )
                )
            )
        loader = partial(BranchMergeProposal.preloadDataForBMPs, user=user)
        return DecoratedResultSet(results, pre_iter_hook=loader)

    @property
    def _api_landing_targets(self):
        return self.getPrecachedLandingTargets(getUtility(ILaunchBag).user)

    def getActiveLandingTargets(self, paths):
        """Merge proposals not in final states where these refs are source."""
        return Store.of(self).find(
            BranchMergeProposal,
            BranchMergeProposal.source_git_repository == self,
            BranchMergeProposal.source_git_path.is_in(paths),
            Not(
                BranchMergeProposal.queue_status.is_in(
                    BRANCH_MERGE_PROPOSAL_FINAL_STATES
                )
            ),
        )

    @property
    def landing_candidates(self):
        """See `IGitRepository`."""
        return Store.of(self).find(
            BranchMergeProposal,
            BranchMergeProposal.target_git_repository == self,
            Not(
                BranchMergeProposal.queue_status.is_in(
                    BRANCH_MERGE_PROPOSAL_FINAL_STATES
                )
            ),
        )

    def getPrecachedLandingCandidates(self, user):
        """See `IGitRepository`."""
        loader = partial(
            BranchMergeProposal.preloadDataForBMPs,
            user=user,
            include_votes=True,
        )
        return DecoratedResultSet(
            self.landing_candidates, pre_iter_hook=loader
        )

    @property
    def _api_landing_candidates(self):
        return self.getPrecachedLandingCandidates(getUtility(ILaunchBag).user)

    def getActiveLandingCandidates(self, paths):
        """Merge proposals not in final states where these refs are target."""
        return Store.of(self).find(
            BranchMergeProposal,
            BranchMergeProposal.target_git_repository == self,
            BranchMergeProposal.target_git_path.is_in(paths),
            Not(
                BranchMergeProposal.queue_status.is_in(
                    BRANCH_MERGE_PROPOSAL_FINAL_STATES
                )
            ),
        )

    @property
    def dependent_landings(self):
        """See `IGitRepository`."""
        return Store.of(self).find(
            BranchMergeProposal,
            BranchMergeProposal.prerequisite_git_repository == self,
            Not(
                BranchMergeProposal.queue_status.is_in(
                    BRANCH_MERGE_PROPOSAL_FINAL_STATES
                )
            ),
        )

    def getMergeProposals(
        self,
        status=None,
        visible_by_user=None,
        merged_revision_ids=None,
        eager_load=False,
    ):
        """See `IGitRepository`."""
        if not status:
            status = (
                BranchMergeProposalStatus.CODE_APPROVED,
                BranchMergeProposalStatus.NEEDS_REVIEW,
                BranchMergeProposalStatus.WORK_IN_PROGRESS,
            )

        collection = getUtility(IAllGitRepositories).visibleByUser(
            visible_by_user
        )
        return collection.getMergeProposals(
            status,
            target_repository=self,
            merged_revision_ids=merged_revision_ids,
            eager_load=eager_load,
        )

    def getMergeProposalByID(self, id):
        """See `IGitRepository`."""
        return self.landing_targets.find(BranchMergeProposal.id == id).one()

    def isRepositoryMergeable(self, other):
        """See `IGitRepository`."""
        return self.namespace.areRepositoriesMergeable(self, other)

    @property
    def pending_updates(self):
        """See `IGitRepository`."""
        from lp.code.model.gitjob import GitJob, GitJobType

        jobs = Store.of(self).find(
            GitJob,
            GitJob.repository == self,
            GitJob.job_type == GitJobType.REF_SCAN,
            GitJob.job == Job.id,
            Job._status.is_in([JobStatus.WAITING, JobStatus.RUNNING]),
        )
        return not jobs.is_empty()

    def updateMergeCommitIDs(self, paths):
        """See `IGitRepository`."""
        store = Store.of(self)
        refs = {
            path: commit_sha1
            for path, commit_sha1 in store.find(
                (GitRef.path, GitRef.commit_sha1),
                GitRef.repository_id == self.id,
                GitRef.path.is_in(paths),
            )
        }
        updated = set()
        for kind in ("source", "target", "prerequisite"):
            repository_name = "%s_git_repository_id" % kind
            path_name = "%s_git_path" % kind
            commit_sha1_name = "%s_git_commit_sha1" % kind
            old_column = partial(getattr, BranchMergeProposal)
            db_kind = "dependent" if kind == "prerequisite" else kind
            column_types = [
                ("%s_git_path" % db_kind, "text"),
                ("%s_git_commit_sha1" % db_kind, "character(40)"),
            ]
            db_values = [
                (
                    bulk.dbify_value(old_column(path_name), path),
                    bulk.dbify_value(
                        old_column(commit_sha1_name), commit_sha1
                    ),
                )
                for path, commit_sha1 in refs.items()
            ]
            new_proposals_expr = Values(
                "new_proposals", column_types, db_values
            )
            new_proposals = ClassAlias(BranchMergeProposal, "new_proposals")
            new_column = partial(getattr, new_proposals)
            updated_columns = {
                old_column(commit_sha1_name): new_column(commit_sha1_name)
            }
            update_filter = And(
                old_column(repository_name) == self.id,
                old_column(path_name) == new_column(path_name),
                Not(
                    BranchMergeProposal.queue_status.is_in(
                        BRANCH_MERGE_PROPOSAL_FINAL_STATES
                    )
                ),
            )
            result = store.execute(
                Returning(
                    BulkUpdate(
                        updated_columns,
                        table=BranchMergeProposal,
                        values=new_proposals_expr,
                        where=update_filter,
                        primary_columns=BranchMergeProposal.id,
                    )
                )
            )
            updated.update(item[0] for item in result)
        if updated:
            # Some existing BranchMergeProposal objects may no longer be
            # valid.  Without knowing which ones we already have, it's
            # safest to just invalidate everything.
            store.invalidate()
        return updated

    def updateLandingTargets(self, paths):
        """See `IGitRepository`."""
        jobs = []
        for merge_proposal in self.getActiveLandingTargets(paths):
            jobs.extend(merge_proposal.scheduleDiffUpdates())
        return jobs

    def makeFrozenRef(self, path, commit_sha1):
        return GitRefFrozen(
            self,
            path,
            commit_sha1,
        )

    def _getRecipes(self, paths=None):
        """Undecorated version of recipes for use by `markRecipesStale`."""
        from lp.code.model.sourcepackagerecipedata import (
            SourcePackageRecipeData,
        )

        if paths is not None:
            revspecs = set()
            for path in paths:
                revspecs.add(path)
                if path.startswith("refs/heads/"):
                    revspecs.add(path[len("refs/heads/") :])
                if path == self.default_branch:
                    revspecs.add(None)
            revspecs = list(revspecs)
        else:
            revspecs = None
        return SourcePackageRecipeData.findRecipes(self, revspecs=revspecs)

    @property
    def recipes(self):
        """See `IHasRecipes`."""
        from lp.code.model.sourcepackagerecipe import SourcePackageRecipe

        hook = SourcePackageRecipe.preLoadDataForSourcePackageRecipes
        return DecoratedResultSet(self._getRecipes(), pre_iter_hook=hook)

    def markRecipesStale(self, paths):
        """See `IGitRepository`."""
        for recipe in self._getRecipes(paths):
            recipe.is_stale = True

    def markSnapsStale(self, paths):
        """See `IGitRepository`."""
        snap_set = getUtility(ISnapSet)
        snaps = snap_set.findByGitRepository(
            self, paths=paths, check_permissions=False
        )
        for snap in snaps:
            # ISnapSet.findByGitRepository returns security-proxied Snap
            # objects on which the is_stale attribute is read-only.  Bypass
            # this.
            removeSecurityProxy(snap).is_stale = True

    def markCharmRecipesStale(self, paths):
        """See `IGitRepository`."""
        recipes = getUtility(ICharmRecipeSet).findByGitRepository(
            self, paths=paths, check_permissions=False
        )
        for recipe in recipes:
            # ICharmRecipeSet.findByGitRepository returns security-proxied
            # CharmRecipe objects on which the is_stale attribute is
            # read-only.  Bypass this.
            removeSecurityProxy(recipe).is_stale = True

    def _markProposalMerged(self, proposal, merged_revision_id, logger=None):
        if logger is not None:
            logger.info(
                "Merge detected: %s => %s",
                proposal.source_git_ref.identity,
                proposal.target_git_ref.identity,
            )
        with BranchMergeProposalNoPreviewDiffDelta.monitor(proposal):
            proposal.markAsMerged(merged_revision_id=merged_revision_id)

    def detectMerges(self, paths, previous_targets, logger=None):
        """See `IGitRepository`."""
        hosting_client = getUtility(IGitHostingClient)
        all_proposals = self.getActiveLandingCandidates(paths).order_by(
            BranchMergeProposal.target_git_path
        )
        for _, group in groupby(all_proposals, attrgetter("target_git_path")):
            proposals = list(group)
            merges = hosting_client.detectMerges(
                self.getInternalPath(),
                proposals[0].target_git_commit_sha1,
                {proposal.source_git_commit_sha1 for proposal in proposals},
                previous_target=previous_targets.get(proposals[0].id),
            )
            for proposal in proposals:
                merged_revision_id = merges.get(
                    proposal.source_git_commit_sha1
                )
                if merged_revision_id is not None:
                    self._markProposalMerged(
                        proposal, merged_revision_id, logger=logger
                    )

    def getBlob(self, filename, rev=None):
        """See `IGitRepository`."""
        hosting_client = getUtility(IGitHostingClient)
        return hosting_client.getBlob(
            self.getInternalPath(), filename, rev=rev
        )

    def getDiff(self, old, new):
        """See `IGitRepository`."""
        hosting_client = getUtility(IGitHostingClient)
        diff = hosting_client.getDiff(self.getInternalPath(), old, new)
        return diff["patch"]

    @cachedproperty
    def code_import(self):
        return getUtility(ICodeImportSet).getByGitRepository(self)

    @property
    def rules(self):
        """See `IGitRepository`."""
        return (
            Store.of(self)
            .find(GitRule, GitRule.repository == self)
            .order_by(GitRule.position)
        )

    def _canonicaliseRuleOrdering(self, rules):
        """Canonicalise rule ordering.

        Exact-match rules come first in lexicographical order, followed by
        wildcard rules in the requested order.  (Note that `sorted` is
        guaranteed to be stable.)
        """
        return sorted(
            rules,
            key=lambda rule: (
                (0, rule.ref_pattern) if is_rule_exact(rule) else (1,)
            ),
        )

    def _syncRulePositions(self, rules):
        """Synchronise rule positions with their order in a provided list.

        :param rules: A sequence of `IGitRule`s in the desired order.
        """
        rules = self._canonicaliseRuleOrdering(rules)
        # Ensure the correct position of all rules, which may involve more
        # work than necessary, but is simple and tends to be
        # self-correcting.  This works because the unique constraint on
        # GitRule(repository, position) is deferred.
        for position, rule in enumerate(rules):
            if rule.repository != self:
                raise AssertionError("%r does not belong to %r" % (rule, self))
            if rule.position != position:
                removeSecurityProxy(rule).position = position

    def getRule(self, ref_pattern):
        """See `IGitRepository`."""
        return self.rules.find(GitRule.ref_pattern == ref_pattern).one()

    def addRule(self, ref_pattern, creator, position=None):
        """See `IGitRepository`."""
        rules = list(self.rules)
        rule = GitRule(
            repository=self,
            # -1 isn't a valid position, but _syncRulePositions will correct
            # it in a moment.
            position=position if position is not None else -1,
            ref_pattern=ref_pattern,
            creator=creator,
            date_created=DEFAULT,
        )
        if position is None:
            rules.append(rule)
        else:
            rules.insert(position, rule)
        self._syncRulePositions(rules)
        getUtility(IGitActivitySet).logRuleAdded(rule, creator)
        return rule

    def moveRule(self, rule, position, user):
        """See `IGitRepository`."""
        if rule.repository != self:
            raise ValueError("%r does not belong to %r" % (rule, self))
        if position < 0:
            raise ValueError("Negative positions are not supported")
        current_position = rule.position
        if position != current_position:
            rules = list(self.rules)
            rules.remove(rule)
            rules.insert(position, rule)
            self._syncRulePositions(rules)
            if rule.position != current_position:
                getUtility(IGitActivitySet).logRuleMoved(
                    rule, current_position, rule.position, user
                )

    @property
    def grants(self):
        """See `IGitRepository`."""
        return Store.of(self).find(
            GitRuleGrant, GitRuleGrant.repository_id == self.id
        )

    def findRuleGrantsByGrantee(
        self, grantee, include_transitive=True, ref_pattern=None
    ):
        """See `IGitRepository`."""
        if isinstance(grantee, DBItem) and grantee.enum == GitGranteeType:
            if grantee == GitGranteeType.PERSON:
                raise ValueError(
                    "grantee may not be GitGranteeType.PERSON; pass a person "
                    "object instead"
                )
            clauses = [GitRuleGrant.grantee_type == grantee]
        elif not include_transitive:
            clauses = [
                GitRuleGrant.grantee_type == GitGranteeType.PERSON,
                GitRuleGrant.grantee == grantee,
            ]
        else:
            clauses = [
                GitRuleGrant.grantee_type == GitGranteeType.PERSON,
                TeamParticipation.person == grantee,
                GitRuleGrant.grantee == TeamParticipation.team_id,
            ]
        if ref_pattern is not None:
            clauses.extend(
                [
                    GitRuleGrant.rule_id == GitRule.id,
                    GitRule.ref_pattern == ref_pattern,
                ]
            )
        return self.grants.find(*clauses).config(distinct=True)

    def getRules(self):
        """See `IGitRepository`."""
        rules = list(self.rules)
        GitRule.preloadGrantsForRules(rules)
        return rules

    @staticmethod
    def _validateRules(rules):
        """Validate a new iterable of access rules."""
        patterns = set()
        for rule in rules:
            if rule.ref_pattern in patterns:
                raise ValueError(
                    "New rules may not contain duplicate ref patterns "
                    "(e.g. %s)" % rule.ref_pattern
                )
            patterns.add(rule.ref_pattern)

    def setRules(self, rules, user):
        """See `IGitRepository`."""
        self._validateRules(rules)
        existing_rules = {rule.ref_pattern: rule for rule in self.rules}
        new_rules = OrderedDict(
            (rule.ref_pattern, rule)
            for rule in self._canonicaliseRuleOrdering(rules)
        )
        GitRule.preloadGrantsForRules(existing_rules.values())

        # Remove old rules first so that we don't generate unnecessary move
        # events.
        for ref_pattern, rule in existing_rules.items():
            if ref_pattern not in new_rules:
                rule.destroySelf(user)

        # Do our best to match up the new rules and grants to any existing
        # ones, in order to preserve creator and date-created information.
        # XXX cjwatson 2018-09-11: We could optimise this to create the new
        # rules in bulk, but it probably isn't worth the extra complexity.
        for position, (ref_pattern, new_rule) in enumerate(new_rules.items()):
            rule = existing_rules.get(ref_pattern)
            if rule is None:
                rule = self.addRule(
                    new_rule.ref_pattern, user, position=position
                )
            else:
                rule_before_modification = Snapshot(
                    rule, providing=providedBy(rule)
                )
                self.moveRule(rule, position, user)
                if rule.position != rule_before_modification.position:
                    notify(
                        ObjectModifiedEvent(
                            rule, rule_before_modification, ["position"]
                        )
                    )
            rule.setGrants(new_rule.grants, user)

        # The individual moves and adds above should have resulted in
        # correct rule ordering, but check this.
        requested_rule_order = list(new_rules)
        observed_rule_order = [rule.ref_pattern for rule in self.rules]
        if requested_rule_order != observed_rule_order:
            raise AssertionError(
                "setRules failed to establish requested rule order %s "
                "(got %s instead)"
                % (requested_rule_order, observed_rule_order)
            )

    def checkRefPermissions(self, person, ref_paths):
        """See `IGitRepository`."""
        result = {}

        rules = list(self.rules)
        grants_for_user = defaultdict(list)
        grants = EmptyResultSet()
        is_owner = False
        if IPerson.providedBy(person):
            grants = grants.union(self.findRuleGrantsByGrantee(person))
            if person.inTeam(self.owner):
                is_owner = True
        elif person == GitGranteeType.REPOSITORY_OWNER:
            is_owner = True
        if is_owner:
            grants = grants.union(
                self.findRuleGrantsByGrantee(GitGranteeType.REPOSITORY_OWNER)
            )

        bulk.load_related(Person, grants, ["grantee_id"])
        for grant in grants:
            grants_for_user[grant.rule].append(grant)

        for ref_path in ref_paths:
            matching_rules = [
                rule
                for rule in rules
                if fnmatch(
                    six.ensure_binary(ref_path),
                    rule.ref_pattern.encode("UTF-8"),
                )
            ]
            if is_owner and not matching_rules:
                # If there are no matching rules, then the repository owner
                # can do anything.
                result[ref_path] = {
                    GitPermissionType.CAN_CREATE,
                    GitPermissionType.CAN_PUSH,
                    GitPermissionType.CAN_FORCE_PUSH,
                }
                continue

            seen_grantees = set()
            union_permissions = set()
            for rule in matching_rules:
                for grant in grants_for_user[rule]:
                    if (grant.grantee, grant.grantee_type) in seen_grantees:
                        continue
                    union_permissions.update(grant.permissions)
                    seen_grantees.add((grant.grantee, grant.grantee_type))

            owner_type = (None, GitGranteeType.REPOSITORY_OWNER)
            if is_owner and owner_type not in seen_grantees:
                union_permissions.update(
                    {GitPermissionType.CAN_CREATE, GitPermissionType.CAN_PUSH}
                )

            # Permission to force-push implies permission to push.
            if GitPermissionType.CAN_FORCE_PUSH in union_permissions:
                union_permissions.add(GitPermissionType.CAN_PUSH)

            result[ref_path] = union_permissions

        return result

    def api_checkRefPermissions(self, person, paths):
        """See `IGitRepository`."""
        return {
            path: describe_git_permissions(permissions)
            for path, permissions in self.checkRefPermissions(
                person, paths
            ).items()
        }

    def getActivity(self, changed_after=None):
        """See `IGitRepository`."""
        clauses = [GitActivity.repository_id == self.id]
        if changed_after is not None:
            clauses.append(GitActivity.date_changed > changed_after)
        return (
            Store.of(self)
            .find(GitActivity, *clauses)
            .order_by(Desc(GitActivity.date_changed), Desc(GitActivity.id))
        )

    def getPrecachedActivity(self, **kwargs):
        def preloadDataForActivities(activities):
            # Utility to load related data for a list of GitActivity
            person_ids = set()
            for activity in activities:
                person_ids.add(activity.changer_id)
                person_ids.add(activity.changee_id)
            list(
                getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                    person_ids, need_validity=True
                )
            )
            return activities

        results = self.getActivity(**kwargs)
        return DecoratedResultSet(
            results, pre_iter_hook=preloadDataForActivities
        )

    # XXX cjwatson 2021-10-13: Remove this once lp.code.xmlrpc.git accepts
    # pushes using personal access tokens.
    def _issueMacaroon(self, user):
        """Issue a macaroon for this repository."""
        issuer = getUtility(IMacaroonIssuer, "git-repository")
        # Our security adapter has already done the checks we need, apart
        # from forbidding anonymous users which is done by the issuer.
        return (
            removeSecurityProxy(issuer)
            .issueMacaroon(self, user=user)
            .serialize()
        )

    # XXX ines-almeida 2023-09-08: This method can be removed in favour of the
    # inherited one from AccessTokenTarget once we don't need  `_issueMacaroon`
    # (see `_issueMacaroon` above)
    def issueAccessToken(
        self, description=None, scopes=None, date_expires=None
    ):
        """See `IGitRepository`."""
        if description is not None and scopes is not None:
            return super().issueAccessToken(
                description, scopes, date_expires=date_expires
            )
        else:
            return self._issueMacaroon(getUtility(ILaunchBag).user)

    def canBeDeleted(self):
        """See `IGitRepository`."""
        # Can't delete if the repository is associated with anything.
        return len(self.getDeletionRequirements()) == 0

    def _getDeletionRequirements(self, eager_load=False):
        """Determine what operations must be performed to delete this branch.

        Two dictionaries are returned, one for items that must be deleted,
        one for items that must be altered.  The item in question is the
        key, and the value is a user-facing string explaining why the item
        is affected.

        As well as the dictionaries, this method returns two list of callables
        that may be called to perform the alterations and deletions needed.
        """
        alteration_operations = []
        deletion_operations = []
        seen_merge_proposal_ids = set()
        # Merge proposals require their source and target repositories to
        # exist.
        for merge_proposal in self.landing_targets:
            if merge_proposal.id not in seen_merge_proposal_ids:
                deletion_operations.append(
                    DeletionCallable(
                        merge_proposal,
                        msg(
                            "This repository is the source repository of this "
                            "merge proposal."
                        ),
                        merge_proposal.deleteProposal,
                    )
                )
                seen_merge_proposal_ids.add(merge_proposal.id)
        # Cannot use self.landing_candidates, because it ignores merged
        # merge proposals.
        for merge_proposal in Store.of(self).find(
            BranchMergeProposal, target_git_repository=self
        ):
            if merge_proposal.id not in seen_merge_proposal_ids:
                deletion_operations.append(
                    DeletionCallable(
                        merge_proposal,
                        msg(
                            "This repository is the target repository of this "
                            "merge proposal."
                        ),
                        merge_proposal.deleteProposal,
                    )
                )
                seen_merge_proposal_ids.add(merge_proposal.id)
        for merge_proposal in Store.of(self).find(
            BranchMergeProposal, prerequisite_git_repository=self
        ):
            if merge_proposal.id not in seen_merge_proposal_ids:
                alteration_operations.append(
                    ClearPrerequisiteRepository(merge_proposal)
                )
                seen_merge_proposal_ids.add(merge_proposal.id)
        recipes = self.recipes if eager_load else self._getRecipes()
        deletion_operations.extend(
            DeletionCallable(
                recipe,
                msg("This recipe uses this repository."),
                recipe.destroySelf,
            )
            for recipe in recipes
        )

        for utility, message, _ in recipe_registry.get_recipe_types():
            if not getUtility(utility).findByGitRepository(self).is_empty():
                alteration_operations.append(
                    DeletionCallable(
                        None,
                        msg(message),
                        getUtility(utility).detachFromGitRepository,
                        self,
                    )
                )

        return (alteration_operations, deletion_operations)

    def getDeletionRequirements(self, eager_load=False):
        """See `IGitRepository`."""
        (
            alteration_operations,
            deletion_operations,
        ) = self._getDeletionRequirements(eager_load=eager_load)
        result = {
            operation.affected_object: ("alter", operation.rationale)
            for operation in alteration_operations
        }
        # Deletion entries should overwrite alteration entries.
        result.update(
            {
                operation.affected_object: ("delete", operation.rationale)
                for operation in deletion_operations
            }
        )
        return result

    def _breakReferences(self):
        """Break all external references to this repository.

        NULLable references will be NULLed.  References which are not NULLable
        will cause the item holding the reference to be deleted.

        This function is guaranteed to perform the operations predicted by
        getDeletionRequirements, because it uses the same backing function.
        """
        (
            alteration_operations,
            deletion_operations,
        ) = self._getDeletionRequirements()
        for operation in alteration_operations:
            operation()
        for operation in deletion_operations:
            operation()
        # Special-case code import, since users don't have lp.Edit on them,
        # since if you can delete a repository you should be able to delete
        # the code import, and since deleting the code import object itself
        # isn't actually a very interesting thing to tell the user about.
        if self.code_import is not None:
            DeleteCodeImport(self.code_import)()
        Store.of(self).flush()

    def _deleteRepositoryAccessGrants(self):
        """Delete access grants for this repository prior to deleting it."""
        getUtility(IAccessArtifactSource).delete([self])

    def _deleteRepositorySubscriptions(self):
        """Delete subscriptions for this repository prior to deleting it."""
        subscriptions = Store.of(self).find(
            GitSubscription, GitSubscription.repository == self
        )
        subscriptions.remove()

    def _deleteJobs(self):
        """Delete jobs for this repository prior to deleting it.

        This deletion includes `GitJob`s associated with the branch.
        """
        # Circular import.
        from lp.code.model.gitjob import GitJob

        # Remove GitJobs.
        affected_jobs = Select(
            [GitJob.job_id],
            And(GitJob.job == Job.id, GitJob.repository == self),
        )
        Store.of(self).find(Job, Job.id.is_in(affected_jobs)).remove()

    def destroySelf(self, break_references=False):
        """See `IGitRepository`."""
        # Circular import.
        from lp.code.interfaces.gitjob import (
            IReclaimGitRepositorySpaceJobSource,
        )

        if break_references:
            self._breakReferences()
        if not self.canBeDeleted():
            raise CannotDeleteGitRepository(
                "Cannot delete Git repository: %s" % self.unique_name
            )

        self.refs.remove()
        self._deleteRepositoryAccessGrants()
        self._deleteRepositorySubscriptions()
        self._deleteJobs()
        getUtility(IWebhookSet).delete(self.webhooks)
        self.getActivity().remove()
        # We intentionally skip the usual destructors; the only other useful
        # thing they do is to log the removal activity, and we remove the
        # activity logs for removed repositories anyway.
        self.grants.remove()
        self.rules.remove()
        removeSecurityProxy(
            self.getAccessTokens(include_expired=True)
        ).remove()
        getUtility(IRevisionStatusReportSet).deleteForRepository(self)
        getUtility(ICIBuildSet).deleteByGitRepository(self)

        # Now destroy the repository.
        repository_name = self.unique_name
        repository_path = self.getInternalPath()
        Store.of(self).remove(self)
        # And now create a job to remove the repository from storage when
        # it's done.
        if self.status == GitRepositoryStatus.AVAILABLE:
            getUtility(IReclaimGitRepositorySpaceJobSource).create(
                repository_name, repository_path
            )


class DeletionOperation:
    """Represent an operation to perform as part of branch deletion."""

    def __init__(self, affected_object, rationale):
        self.affected_object = ProxyFactory(affected_object)
        self.rationale = rationale

    def __call__(self):
        """Perform the deletion operation."""
        raise NotImplementedError(DeletionOperation.__call__)


class DeletionCallable(DeletionOperation):
    """Deletion operation that invokes a callable."""

    def __init__(self, affected_object, rationale, func, *args, **kwargs):
        super().__init__(affected_object, rationale)
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def __call__(self):
        self.func(*self.args, **self.kwargs)


class ClearPrerequisiteRepository(DeletionOperation):
    """Delete operation that clears a merge proposal's prerequisite
    repository."""

    def __init__(self, merge_proposal):
        DeletionOperation.__init__(
            self,
            merge_proposal,
            msg(
                "This repository is the prerequisite repository of this merge "
                "proposal."
            ),
        )

    def __call__(self):
        self.affected_object.prerequisite_git_repository = None
        self.affected_object.prerequisite_git_path = None
        self.affected_object.prerequisite_git_commit_sha1 = None


class DeleteCodeImport(DeletionOperation):
    """Deletion operation that deletes a repository's import."""

    def __init__(self, code_import):
        DeletionOperation.__init__(
            self,
            code_import,
            msg("This is the import data for this repository."),
        )

    def __call__(self):
        getUtility(ICodeImportSet).delete(self.affected_object)


@implementer(IGitRepositorySet)
class GitRepositorySet:
    """See `IGitRepositorySet`."""

    def new(
        self,
        repository_type,
        registrant,
        owner,
        target,
        name,
        information_type=None,
        date_created=DEFAULT,
        description=None,
        with_hosting=False,
        async_hosting=False,
        status=GitRepositoryStatus.AVAILABLE,
        clone_from_repository=None,
    ):
        """See `IGitRepositorySet`."""
        namespace = get_git_namespace(target, owner)
        return namespace.createRepository(
            repository_type,
            registrant,
            name,
            information_type=information_type,
            date_created=date_created,
            description=description,
            with_hosting=with_hosting,
            async_hosting=async_hosting,
            status=status,
            clone_from_repository=clone_from_repository,
        )

    def getByID(self, user, id):
        """See `IGitRepositorySet`."""
        repository = getUtility(IGitLookup).get(id)
        if repository is None:
            return None
        # removeSecurityProxy is safe here since we're explicitly performing
        # a permission check.
        if removeSecurityProxy(repository).visibleByUser(user):
            return repository
        return None

    def getByPath(self, user, path):
        """See `IGitRepositorySet`."""
        repository, extra_path = getUtility(IGitLookup).getByPath(path)
        if repository is None or extra_path:
            return None
        # removeSecurityProxy is safe here since we're explicitly performing
        # a permission check.
        if removeSecurityProxy(repository).visibleByUser(user):
            return repository
        return None

    def getRepositories(
        self,
        user,
        target=None,
        order_by=GitListingSort.MOST_RECENTLY_CHANGED_FIRST,
        modified_since_date=None,
    ):
        """See `IGitRepositorySet`."""
        if target is not None:
            collection = IGitCollection(target)
        else:
            collection = getUtility(IAllGitRepositories)
        collection = collection.visibleByUser(user)
        if modified_since_date is not None:
            collection = collection.modifiedSince(modified_since_date)
        return collection.getRepositories(eager_load=True, sort_by=order_by)

    def countRepositoriesForRepack(self):
        """See `IGitRepositorySet`."""
        repos = (
            IStore(GitRepository)
            .find(
                GitRepository,
                Or(
                    GitRepository.loose_object_count
                    >= config.codehosting.loose_objects_threshold,
                    GitRepository.pack_count
                    >= config.codehosting.packs_threshold,
                ),
                GitRepository.status == GitRepositoryStatus.AVAILABLE,
            )
            .order_by(GitRepository.id)
        )
        return repos.count()

    def getRepositoryVisibilityInfo(self, user, person, repository_names):
        """See `IGitRepositorySet`."""
        if user is None:
            return dict()
        lookup = getUtility(IGitLookup)
        visible_repositories = []
        for name in repository_names:
            repository = lookup.getByUniqueName(name)
            try:
                if (
                    repository is not None
                    and repository.visibleByUser(user)
                    and repository.visibleByUser(person)
                ):
                    visible_repositories.append(repository.unique_name)
            except Unauthorized:
                # We don't include repositories user cannot see.
                pass
        return {
            "person_name": person.displayname,
            "visible_repositories": visible_repositories,
        }

    def getDefaultRepository(self, target):
        """See `IGitRepositorySet`."""
        clauses = [GitRepository.target_default == True]
        if IProduct.providedBy(target):
            clauses.append(GitRepository.project == target)
        elif IDistributionSourcePackage.providedBy(target):
            clauses.append(GitRepository.distribution == target.distribution)
            clauses.append(
                GitRepository.sourcepackagename == target.sourcepackagename
            )
        elif IOCIProject.providedBy(target):
            clauses.append(GitRepository.oci_project == target)
        else:
            raise GitTargetError(
                "Personal repositories cannot be defaults for any target."
            )
        return IStore(GitRepository).find(GitRepository, *clauses).one()

    def getDefaultRepositoryForOwner(self, owner, target):
        """See `IGitRepositorySet`."""
        clauses = [
            GitRepository.owner == owner,
            GitRepository.owner_default == True,
        ]
        if IProduct.providedBy(target):
            clauses.append(GitRepository.project == target)
        elif IDistributionSourcePackage.providedBy(target):
            clauses.append(GitRepository.distribution == target.distribution)
            clauses.append(
                GitRepository.sourcepackagename == target.sourcepackagename
            )
        elif IOCIProject.providedBy(target):
            clauses.append(GitRepository.oci_project == target)
        else:
            raise GitTargetError(
                "Personal repositories cannot be defaults for any target."
            )
        return IStore(GitRepository).find(GitRepository, *clauses).one()

    def setDefaultRepository(self, target, repository):
        """See `IGitRepositorySet`."""
        if IPerson.providedBy(target):
            raise GitTargetError(
                "Cannot set a default Git repository for a person, only "
                "for a project or a package."
            )
        if not (
            check_permission("launchpad.Edit", target)
            or (
                IDistributionSourcePackage.providedBy(target)
                and getUtility(ILaunchBag).user
                and getUtility(ILaunchBag).user.inTeam(
                    target.distribution.code_admin
                )
            )
        ):
            raise Unauthorized(
                "You cannot set the default Git repository for %s."
                % target.display_name
            )
        if repository is not None and repository.target != target:
            raise GitTargetError(
                "Cannot set default Git repository to one attached to "
                "another target."
            )
        previous = self.getDefaultRepository(target)
        if previous != repository:
            if previous is not None:
                previous.setTargetDefault(False)
            if repository is not None:
                repository.setTargetDefault(True)

    def setDefaultRepositoryForOwner(self, owner, target, repository, user):
        """See `IGitRepositorySet`."""
        if not user.inTeam(owner):
            if owner.is_team:
                raise Unauthorized(
                    "%s is not a member of %s"
                    % (user.displayname, owner.displayname)
                )
            else:
                raise Unauthorized(
                    "%s cannot set a default Git repository for %s"
                    % (user.displayname, owner.displayname)
                )
        if IPerson.providedBy(target):
            raise GitTargetError(
                "Cannot set a default Git repository for a person, only "
                "for a project or a package."
            )
        if repository is not None:
            if repository.target != target:
                raise GitTargetError(
                    "Cannot set default Git repository to one attached to "
                    "another target."
                )
            if repository.owner != owner:
                raise GitTargetError(
                    "Cannot set a person's default Git repository to one "
                    "owned by somebody else."
                )
        previous = self.getDefaultRepositoryForOwner(owner, target)
        if previous != repository:
            if previous is not None:
                previous.setOwnerDefault(False)
            if repository is not None:
                repository.setOwnerDefault(True)

    def empty_list(self):
        """See `IGitRepositorySet`."""
        return []

    @staticmethod
    def preloadDefaultRepositoriesForProjects(projects):
        repositories = bulk.load_referencing(
            GitRepository,
            projects,
            ["project_id"],
            extra_conditions=[GitRepository.target_default == True],
        )
        return {
            repository.project_id: repository for repository in repositories
        }

    def getRepositoriesForRepack(self, limit=50):
        """See `IGitRepositorySet`."""
        repos = (
            IStore(GitRepository)
            .find(
                GitRepository,
                Or(
                    GitRepository.loose_object_count
                    >= config.codehosting.loose_objects_threshold,
                    GitRepository.pack_count
                    >= config.codehosting.packs_threshold,
                ),
                GitRepository.status == GitRepositoryStatus.AVAILABLE,
            )
            .order_by(Desc(GitRepository.loose_object_count))
            .config(limit=limit)
        )

        return list(repos)


@implementer(IMacaroonIssuer)
class GitRepositoryMacaroonIssuer(MacaroonIssuerBase):
    identifier = "git-repository"
    allow_multiple = {"lp.expires"}

    _timestamp_format = "%Y-%m-%dT%H:%M:%S.%f"

    def __init__(self):
        super().__init__()
        self.checkers = {
            "lp.principal.openid-identifier": self.verifyOpenIDIdentifier,
            "lp.expires": self.verifyExpires,
        }

    @property
    def _root_secret(self):
        secret = config.codehosting.git_macaroon_secret_key
        if not secret:
            raise RuntimeError(
                "codehosting.git_macaroon_secret_key not configured."
            )
        return secret

    def checkIssuingContext(self, context, user=None, **kwargs):
        """See `MacaroonIssuerBase`.

        For issuing, the context is an `IGitRepository`.
        """
        if user is None:
            raise Unauthorized(
                "git-repository macaroons may only be issued for a logged-in "
                "user."
            )
        if not IGitRepository.providedBy(context):
            raise ValueError("Cannot handle context %r." % context)
        return context.id

    def issueMacaroon(self, context, user=None, **kwargs):
        """See `IMacaroonIssuer`."""
        macaroon = super().issueMacaroon(context, user=user, **kwargs)
        naked_account = removeSecurityProxy(user).account
        macaroon.add_first_party_caveat(
            "lp.principal.openid-identifier "
            + naked_account.openid_identifiers.any().identifier
        )
        store = IStore(GitRepository)
        # XXX cjwatson 2019-04-09: Expire macaroons after the number of
        # seconds given in the code.git.access_token_expiry feature flag,
        # defaulting to a week.  This isn't very flexible, but for now it
        # saves on having to implement macaroon persistence in order that
        # users can revoke them.
        expiry_seconds_str = getFeatureFlag("code.git.access_token_expiry")
        if expiry_seconds_str is None:
            expiry_seconds = 60 * 60 * 24 * 7
        else:
            expiry_seconds = int(expiry_seconds_str)
        expiry = get_transaction_timestamp(store) + timedelta(
            seconds=expiry_seconds
        )
        macaroon.add_first_party_caveat(
            "lp.expires " + expiry.strftime(self._timestamp_format)
        )
        return macaroon

    def checkVerificationContext(self, context, **kwargs):
        """See `MacaroonIssuerBase`.

        For verification, the context is an `IGitRepository`.
        """
        if not IGitRepository.providedBy(context):
            raise ValueError("Cannot handle context %r." % context)
        return context

    def verifyPrimaryCaveat(self, verified, caveat_value, context, **kwargs):
        """See `MacaroonIssuerBase`."""
        if context is None:
            # We're only verifying that the macaroon could be valid for some
            # context.
            return True
        return caveat_value == str(context.id)

    def verifyOpenIDIdentifier(
        self, verified, caveat_value, context, user=None, **kwargs
    ):
        """Verify an lp.principal.openid-identifier caveat."""
        try:
            account = getUtility(IAccountSet).getByOpenIDIdentifier(
                caveat_value
            )
        except LookupError:
            return False
        ok = (
            IPerson.providedBy(user)
            and user.account_status == AccountStatus.ACTIVE
            and user.account == account
        )
        if ok:
            verified.user = user
        return ok

    def verifyExpires(self, verified, caveat_value, context, **kwargs):
        """Verify an lp.expires caveat."""
        try:
            expires = datetime.strptime(
                caveat_value, self._timestamp_format
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        store = IStore(GitRepository)
        return get_transaction_timestamp(store) < expires


def get_git_repository_privacy_filter(user, repository_class=GitRepository):
    public_filter = repository_class.information_type.is_in(
        PUBLIC_INFORMATION_TYPES
    )

    if user is None:
        return [public_filter]

    artifact_grant_query = Coalesce(
        ArrayIntersects(
            SQL("%s.access_grants" % repository_class.__storm_table__),
            Select(
                ArrayAgg(TeamParticipation.team_id),
                tables=TeamParticipation,
                where=(TeamParticipation.person == user),
            ),
        ),
        False,
    )

    policy_grant_query = Coalesce(
        ArrayIntersects(
            Array(SQL("%s.access_policy" % repository_class.__storm_table__)),
            Select(
                ArrayAgg(AccessPolicyGrant.policy_id),
                tables=(
                    AccessPolicyGrant,
                    Join(
                        TeamParticipation,
                        TeamParticipation.team_id
                        == AccessPolicyGrant.grantee_id,
                    ),
                ),
                where=(TeamParticipation.person == user),
            ),
        ),
        False,
    )

    return [Or(public_filter, artifact_grant_query, policy_grant_query)]
