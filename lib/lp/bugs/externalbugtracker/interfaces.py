#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

from zope.interface import Interface


class IGitHubRateLimit(Interface):
    """Interface for rate-limit tracking for the GitHub Issues API."""

    def checkLimit(url, token=None):
        """A context manager that checks the remote host's rate limit.

        :param url: The URL being requested.
        :param token: If not None, an OAuth token to use as authentication
            to the remote host when asking it for the current rate limit.
        :return: A suitable `Authorization` header (from the context
            manager's `__enter__` method).
        :raises GitHubExceededRateLimit: if the rate limit was exceeded.
        """

    def clearCache():
        """Forget any cached rate limits."""
