# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Simple memoization decorator for functions and methods"""

__all__ = [
    'memoize',
    ]


class memoize:
    """Simple memoize decorator that vary on arguments.

    This decorator doesn't work with kwargs, nor mutable objects like lists
    or dicts as arguments.
    """
    def __init__(self, function):
        self.memo = {}
        self.function = function

    def __call__(self, *args):
        if args not in self.memo:
            self.memo[args] = self.function(*args)
        return self.memo[args]

    def clean_memo(self):
        self.memo = {}
