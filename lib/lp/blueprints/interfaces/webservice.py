# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""All the interfaces that are exposed through the webservice.

There is a declaration in ZCML somewhere that looks like:
  <webservice:register module="lp.blueprints.interfaces.webservice" />

which tells `lazr.restful` that it should look for webservice exports here.
"""

__all__ = [
    "GoalProposeError",
    "ISpecification",
    "ISpecificationBranch",
    "ISpecificationSet",
    "ISpecificationSubscription",
    "ISpecificationTarget",
]

from lp.blueprints.interfaces.specification import (
    GoalProposeError,
    ISpecification,
    ISpecificationSet,
)
from lp.blueprints.interfaces.specificationbranch import ISpecificationBranch
from lp.blueprints.interfaces.specificationsubscription import (
    ISpecificationSubscription,
)
from lp.blueprints.interfaces.specificationtarget import (
    IHasSpecifications,
    ISpecificationTarget,
)
from lp.bugs.interfaces.bug import IBug
from lp.services.webservice.apihelpers import (
    patch_collection_property,
    patch_entry_return_type,
    patch_plain_parameter_type,
)

# IHasSpecifications
patch_collection_property(
    IHasSpecifications, "visible_specifications", ISpecification
)
patch_collection_property(
    IHasSpecifications, "api_valid_specifications", ISpecification
)

# ISpecification
patch_plain_parameter_type(ISpecification, "linkBug", "bug", IBug)
patch_plain_parameter_type(ISpecification, "unlinkBug", "bug", IBug)
patch_collection_property(ISpecification, "dependencies", ISpecification)
patch_collection_property(
    ISpecification, "linked_branches", ISpecificationBranch
)

# ISpecificationTarget
patch_entry_return_type(
    ISpecificationTarget, "getSpecification", ISpecification
)
