# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""All the interfaces that are exposed through the webservice."""

__all__ = [
    'IOCIProject',
    'IOCIProjectSeries',
    'IOCIPushRule',
    'IOCIRecipe',
    'IOCIRecipeBuild',
    'IOCIRecipeBuildRequest'
    ]

from lp.oci.interfaces.ocipushrule import IOCIPushRule
from lp.oci.interfaces.ocirecipe import (
    IOCIRecipe,
    IOCIRecipeBuildRequest,
    IOCIRecipeEdit,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.ociprojectseries import IOCIProjectSeries
from lp.services.webservice.apihelpers import (
    patch_collection_property,
    patch_entry_return_type,
    patch_plain_parameter_type,
    patch_reference_property,
    )


# IOCIProject
patch_collection_property(IOCIProject, 'series', IOCIProjectSeries)
patch_entry_return_type(IOCIProject, 'newRecipe', IOCIRecipe)
patch_plain_parameter_type(
    IOCIProject, 'setOfficialRecipeStatus', 'recipe', IOCIRecipe)

# IOCIRecipe
patch_collection_property(IOCIRecipe, 'builds', IOCIRecipeBuild)
patch_collection_property(IOCIRecipe, 'completed_builds', IOCIRecipeBuild)
patch_collection_property(IOCIRecipe, 'pending_builds', IOCIRecipeBuild)
patch_collection_property(IOCIRecipe, 'push_rules', IOCIPushRule)

# IOCIRecipeRequestBuild
patch_reference_property(IOCIRecipeBuildRequest, 'recipe', IOCIRecipe)
patch_collection_property(IOCIRecipeBuildRequest, 'builds', IOCIRecipeBuild)


patch_entry_return_type(IOCIRecipeEdit, 'newPushRule', IOCIPushRule)
