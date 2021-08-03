# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Macaroon testing helpers."""

__metaclass__ = type
__all__ = [
    'find_caveats_by_name',
    'MacaroonTestMixin',
    'MacaroonVerifies',
    ]

from pymacaroons import Macaroon
from testtools.content import text_content
from testtools.matchers import (
    Matcher,
    MatchesStructure,
    Mismatch,
    )
from zope.component import getUtility

from lp.services.macaroons.interfaces import IMacaroonIssuer


def find_caveats_by_name(macaroon, caveat_name):
    return [
        caveat for caveat in macaroon.caveats
        if caveat.caveat_id.startswith(caveat_name + " ")]


class MacaroonVerifies(Matcher):
    """Matches if a macaroon can be verified."""

    def __init__(self, issuer_name, context, matcher=None, **verify_kwargs):
        super(MacaroonVerifies, self).__init__()
        self.issuer_name = issuer_name
        self.context = context
        self.matcher = matcher
        self.verify_kwargs = verify_kwargs

    def match(self, macaroon_raw):
        issuer = getUtility(IMacaroonIssuer, self.issuer_name)
        macaroon = Macaroon.deserialize(macaroon_raw)
        errors = []
        verified = issuer.verifyMacaroon(
            macaroon, self.context, errors=errors, **self.verify_kwargs)
        if not verified:
            return Mismatch(
                "Macaroon '%s' does not verify" % macaroon_raw,
                {"errors": text_content("\n".join(errors))})
        mismatch = MatchesStructure.byEquality(
            issuer_name=self.issuer_name).match(verified)
        if mismatch is not None:
            return mismatch
        if self.matcher is not None:
            return self.matcher.match(verified)


class MacaroonTestMixin:

    def assertMacaroonVerifies(self, issuer, macaroon, context, **kwargs):
        self.assertThat(
            macaroon.serialize(),
            MacaroonVerifies(issuer.identifier, context, **kwargs))

    def assertMacaroonDoesNotVerify(self, expected_errors, issuer, macaroon,
                                    context, **kwargs):
        matcher = MacaroonVerifies(issuer.identifier, context, **kwargs)
        mismatch = matcher.match(macaroon.serialize())
        self.assertIsNotNone(mismatch)
        errors = mismatch.get_details()["errors"].as_text().splitlines()
        self.assertEqual(expected_errors, errors)
