# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Generic Python utilities.

Functions, lists and so forth. Nothing here that does system calls or network
stuff.
"""

__all__ = [
    "AutoDecorateMetaClass",
    "CachingIterator",
    "decorate_with",
    "docstring_dedent",
    "file_exists",
    "iter_chunks",
    "iter_split",
    "load_bz2_pickle",
    "obfuscate_email",
    "obfuscate_structure",
    "re_email_address",
    "round_half_up",
    "sanitise_urls",
    "save_bz2_pickle",
    "seconds_since_epoch",
    "text_delta",
    "traceback_info",
    "utc_now",
    "value_string",
]

import bz2
import decimal
import os
import pickle
import re
import sys
from datetime import datetime, timezone
from itertools import islice, tee
from textwrap import dedent
from types import FunctionType

from lazr.enum import BaseItem
from twisted.python.util import mergeFunctionMetadata
from zope.security.proxy import isinstance as zope_isinstance


class AutoDecorateMetaClass(type):
    """
    AutoDecorateMetaClass is a metaclass that can be used to make a class
    implicitly wrap all of its methods with one or more decorators.

    Usage::

        class A(metaclass=AutoDecorateMetaClass):
            __decorators = (...)

    """

    def __new__(mcs, class_name, bases, class_dict):
        class_dict = dict(class_dict)
        decorators = class_dict.pop(f"_{class_name}__decorators", None)
        if decorators is not None:
            for name, value in class_dict.items():
                if type(value) == FunctionType:
                    for decorator in decorators:
                        value = decorator(value)
                        assert callable(
                            value
                        ), "Decorator {} didn't return a callable.".format(
                            repr(decorator)
                        )
                    class_dict[name] = value
        return type.__new__(mcs, class_name, bases, class_dict)


def iter_split(string, splitter, splits=None):
    """Iterate over ways to split 'string' in two with 'splitter'.

    If 'string' is empty, then yield nothing. Otherwise, yield tuples like
    ('a/b/c', ''), ('a/b', '/c'), ('a', '/b/c') for a string 'a/b/c' and a
    splitter '/'.

    The tuples are yielded such that the first result has everything in the
    first tuple. With each iteration, the first element gets smaller and the
    second gets larger. It stops iterating just before it would have to yield
    ('', 'a/b/c').

    Splits, if specified, is an iterable of splitters to split the string at.
    """
    if string == "":
        return
    tokens = string.split(splitter)
    if splits is None:
        splits = reversed(range(1, len(tokens) + 1))
    for i in splits:
        first = splitter.join(tokens[:i])
        yield first, string[len(first) :]


def iter_chunks(iterable, size):
    """Iterate over `iterable` in chunks of size `size`.

    I'm amazed this isn't in itertools (mwhudson).
    """
    iterable = iter(iterable)
    while True:
        chunk = tuple(islice(iterable, size))
        if not chunk:
            break
        yield chunk


def value_string(item):
    """Return a unicode string representing value.

    This text is special cased for enumerated types.
    """
    if item is None:
        return "(not set)"
    elif zope_isinstance(item, BaseItem):
        return item.title
    elif zope_isinstance(item, bytes):
        return item.decode()
    else:
        return str(item)


def text_delta(instance_delta, delta_names, state_names, interface):
    """Return a textual delta for a Delta object.

    A list of strings is returned.

    Only modified members of the delta will be shown.

    :param instance_delta: The delta to generate a textual representation of.
    :param delta_names: The names of all members to show changes to.
    :param state_names: The names of all members to show only the new state
        of.
    :param interface: The Zope interface that the input delta compared.
    """
    output = []
    indent = " " * 4

    # Fields for which we have old and new values.
    for field_name in delta_names:
        delta = getattr(instance_delta, field_name, None)
        if delta is None:
            continue
        title = interface[field_name].title
        old_item = value_string(delta["old"])
        new_item = value_string(delta["new"])
        output.append("%s%s: %s => %s" % (indent, title, old_item, new_item))
    for field_name in state_names:
        delta = getattr(instance_delta, field_name, None)
        if delta is None:
            continue
        title = interface[field_name].title
        if output:
            output.append("")
        output.append("%s changed to:\n\n%s" % (title, delta))
    return "\n".join(output)


class CachingIterator:
    """Remember the items extracted from the iterator for the next iteration.

    Some generators and iterators are expensive to calculate, like calculating
    the merge sorted revision graph for a bazaar branch, so you don't want to
    call them too often.  Rearranging the code so it doesn't call the
    expensive iterator can make the code awkward.  This class provides a way
    to have the iterator called once, and the results stored.  The results
    can then be iterated over again, and more values retrieved from the
    iterator if necessary.
    """

    def __init__(self, iterator_factory):
        self.iterator_factory = iterator_factory
        self.iterator = None

    def __iter__(self):
        if self.iterator is None:
            self.iterator = self.iterator_factory()
        # Teeing an iterator previously returned by tee won't cause heat
        # death. See tee_copy in itertoolsmodule.c in the Python source.
        self.iterator, iterator = tee(self.iterator)
        return iterator


def decorate_with(context_factory, *args, **kwargs):
    """Create a decorator that runs decorated functions with 'context'."""

    def decorator(function):
        def decorated(*a, **kw):
            with context_factory(*args, **kwargs):
                return function(*a, **kw)

        return mergeFunctionMetadata(function, decorated)

    return decorator


def docstring_dedent(s):
    """Remove leading indentation from a doc string.

    Since the first line doesn't have indentation, split it off, dedent, and
    then reassemble.
    """
    # Make sure there is at least one newline so the split works.
    first, rest = (s + "\n").split("\n", 1)
    return (first + "\n" + dedent(rest)).strip()


def file_exists(filename):
    """Does `filename` exist?"""
    return os.access(filename, os.F_OK)


def traceback_info(info):
    """Set `__traceback_info__` in the caller's locals.

    This is more aesthetically pleasing that assigning to __traceback_info__,
    but it more importantly avoids spurious lint warnings about unused local
    variables, and helps to avoid typos.
    """
    sys._getframe(1).f_locals["__traceback_info__"] = info


def utc_now():
    """Return a timezone-aware timestamp for the current time."""
    return datetime.now(tz=timezone.utc)


_epoch = datetime.fromtimestamp(0, tz=timezone.utc)


def seconds_since_epoch(dt):
    """Express a `datetime` as the number of seconds since the Unix epoch."""
    return (dt - _epoch).total_seconds()


# This is a regular expression that matches email address embedded in
# text. It is not RFC 2821 compliant, nor does it need to be. This
# expression strives to identify probable email addresses so that they
# can be obfuscated when viewed by unauthenticated users. See
# http://www.email-unlimited.com/stuff/email_address_validator.htm

# localnames do not have [&?%!@<>,;:`|{}()#*^~ ] in practice
# (regardless of RFC 2821) because they conflict with other systems.
# See https://lists.ubuntu.com
#     /mailman/private/launchpad-reviews/2007-June/006081.html

# This version of the re is more than 5x faster that the original
# version used in ftest/test_tales.testObfuscateEmail.
re_email_address = re.compile(
    r"""
    \b[a-zA-Z0-9._/="'+-]{1,64}@  # The localname.
    [a-zA-Z][a-zA-Z0-9-]{1,63}    # The hostname.
    \.[a-zA-Z0-9.-]{1,251}\b      # Dot starts one or more domains.
    """,
    re.VERBOSE,
)  # ' <- font-lock turd


def obfuscate_email(text_to_obfuscate, replacement=None):
    """Obfuscate an email address.

    The email address is obfuscated as <email address hidden> by default,
    or with the given replacement.

    The pattern used to identify an email address is not 2822. It strives
    to match any possible email address embedded in the text. For example,
    mailto:person@domain.dom and http://person:password@domain.dom both
    match, though the http match is in fact not an email address.
    """
    if replacement is None:
        replacement = "<email address hidden>"
    text = re_email_address.sub(replacement, text_to_obfuscate)
    # Avoid doubled angle brackets.
    text = text.replace("<<email address hidden>>", "<email address hidden>")
    return text


def save_bz2_pickle(obj, filename):
    """Save a bz2 compressed pickle of `obj` to `filename`."""
    fout = bz2.BZ2File(filename, "w")
    try:
        # Use protocol 2 for Python 2 compatibility.
        pickle.dump(obj, fout, protocol=2)
    finally:
        fout.close()


def load_bz2_pickle(filename):
    """Load and return a bz2 compressed pickle from `filename`."""
    fin = bz2.BZ2File(filename, "r")
    try:
        return pickle.load(fin)
    finally:
        fin.close()


def obfuscate_structure(o):
    """Obfuscate the strings of a json-serializable structure.

    Note: tuples are converted to lists because json encoders do not
    distinguish between lists and tuples.

    :param o: Any json-serializable object.
    :return: a possibly-new structure in which all strings, list and tuple
        elements, and dict keys and values have undergone obfuscate_email
        recursively.
    """
    if isinstance(o, str):
        return obfuscate_email(o)
    elif isinstance(o, (list, tuple)):
        return [obfuscate_structure(value) for value in o]
    elif isinstance(o, (dict)):
        return {
            obfuscate_structure(key): obfuscate_structure(value)
            for key, value in o.items()
        }
    else:
        return o


def sanitise_urls(s):
    """Sanitise a string that may contain URLs for logging.

    Some jobs are started with arguments that probably shouldn't be
    logged in their entirety (usernames and passwords for P3As, for
    example).  This function removes them.
    """
    # Remove credentials from URLs.
    password_re = re.compile(r"://([^:@/]*:[^@/]*@)(\S+)")
    return password_re.sub(r"://<redacted>@\2", s)


def round_half_up(number):
    """Round `number` to the nearest integer, with ties going away from zero.

    This is equivalent to `int(round(number))` on Python 2; Python 3's
    `round` prefers round-to-even in the case of ties, which does a better
    job of avoiding statistical bias in many cases but isn't always what we
    want.
    """
    return int(
        decimal.Decimal(number).to_integral_value(
            rounding=decimal.ROUND_HALF_UP
        )
    )
