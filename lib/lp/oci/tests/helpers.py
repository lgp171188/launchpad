# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper methods and mixins for OCI tests."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = []

import base64

from nacl.public import PrivateKey
from testtools.matchers import (
    AfterPreprocessing,
    MatchesAll,
    )
from zope.security.proxy import removeSecurityProxy

from lp.oci.interfaces.ocirecipe import OCI_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture


class OCIConfigHelperMixin:

    def setConfig(self):
        self.private_key = PrivateKey.generate()
        self.pushConfig(
            "oci",
            registry_secrets_public_key=base64.b64encode(
                bytes(self.private_key.public_key)).decode("UTF-8"))
        self.pushConfig(
            "oci",
            registry_secrets_private_key=base64.b64encode(
                bytes(self.private_key)).decode("UTF-8"))
        # Default feature flags for our tests
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))


class MatchesOCIRegistryCredentials(MatchesAll):
    """Matches an `OCIRegistryCredentials` object.

    `main_matcher` matches the `OCIRegistryCredentials` object itself, while
    `credentials_matcher` matches the result of its `getCredentials` method.
    """

    def __init__(self, main_matcher, credentials_matcher):
        super(MatchesOCIRegistryCredentials, self).__init__(
            main_matcher,
            AfterPreprocessing(
                lambda matchee: removeSecurityProxy(matchee).getCredentials(),
                credentials_matcher))
