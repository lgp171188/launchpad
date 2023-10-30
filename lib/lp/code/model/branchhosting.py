# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Communication with the Loggerhead API for Bazaar code hosting."""

__all__ = [
    "BranchHostingClient",
]

import json
import sys
from urllib.parse import quote, urljoin

import requests
from lazr.restful.utils import get_current_browser_request
from zope.interface import implementer

from lp.code.errors import BranchFileNotFound, BranchHostingFault
from lp.code.interfaces.branchhosting import IBranchHostingClient
from lp.code.interfaces.codehosting import BRANCH_ID_ALIAS_PREFIX
from lp.services.config import config
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.services.timeout import (
    TimeoutError,
    get_default_timeout_function,
    urlfetch,
)


class RequestExceptionWrapper(requests.RequestException):
    """A non-requests exception that occurred during a request."""


class InvalidRevisionException(Exception):
    """An exception thrown when a revision ID is not valid"""


@implementer(IBranchHostingClient)
class BranchHostingClient:
    """A client for the Bazaar Loggerhead API."""

    def __init__(self):
        self.endpoint = config.codehosting.internal_bzr_api_endpoint

    def _request(
        self, method, branch_id, quoted_tail, as_json=False, **kwargs
    ):
        """Make a request to the Loggerhead API."""
        # Fetch the current timeout before starting the timeline action,
        # since making a database query inside this action will result in an
        # OverlappingActionError.
        get_default_timeout_function()()
        timeline = get_request_timeline(get_current_browser_request())
        components = [BRANCH_ID_ALIAS_PREFIX, str(branch_id)]
        if as_json:
            components.append("+json")
        components.append(quoted_tail)
        path = "/" + "/".join(components)
        action = timeline.start(
            "branch-hosting-%s" % method, "%s %s" % (path, json.dumps(kwargs))
        )
        try:
            response = urlfetch(
                urljoin(self.endpoint, path), method=method, **kwargs
            )
        except TimeoutError:
            # Re-raise this directly so that it can be handled specially by
            # callers.
            raise
        except requests.RequestException:
            raise
        except Exception:
            _, val, tb = sys.exc_info()
            try:
                raise RequestExceptionWrapper(*val.args).with_traceback(tb)
            finally:
                # Avoid traceback reference cycles.
                del val, tb
        finally:
            action.finish()
        if as_json:
            if response.content:
                return response.json()
            else:
                return None
        else:
            return response.content

    def _get(self, branch_id, tail, **kwargs):
        return self._request("get", branch_id, tail, **kwargs)

    def _checkRevision(self, rev):
        """Check that a revision is well-formed.

        We don't have a lot of scope for validation here, since Bazaar
        allows revision IDs to be basically anything; but let's at least
        exclude / as an extra layer of defence against path traversal
        attacks.
        """
        if rev is not None and "/" in rev:
            raise InvalidRevisionException(
                "Revision ID '%s' is not well-formed." % rev
            )

    def getDiff(
        self, branch_id, new, old=None, context_lines=None, logger=None
    ):
        """See `IBranchHostingClient`."""
        self._checkRevision(old)
        self._checkRevision(new)
        try:
            if logger is not None:
                if old is None:
                    logger.info(
                        "Requesting diff for %s from parent of %s to %s"
                        % (branch_id, new, new)
                    )
                else:
                    logger.info(
                        "Requesting diff for %s from %s to %s"
                        % (branch_id, old, new)
                    )
            quoted_tail = "diff/%s" % quote(new, safe="")
            if old is not None:
                quoted_tail += "/%s" % quote(old, safe="")
            return self._get(
                branch_id,
                quoted_tail,
                as_json=False,
                params={"context_lines": context_lines},
            )
        except requests.RequestException as e:
            raise BranchHostingFault(
                "Failed to get diff from Bazaar branch: %s" % e
            )

    def getBlob(self, branch_id, path, rev=None, logger=None):
        """See `IBranchHostingClient`."""
        self._checkRevision(rev)
        try:
            if logger is not None:
                logger.info(
                    "Fetching file ID %s from branch %s" % (path, branch_id)
                )
            return self._get(
                branch_id,
                "download/%s/%s"
                % (quote(rev or "head:", safe=""), quote(path, safe="/")),
                as_json=False,
            )
        except requests.RequestException as e:
            if (
                e.response is not None
                and e.response.status_code == requests.codes.NOT_FOUND
            ):
                raise BranchFileNotFound(branch_id, filename=path, rev=rev)
            else:
                raise BranchHostingFault(
                    "Failed to get file from Bazaar branch: %s" % e
                )
