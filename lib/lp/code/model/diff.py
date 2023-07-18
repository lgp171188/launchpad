# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementation classes for IDiff, etc."""

__all__ = [
    "Diff",
    "IncrementalDiff",
    "PreviewDiff",
]

import io
import json
import sys
from contextlib import ExitStack
from datetime import timezone
from operator import attrgetter
from uuid import uuid1

import six
from breezy import trace
from breezy.diff import show_diff_trees
from breezy.merge import Merge3Merger
from breezy.patches import Patch, parse_patches
from breezy.plugins.difftacular.generate_diff import diff_ignore_branches
from lazr.delegates import delegate_to
from storm.locals import DateTime, Int, Reference, Unicode
from zope.component import getUtility
from zope.error.interfaces import IErrorReportingUtility
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.code.interfaces.diff import IDiff, IIncrementalDiff, IPreviewDiff
from lp.code.interfaces.githosting import IGitHostingClient
from lp.codehosting.bzrutils import read_locked
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.librarian.interfaces import ILibraryFileAliasSet
from lp.services.librarian.interfaces.client import (
    LIBRARIAN_SERVER_DEFAULT_TIMEOUT,
)
from lp.services.propertycache import get_property_cache
from lp.services.timeout import get_default_timeout_function, reduced_timeout


@implementer(IDiff)
class Diff(StormBase):
    """See `IDiff`."""

    __storm_table__ = "Diff"

    id = Int(primary=True)

    diff_text_id = Int(name="diff_text", allow_none=True)
    diff_text = Reference(diff_text_id, "LibraryFileAlias.id")

    diff_lines_count = Int(name="diff_lines_count", allow_none=True)

    _diffstat = Unicode(name="diffstat", allow_none=True)

    @property
    def diffstat(self):
        if self._diffstat is None:
            return None
        return {
            key: tuple(value)
            for key, value in json.loads(self._diffstat).items()
        }

    @diffstat.setter
    def diffstat(self, diffstat):
        if diffstat is None:
            self._diffstat = None
            return
        # diffstats should be mappings of path to line counts.
        assert isinstance(diffstat, dict)
        self._diffstat = json.dumps(diffstat)

    added_lines_count = Int(name="added_lines_count", allow_none=True)

    removed_lines_count = Int(name="removed_lines_count", allow_none=True)

    def __init__(
        self,
        diff_text=None,
        diff_lines_count=None,
        diffstat=None,
        added_lines_count=None,
        removed_lines_count=None,
    ):
        super().__init__()
        self.diff_text = diff_text
        self.diff_lines_count = diff_lines_count
        self.diffstat = diffstat
        self.added_lines_count = added_lines_count
        self.removed_lines_count = removed_lines_count

    @property
    def text(self):
        if self.diff_text is None:
            return ""
        else:
            with reduced_timeout(
                0.01, webapp_max=2.0, default=LIBRARIAN_SERVER_DEFAULT_TIMEOUT
            ):
                timeout = get_default_timeout_function()()
            self.diff_text.open(timeout)
            try:
                diff_bytes = self.diff_text.read(config.diff.max_read_size)
                # Attempt to decode the diff somewhat intelligently,
                # although this may not be a great heuristic.
                try:
                    return diff_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    return diff_bytes.decode("windows-1252", "replace")
            finally:
                self.diff_text.close()

    @property
    def oversized(self):
        # If the size of the content of the librarian file is over the
        # config.diff.max_read_size, then we have an oversized diff.
        if self.diff_text is None:
            return False
        diff_size = self.diff_text.content.filesize
        return diff_size > config.diff.max_read_size

    @classmethod
    def mergePreviewFromBranches(
        cls,
        source_branch,
        source_revision,
        target_branch,
        prerequisite_branch=None,
    ):
        """Generate a merge preview diff from the supplied branches.

        :param source_branch: The branch that will be merged.
        :param source_revision: The revision_id of the revision that will be
            merged.
        :param target_branch: The branch that the source will merge into.
        :param prerequisite_branch: The branch that should be merged before
            merging the source.
        :return: A tuple of (`Diff`, `ConflictList`) for a merge preview.
        """
        cleanups = []
        try:
            for branch in [source_branch, target_branch, prerequisite_branch]:
                if branch is not None:
                    branch.lock_read()
                    cleanups.append(branch.unlock)
            merge_target = target_branch.basis_tree()
            if prerequisite_branch is not None:
                prereq_revision = cls._getLCA(
                    source_branch, source_revision, prerequisite_branch
                )
                from_tree, _ignored_conflicts = cls._getMergedTree(
                    prerequisite_branch,
                    prereq_revision,
                    target_branch,
                    merge_target,
                    cleanups,
                )
            else:
                from_tree = merge_target
            to_tree, conflicts = cls._getMergedTree(
                source_branch,
                source_revision,
                target_branch,
                merge_target,
                cleanups,
            )
            return cls.fromTrees(from_tree, to_tree), conflicts
        finally:
            for cleanup in reversed(cleanups):
                cleanup()

    @classmethod
    def _getMergedTree(
        cls,
        source_branch,
        source_revision,
        target_branch,
        merge_target,
        cleanups,
    ):
        """Return a tree that is the result of a merge.

        :param source_branch: The branch to merge.
        :param source_revision: The revision_id of the revision to merge.
        :param target_branch: The branch to merge into.
        :param merge_target: The tree to merge into.
        :param cleanups: A list of cleanup operations to run when all
            operations are complete.  This will be appended to.
        :return: a tuple of a tree and the resulting conflicts.
        """
        lca = cls._getLCA(source_branch, source_revision, target_branch)
        merge_base = source_branch.repository.revision_tree(lca)
        merge_source = source_branch.repository.revision_tree(source_revision)
        merger = Merge3Merger(
            merge_target,
            merge_target,
            merge_base,
            merge_source,
            this_branch=target_branch,
            do_merge=False,
        )

        def dummy_warning(self, *args, **kwargs):
            pass

        real_warning = trace.warning
        trace.warning = dummy_warning
        try:
            transform = merger.make_preview_transform()
        finally:
            trace.warning = real_warning
        cleanups.append(transform.finalize)
        return transform.get_preview_tree(), merger.cooked_conflicts

    @staticmethod
    def _getLCA(source_branch, source_revision, target_branch):
        """Return the unique LCA of two branches.

        :param source_branch: The branch to merge.
        :param source_revision: The revision of the source branch.
        :param target_branch: The branch to merge into.
        """
        graph = target_branch.repository.get_graph(source_branch.repository)
        return graph.find_unique_lca(
            source_revision, target_branch.last_revision()
        )

    @classmethod
    def fromTrees(klass, from_tree, to_tree, filename=None):
        """Create a Diff from two Bazaar trees.

        :from_tree: The old tree in the diff.
        :to_tree: The new tree in the diff.
        """
        diff_content = io.BytesIO()
        show_diff_trees(
            from_tree, to_tree, diff_content, old_label="", new_label=""
        )
        return klass.fromFileAtEnd(diff_content, filename)

    @classmethod
    def fromFileAtEnd(cls, diff_content, filename=None):
        """Make a Diff from a file object that is currently at its end."""
        size = diff_content.tell()
        diff_content.seek(0)
        return cls.fromFile(diff_content, size, filename)

    @classmethod
    def fromFile(
        cls, diff_content, size, filename=None, strip_prefix_segments=0
    ):
        """Create a Diff from a textual diff.

        :diff_content: The diff text, as `bytes`.
        :size: The number of bytes in the diff text.
        :filename: The filename to store the content with.  Randomly generated
            if not supplied.
        """
        if size == 0:
            diff_text = None
            diff_lines_count = 0
            diff_content_bytes = ""
        else:
            if filename is None:
                filename = str(uuid1()) + ".txt"
            diff_text = getUtility(ILibraryFileAliasSet).create(
                filename, size, diff_content, "text/x-diff", restricted=True
            )
            diff_content.seek(0)
            diff_content_bytes = diff_content.read(size)
            diff_lines_count = len(diff_content_bytes.strip().split(b"\n"))
        try:
            diffstat = cls.generateDiffstat(
                diff_content_bytes, strip_prefix_segments=strip_prefix_segments
            )
        except Exception:
            getUtility(IErrorReportingUtility).raising(sys.exc_info())
            # Set the diffstat to be empty.
            diffstat = None
            added_lines_count = None
            removed_lines_count = None
        else:
            added_lines_count = 0
            removed_lines_count = 0
            for path, (added, removed) in diffstat.items():
                added_lines_count += added
                removed_lines_count += removed
        diff = cls(
            diff_text=diff_text,
            diff_lines_count=diff_lines_count,
            diffstat=diffstat,
            added_lines_count=added_lines_count,
            removed_lines_count=removed_lines_count,
        )
        return IStore(Diff).add(diff)

    @staticmethod
    def generateDiffstat(diff_bytes, strip_prefix_segments=0):
        """Generate statistics about the provided diff.

        :param diff_bytes: A unified diff, as bytes.
        :param strip_prefix_segments: Strip the smallest prefix containing
            this many leading slashes from each file name found in the patch
            file, as with "patch -p".
        :return: A map of {filename: (added_line_count, removed_line_count)}
        """
        file_stats = {}
        # Set allow_dirty, so we don't raise exceptions for dirty patches.
        patches = parse_patches(diff_bytes.splitlines(True), allow_dirty=True)
        for patch in patches:
            if not isinstance(patch, Patch):
                continue
            path = patch.newname.decode("UTF-8", "replace").split("\t")[0]
            if strip_prefix_segments:
                path = path.split("/", strip_prefix_segments)[-1]
            file_stats[path] = tuple(patch.stats_values()[:2])
        return file_stats

    @classmethod
    def generateIncrementalDiff(
        cls, old_revision, new_revision, source_branch, ignore_branches
    ):
        """Return a Diff whose contents are an incremental diff.

        The Diff's contents will show the changes made between old_revision
        and new_revision, except those changes introduced by the
        ignore_branches.

        :param old_revision: The `Revision` to show changes from.
        :param new_revision: The `Revision` to show changes to.
        :param source_branch: The bzr branch containing these revisions.
        :param ignore_brances: A collection of branches to ignore merges from.
        :return: a `Diff`.
        """
        diff_content = io.BytesIO()
        with ExitStack() as stack:
            for branch in [source_branch] + ignore_branches:
                stack.enter_context(read_locked(branch))
            diff_ignore_branches(
                source_branch,
                ignore_branches,
                old_revision.revision_id.encode(),
                new_revision.revision_id.encode(),
                diff_content,
            )
        return cls.fromFileAtEnd(diff_content)


@implementer(IIncrementalDiff)
@delegate_to(IDiff, context="diff")
class IncrementalDiff(StormBase):
    """See `IIncrementalDiff."""

    __storm_table__ = "IncrementalDiff"

    id = Int(primary=True, allow_none=False)

    diff_id = Int(name="diff", allow_none=False)

    diff = Reference(diff_id, "Diff.id")

    branch_merge_proposal_id = Int(
        name="branch_merge_proposal", allow_none=False
    )

    branch_merge_proposal = Reference(
        branch_merge_proposal_id, "BranchMergeProposal.id"
    )

    old_revision_id = Int(name="old_revision", allow_none=False)

    old_revision = Reference(old_revision_id, "Revision.id")

    new_revision_id = Int(name="new_revision", allow_none=False)

    new_revision = Reference(new_revision_id, "Revision.id")


@implementer(IPreviewDiff)
@delegate_to(IDiff, context="diff")
class PreviewDiff(StormBase):
    """See `IPreviewDiff`."""

    __storm_table__ = "PreviewDiff"

    id = Int(primary=True)

    diff_id = Int(name="diff")
    diff = Reference(diff_id, "Diff.id")

    source_revision_id = Unicode(allow_none=False)

    target_revision_id = Unicode(allow_none=False)

    prerequisite_revision_id = Unicode(name="dependent_revision_id")

    branch_merge_proposal_id = Int(
        name="branch_merge_proposal", allow_none=False
    )
    branch_merge_proposal = Reference(
        branch_merge_proposal_id, "BranchMergeProposal.id"
    )

    date_created = DateTime(
        name="date_created",
        default=UTC_NOW,
        allow_none=False,
        tzinfo=timezone.utc,
    )

    conflicts = Unicode()

    @property
    def title(self):
        """See `IPreviewDiff`."""
        bmp = self.branch_merge_proposal
        # XXX cprov 20140224: we fallback to revision_ids when the
        # diff was generated for absent branch revisions (e.g. the source
        # or target branch was overwritten). Which means some entries for
        # the same BMP may have much wider titles depending on the
        # branch history. It is particularly bad for rendering the diff
        # navigator 'select' widget in the UI.
        if bmp.source_branch is not None:
            source_revision = bmp.source_branch.getBranchRevision(
                revision_id=self.source_revision_id
            )
            if source_revision and source_revision.sequence:
                source_rev = "r{}".format(source_revision.sequence)
            else:
                source_rev = self.source_revision_id
            target_revision = bmp.target_branch.getBranchRevision(
                revision_id=self.target_revision_id
            )
            if target_revision and target_revision.sequence:
                target_rev = "r{}".format(target_revision.sequence)
            else:
                target_rev = self.target_revision_id
        else:
            # For Git, we shorten to seven characters since that's usual.
            # We should perhaps shorten only as far as preserves uniqueness,
            # but that requires talking to the hosting service and it's
            # unlikely to be a problem in practice.
            source_rev = self.source_revision_id[:7]
            target_rev = self.target_revision_id[:7]

        return "{} into {}".format(source_rev, target_rev)

    @property
    def has_conflicts(self):
        return self.conflicts is not None and self.conflicts != ""

    @classmethod
    def fromBranchMergeProposal(cls, bmp):
        """Create a `PreviewDiff` from a `BranchMergeProposal`.

        Includes a diff from the source to the target.
        :param bmp: The `BranchMergeProposal` to generate a `PreviewDiff` for.
        :return: A `PreviewDiff`.
        """
        if bmp.source_branch is not None:
            source_branch = bmp.source_branch.getBzrBranch()
            source_revision = source_branch.last_revision()
            target_branch = bmp.target_branch.getBzrBranch()
            target_revision = target_branch.last_revision()
            if bmp.prerequisite_branch is not None:
                prerequisite_branch = bmp.prerequisite_branch.getBzrBranch()
            else:
                prerequisite_branch = None
            diff, conflicts = Diff.mergePreviewFromBranches(
                source_branch,
                source_revision,
                target_branch,
                prerequisite_branch,
            )
            preview = cls()
            preview.source_revision_id = source_revision.decode("utf-8")
            preview.target_revision_id = target_revision.decode("utf-8")
            preview.branch_merge_proposal = bmp
            preview.diff = diff
            preview.conflicts = "".join(
                str(conflict) + "\n" for conflict in conflicts
            )
        else:
            source_repository = bmp.source_git_repository
            target_repository = bmp.target_git_repository
            prerequisite_repository = bmp.prerequisite_git_repository
            path = target_repository.getInternalPath()
            if source_repository != target_repository:
                path += ":%s" % source_repository.getInternalPath()
            if (
                prerequisite_repository is not None
                and prerequisite_repository != source_repository
                and prerequisite_repository != target_repository
            ):
                path += ":%s" % prerequisite_repository.getInternalPath()
            response = getUtility(IGitHostingClient).getMergeDiff(
                path,
                bmp.target_git_commit_sha1,
                bmp.source_git_commit_sha1,
                prerequisite=bmp.prerequisite_git_commit_sha1,
            )
            conflicts = "".join(
                "Conflict in %s\n" % path for path in response["conflicts"]
            )
            preview = cls.create(
                bmp,
                response["patch"].encode("utf-8"),
                bmp.source_git_commit_sha1,
                bmp.target_git_commit_sha1,
                bmp.prerequisite_git_commit_sha1,
                conflicts,
                strip_prefix_segments=1,
            )
        del get_property_cache(bmp).preview_diffs
        del get_property_cache(bmp).preview_diff
        return preview

    @classmethod
    def create(
        cls,
        bmp,
        diff_content,
        source_revision_id,
        target_revision_id,
        prerequisite_revision_id,
        conflicts,
        strip_prefix_segments=0,
    ):
        """Create a PreviewDiff with specified values.

        :param bmp: The `BranchMergeProposal` this diff references.
        :param diff_content: The text of the diff, as bytes (or text, which
            will be encoded using UTF-8).
        :param source_revision_id: The revision_id of the source branch.
        :param target_revision_id: The revision_id of the target branch.
        :param prerequisite_revision_id: The revision_id of the prerequisite
            branch.
        :param conflicts: The conflicts, as text.
        :return: A `PreviewDiff` with specified values.
        """
        diff_content = six.ensure_binary(diff_content)
        filename = str(uuid1()) + ".txt"
        size = len(diff_content)
        diff = Diff.fromFile(
            io.BytesIO(diff_content),
            size,
            filename,
            strip_prefix_segments=strip_prefix_segments,
        )

        preview = cls()
        preview.branch_merge_proposal = bmp
        preview.source_revision_id = source_revision_id
        preview.target_revision_id = target_revision_id
        preview.prerequisite_revision_id = prerequisite_revision_id
        preview.conflicts = conflicts
        preview.diff = diff

        return preview

    @property
    def stale(self):
        """See `IPreviewDiff`."""
        # A preview diff is stale if the revision ids used to make the diff
        # are different from the tips of the source or target branches.
        bmp = self.branch_merge_proposal
        get_id = attrgetter(
            "last_scanned_id" if bmp.source_branch else "commit_sha1"
        )
        if self.source_revision_id != get_id(
            bmp.merge_source
        ) or self.target_revision_id != get_id(bmp.merge_target):
            return True
        return (
            bmp.merge_prerequisite is not None
            and self.prerequisite_revision_id != get_id(bmp.merge_prerequisite)
        )

    def getFileByName(self, filename):
        """See `IPreviewDiff`."""
        if filename == "preview.diff" and self.diff_text is not None:
            return self.diff_text
        else:
            raise NotFoundError(filename)
