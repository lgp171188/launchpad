# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""All the interfaces that are exposed through the webservice."""

__all__ = [
    'IOCIProject',
    'IOCIProjectSeries',
    'IOCIRecipe',
    ]

from lp.oci.interfaces.ocirecipe import IOCIRecipe
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.ociprojectseries import IOCIProjectSeries
