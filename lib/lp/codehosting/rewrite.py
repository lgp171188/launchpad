# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementation of the dynamic RewriteMap used to serve branches over HTTP.
"""

import time

from bzrlib import urlutils

from canonical.launchpad.webapp.interfaces import (
        IStoreSelector, MAIN_STORE, SLAVE_FLAVOR)
from zope.component import getUtility
from lp.code.model.branch import Branch
from lp.codehosting.vfs import branch_id_to_path

from canonical.config import config

__all__ = ['BranchRewriter']


class BranchRewriter:

    def __init__(self, logger, _now=None):
        """

        :param logger: Logger than messages about what the rewriter is doing
            will be sent to.
        :param proxy: A blocking proxy for a branchfilesystem endpoint.
        """
        if _now is None:
            self._now = time.time
        else:
            self._now = _now
        self.logger = logger
        self.store = getUtility(IStoreSelector).get(MAIN_STORE, SLAVE_FLAVOR)
        self._cache = {}
        self._expiry_time = 10.0

    def _codebrowse_url(self, path):
        return urlutils.join(
            config.codehosting.internal_codebrowse_root,
            path)

    def _getBranchIdAndTrailingPath(self, location):
        """XXX Write me!"""
        parts = location[1:].split('/')
        prefixes = []
        for i in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:i])
            if prefix in self._cache:
                branch_id, inserted_time = self._cache[prefix]
                if self._now() < inserted_time + self._expiry_time:
                    trailing = location[len(prefix) + 1:]
                    return branch_id, trailing, "HIT"
            prefixes.append(prefix)
        result = self.store.find(
            Branch,
            Branch.unique_name.is_in(prefixes), Branch.private == False)
        try:
            branch_id, unique_name = result.values(
                Branch.id, Branch.unique_name).next()
        except StopIteration:
            return None, None, "MISS"
        self._cache[unique_name] = (branch_id, self._now())
        trailing = location[len(unique_name) + 1:]
        return branch_id, trailing, "MISS"

    def rewriteLine(self, resource_location):
        """Rewrite 'resource_location' to a more concrete location.

        We use the 'translatePath' BranchFileSystemClient method.  There are
        three cases:

         (1) The request is for something within the .bzr directory of a
             branch.

             In this case we rewrite the request to the location from which
             branches are served by ID.

         (2) The request is for something within a branch, but not the .bzr
             directory.

             In this case, we hand the request off to codebrowse.

         (3) The branch is not found.  Two sub-cases: the request is for a
             product control directory or the we don't know how to translate
             the path.

             In both these cases we return 'NULL' which indicates to Apache
             that we don't know how to rewrite the request (and so it should
             go on to generate a 404 response).

        Other errors are allowed to propagate, on the assumption that the
        caller will catch and log them.
        """
        # Codebrowse generates references to its images and stylesheets
        # starting with "/static", so pass them on unthinkingly.
        T = time.time()
        cached = None
        if resource_location.startswith('/static/'):
            r = self._codebrowse_url(resource_location)
            cached = 'N/A'
        else:
            branch_id, trailing, cached = self._getBranchIdAndTrailingPath(
                resource_location)
            if branch_id is None:
                r = self._codebrowse_url(resource_location)
            else:
                if trailing.startswith('/.bzr'):
                    r = urlutils.join(
                        config.codehosting.internal_branch_by_id_root,
                        branch_id_to_path(branch_id), trailing[1:])
                else:
                    r = self._codebrowse_url(resource_location)
        self.logger.info(
            "%r -> %r (%fs, cache: %s)",
            resource_location, r, time.time() - T, cached)
        return r
