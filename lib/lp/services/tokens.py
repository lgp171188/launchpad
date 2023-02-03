# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Utility methods for random token generation."""

__all__ = [
    "create_token",
]

import random


def create_token(token_length):
    """Create a random token string.

    :param token_length: Specifies how long you want the token.
    """
    # Since tokens are, in general, user-visible, vowels are not included
    # below to prevent them from having curse/offensive words.
    characters = "0123456789bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ"
    return "".join(
        random.SystemRandom().choice(characters)
        for count in range(token_length)
    )
