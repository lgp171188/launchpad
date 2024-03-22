# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for internal Git APIs."""

__all__ = [
    "IGitAPI",
    "IGitApplication",
]

from zope.interface import Interface

from lp.services.webapp.interfaces import ILaunchpadApplication


class IGitApplication(ILaunchpadApplication):
    """Git application root."""


class IGitAPI(Interface):
    """The Git XML-RPC interface to Launchpad.

    Published at "git" on the private XML-RPC server.

    The Git pack frontend uses this to translate user-visible paths to
    internal ones, and to notify Launchpad of ref changes.
    """

    def translatePath(path, permission, requester_id, can_authenticate):
        """Translate 'path' so that the Git pack frontend can access it.

        If the repository does not exist and write permission was requested,
        register a new repository if possible.

        :param path: The path being translated.  This should be a string
            representing an absolute path to a Git repository.
        :param permission: "read" or "write".
        :param requester_id: The database ID of the person requesting the
            path translation, or None for an anonymous request.
        :param can_authenticate: True if the frontend can request
            authentication, otherwise False.

        :returns: A `PathTranslationError` fault if 'path' cannot be
            translated; a `PermissionDenied` fault if the requester cannot
            see or create the repository; otherwise, a dict containing at
            least the following keys::
                "path", whose value is the repository's storage path;
                "writable", whose value is True if the requester can push to
                this repository, otherwise False.
        """

    def notify(translated_path, statistics, auth_params):
        """Notify of a change to the repository at 'translated_path'.

        :param translated_path: The translated path to the repository.  (We
            use translated paths here in order to avoid problems with
            repository names etc. being changed during a push.)
        :param statistics: a dict of {'loose_object_count', 'pack_count'}:
            the number of loose objects and packs for the repository.
        :param auth_params: A dictionary of authentication parameters.

        :returns: A `NotFound` fault if no repository can be found for
            'translated_path'; otherwise None.
        """

    def authenticateWithPassword(username, password):
        """Authenticate a user by username and password.

        This currently only works when using macaroon authentication.

        :returns: An `Unauthorized` fault if the username and password do
            not match; otherwise, a dict containing a "uid" (for a real
            user) or "user" (for internal services) key indicating the
            authenticated principal, and possibly "macaroon" with a macaroon
            that requires further authorisation by other methods.
        """

    def checkRefPermissions(translated_paths, ref_paths, auth_params):
        """Return a list of ref rules for a `user` in a `repository` that
        match the input refs.

        :returns: A list of rules for the user in the specified repository
        """

    def getMergeProposalURL(translated_path, branch, auth_params):
        """Return the URL for a merge proposal.

        When a `branch` that is not the default branch in a repository
        is pushed, the URL where the merge proposal for that branch can
        be opened will be generated and returned.

        :returns: The URL to register a merge proposal for the branch in the
            specified repository. A `GitRepositoryNotFound` fault is returned
            if no repository can be found for 'translated_path',
            or an `Unauthorized` fault for unauthorized push attempts.
        """

    def getMergeProposalInfo(translated_path, branch, auth_params):
        """Return the info (string) for a merge proposal.

        When a `branch` that is not the default branch in a repository
        is pushed, the URL where the merge proposal for that branch can
        be opened will be generated and returned if the merge proposal
        doesn't exist, otherwise the link of the existing merge proposal
        will be returned.

        :returns: A string explaining how to register a merge proposal
            for this branch, or pointing to an existing active merge
            proposal. A `GitRepositoryNotFound` fault is returned
            if no repository can be found for 'translated_path',
            or an `Unauthorized` fault for unauthorized push attempts.
        """

    def confirmRepoCreation(repository_id):
        """Confirm that repository creation.

        When code hosting finishes creating the repository locally,
        it should call back this method to confirm that the repository was
        created, and Launchpad should make the repository available for end
        users.

        :param repository_id: The database ID of the repository, provided by
                    translatePath call when repo creation is necessary.
        """

    def abortRepoCreation(repository_id):
        """Abort the creation of a repository, removing it from database.

        When code hosting fails to create a repository locally, it should
        call back this method to indicate that the operation failed and the
        repository should be removed from Launchpad's database.

        :param repository_id: The database ID of the repository, provided by
                    translatePath call when repo creation is necessary.
        """

    def updateRepackStats(translated_path, statistics):
        """Update the repack stats for the repository.

        When code hosting completes a repack asynchronously
        (Celery task), it will call back this method to
        indicate that the operation completed and that repack stats
        (loose_object_count, pack_count and date_last_scanned) for the
        repository should be updated in Launchpad's database.

        :param statistics: a dict of {'loose_object_count', 'pack_count'}:
            the number of loose objects and packs for the repository.

        :param translated_path: The translated path to the repository.  (We
            use translated paths here in order to avoid problems with
            repository names etc. being changed during a push.)
        """
