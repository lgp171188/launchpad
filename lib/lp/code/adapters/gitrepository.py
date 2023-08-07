# Copyright 2015-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Components and adapters related to Git repositories."""

__all__ = [
    "git_repository_for_distro_source_package",
    "git_repository_for_oci_project",
    "git_repository_for_person_distro_source_package",
    "git_repository_for_person_oci_project",
    "git_repository_for_person_product",
    "git_repository_for_project",
    "GitRepositoryDelta",
]

from lazr.lifecycle.objectdelta import ObjectDelta
from zope.component import getUtility
from zope.interface import implementer

from lp.code.interfaces.gitrepository import (
    IGitRepository,
    IGitRepositoryDelta,
    IGitRepositorySet,
)


def git_repository_for_project(project):
    """Adapt a project to a Git repository."""
    return getUtility(IGitRepositorySet).getDefaultRepository(project)


def git_repository_for_distro_source_package(distro_source_package):
    """Adapt a distribution source package to a Git repository."""
    return getUtility(IGitRepositorySet).getDefaultRepository(
        distro_source_package
    )


def git_repository_for_oci_project(oci_project):
    """Adapt an OCI project to a Git repository."""
    return getUtility(IGitRepositorySet).getDefaultRepository(oci_project)


def git_repository_for_person_product(person_product):
    """Adapt a PersonProduct to a Git repository."""
    return getUtility(IGitRepositorySet).getDefaultRepositoryForOwner(
        person_product.person, person_product.product
    )


def git_repository_for_person_distro_source_package(person_dsp):
    """Adapt a PersonDistributionSourcePackage to a Git repository."""
    return getUtility(IGitRepositorySet).getDefaultRepositoryForOwner(
        person_dsp.person, person_dsp.distro_source_package
    )


def git_repository_for_person_oci_project(person_oci_project):
    """Adapt a PersonOCIProject to a Git repository."""
    return getUtility(IGitRepositorySet).getDefaultRepositoryForOwner(
        person_oci_project.person, person_oci_project.oci_project
    )


@implementer(IGitRepositoryDelta)
class GitRepositoryDelta:
    """See `IGitRepositoryDelta`."""

    delta_values = ("name", "git_identity")

    new_values = ()

    interface = IGitRepository

    def __init__(
        self, repository, user, name=None, git_identity=None, activities=None
    ):
        self.repository = repository
        self.user = user

        self.name = name
        self.git_identity = git_identity
        self.activities = activities

    @classmethod
    def construct(klass, old_repository, new_repository, user):
        """Return a GitRepositoryDelta instance that encapsulates the changes.

        This method is primarily used by event subscription code to
        determine what has changed during an ObjectModifiedEvent.
        """
        delta = ObjectDelta(old_repository, new_repository)
        delta.recordNewAndOld(klass.delta_values)
        activities = list(
            new_repository.getActivity(
                changed_after=old_repository.date_last_modified
            )
        )
        if delta.changes or activities:
            changes = delta.changes
            changes["repository"] = new_repository
            changes["user"] = user
            changes["activities"] = activities

            return GitRepositoryDelta(**changes)
        else:
            return None
