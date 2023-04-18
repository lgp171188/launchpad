# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface to lpci's configuration file."""

__all__ = [
    "ILPCIConfiguration",
    "LPCIConfigurationError",
]

from zope.interface import Interface
from zope.schema import Dict, List, TextLine


class LPCIConfigurationError(Exception):
    """Parsing lpci's configuration file failed."""


class ILPCIConfiguration(Interface):
    """An object representation of a `.launchpad.yaml` file."""

    pipeline = List(
        title="List of stages",
        description="Each stage is a list of job names.",
        value_type=TextLine(),
    )

    jobs = Dict(
        title="Mapping of job names to job definitions",
        key_type=TextLine(),
        value_type=Dict(key_type=TextLine()),
    )
