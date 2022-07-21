# Copyright 2012-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Sharing policies for pillars."""

__all__ = [
    "SharingPolicyMixin",
]

import itertools

from zope.component import getUtility

from lp.app.enums import (
    FREE_INFORMATION_TYPES,
    PRIVATE_INFORMATION_TYPES,
    PROPRIETARY_INFORMATION_TYPES,
    InformationType,
)
from lp.blueprints.model.specification import (
    SPECIFICATION_POLICY_ALLOWED_TYPES,
)
from lp.bugs.interfaces.bugtarget import BUG_POLICY_ALLOWED_TYPES
from lp.code.model.branchnamespace import BRANCH_POLICY_ALLOWED_TYPES
from lp.registry.enums import (
    BranchSharingPolicy,
    BugSharingPolicy,
    SpecificationSharingPolicy,
)
from lp.registry.errors import CommercialSubscribersOnly, ProprietaryPillar
from lp.registry.interfaces.accesspolicy import (
    IAccessPolicyArtifactSource,
    IAccessPolicyGrantSource,
    IAccessPolicySource,
)


class SharingPolicyMixin:
    """Sharing policy support for pillars.

    The pillar should define `bug_sharing_policy`, `branch_sharing_policy`,
    `specification_sharing_policy`, and `access_policies` fields.
    """

    def _prepare_to_set_sharing_policy(self, var, enum, kind, allowed_types):
        if (
            var not in {enum.PUBLIC, enum.FORBIDDEN}
            and not self.has_current_commercial_subscription
        ):
            raise CommercialSubscribersOnly(
                "A current commercial subscription is required to use "
                "proprietary %s." % kind
            )
        if self.information_type != InformationType.PUBLIC:
            if InformationType.PUBLIC in allowed_types[var]:
                raise ProprietaryPillar(
                    "The pillar is %s." % self.information_type.title
                )
        self._ensurePolicies(allowed_types[var])

    def setBranchSharingPolicy(self, branch_sharing_policy):
        """Mutator for branch_sharing_policy.

        Checks authorization and entitlement.
        """
        self._prepare_to_set_sharing_policy(
            branch_sharing_policy,
            BranchSharingPolicy,
            "branches",
            BRANCH_POLICY_ALLOWED_TYPES,
        )
        self.branch_sharing_policy = branch_sharing_policy
        self._pruneUnusedPolicies()

    def setBugSharingPolicy(self, bug_sharing_policy):
        """Mutator for bug_sharing_policy.

        Checks authorization and entitlement.
        """
        self._prepare_to_set_sharing_policy(
            bug_sharing_policy,
            BugSharingPolicy,
            "bugs",
            BUG_POLICY_ALLOWED_TYPES,
        )
        self.bug_sharing_policy = bug_sharing_policy
        self._pruneUnusedPolicies()

    def setSpecificationSharingPolicy(self, specification_sharing_policy):
        """Mutator for specification_sharing_policy.

        Checks authorization and entitlement.
        """
        self._prepare_to_set_sharing_policy(
            specification_sharing_policy,
            SpecificationSharingPolicy,
            "specifications",
            SPECIFICATION_POLICY_ALLOWED_TYPES,
        )
        self.specification_sharing_policy = specification_sharing_policy
        self._pruneUnusedPolicies()

    def _ensurePolicies(self, information_types):
        # Ensure that the pillar has access policies for the specified
        # information types.
        aps = getUtility(IAccessPolicySource)
        existing_policies = aps.findByPillar([self])
        existing_types = {
            access_policy.type for access_policy in existing_policies
        }
        # Create the missing policies.
        required_types = (
            set(information_types)
            .difference(existing_types)
            .intersection(PRIVATE_INFORMATION_TYPES)
        )
        policies = itertools.product((self,), required_types)
        policies = getUtility(IAccessPolicySource).create(policies)

        # Add the maintainer to the policies.
        grants = []
        for p in policies:
            grants.append((p, self.owner, self.owner))
        getUtility(IAccessPolicyGrantSource).grant(grants)

        self._cacheAccessPolicies()

    def _cacheAccessPolicies(self):
        # Update the cache of AccessPolicy.ids for which an
        # AccessPolicyGrant or AccessArtifactGrant is sufficient to convey
        # launchpad.LimitedView on this pillar.
        #
        # We only need a cache for proprietary types, and it only includes
        # proprietary policies in case a policy like Private Security was
        # somehow left around when a pillar was transitioned to Proprietary.
        if self.information_type in PROPRIETARY_INFORMATION_TYPES:
            self.access_policies = [
                policy.id
                for policy in getUtility(IAccessPolicySource).find(
                    [(self, type) for type in PROPRIETARY_INFORMATION_TYPES]
                )
            ]
        else:
            self.access_policies = None

    def _pruneUnusedPolicies(self):
        allowed_bug_types = set(
            BUG_POLICY_ALLOWED_TYPES.get(
                self.bug_sharing_policy, FREE_INFORMATION_TYPES
            )
        )
        allowed_branch_types = set(
            BRANCH_POLICY_ALLOWED_TYPES.get(
                self.branch_sharing_policy, FREE_INFORMATION_TYPES
            )
        )
        allowed_spec_types = set(
            SPECIFICATION_POLICY_ALLOWED_TYPES.get(
                self.specification_sharing_policy, [InformationType.PUBLIC]
            )
        )
        allowed_types = (
            allowed_bug_types | allowed_branch_types | allowed_spec_types
        )
        allowed_types.add(self.information_type)
        # Fetch all APs, and after filtering out ones that are forbidden
        # by the bug, branch, and specification policies, the APs that have no
        # APAs are unused and can be deleted.
        ap_source = getUtility(IAccessPolicySource)
        access_policies = set(ap_source.findByPillar([self]))
        apa_source = getUtility(IAccessPolicyArtifactSource)
        unused_aps = [
            ap
            for ap in access_policies
            if ap.type not in allowed_types
            and apa_source.findByPolicy([ap]).is_empty()
        ]
        getUtility(IAccessPolicyGrantSource).revokeByPolicy(unused_aps)
        ap_source.delete([(ap.pillar, ap.type) for ap in unused_aps])
        self._cacheAccessPolicies()
