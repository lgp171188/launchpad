# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Support code for using a custom test result in test.py."""

__all__ = [
    "filter_tests",
    "patch_find_tests",
]

from unittest import TestSuite

from zope.testrunner import find


def patch_find_tests(hook):
    """Add a post-processing hook to zope.testrunner.find_tests.

    This is useful for things like filtering tests or listing tests.

    :param hook: A callable that takes the output of the real
        `testrunner.find_tests` and returns a thing with the same type and
        structure.
    """
    real_find_tests = find.find_tests

    def find_tests(*args):
        return hook(real_find_tests(*args))

    find.find_tests = find_tests


def filter_tests(list_name, reorder_tests=False):
    """Create a hook for `patch_find_tests` that filters tests based on id.

    :param list_name: A filename that contains a newline-separated list of
        test ids, as generated by `list_tests`.
    :param reorder_tests: if True, the tests contained in `list_name`
        are reordered by id. Default is False: the ordering is preserved.
    :return: A callable that takes a result of `testrunner.find_tests` and
        returns only those tests with ids in the file 'list_name'.

    Note great care is taken to preserve the ordering of the original test
    cases, which is quite important if trying to figure out test isolation
    bugs.  The original ordering is maintained within layers but since the
    results are returned as a dictionary the caller may shuffle the way the
    layers are run and there is nothing to be done about that here.  In
    practice the layers are seen to be run in the same order.

    However, test cases can still be reordered if `reorder_tests` is set to
    True: this is useful when tests are shuffled and the test shuffler is
    initialized using a particoular value. This way the same seed produces
    the same random ordering, regardless of whether the tests are filtered
    using -t or --load-list.

    Should a test be listed, but not present in any of the suites, it is
    silently ignored.
    """

    def do_filter(tests_by_layer_name):
        # Read the tests, filtering out any blank lines.
        with open(list_name) as f:
            tests = [line.strip() for line in f if line]
        if reorder_tests:
            tests.sort()
        test_lookup = {}
        # Multiple unique testcases can be represented by a single id and they
        # must be tracked separately.
        for layer_name, suite in tests_by_layer_name.items():
            for testcase in suite:
                layer_to_tests = test_lookup.setdefault(testcase.id(), {})
                testcases = layer_to_tests.setdefault(layer_name, [])
                testcases.append(testcase)

        result = {}
        for testname in tests:
            layer_to_tests = test_lookup.get(testname, {})
            for layer_name, testcases in layer_to_tests.items():
                if testcases is not None:
                    suite = result.setdefault(layer_name, TestSuite())
                    suite.addTests(testcases)
        return result

    return do_filter
