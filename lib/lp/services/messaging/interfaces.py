# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Messaging interfaces."""

__all__ = [
    "MessagingException",
    "MessagingUnavailable",
]


class MessagingException(Exception):
    """Failure in messaging."""


class MessagingUnavailable(MessagingException):
    """Messaging systems are not available."""
