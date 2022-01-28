# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface to lpcraft's configuration file."""

__all__ = [
    "ILPCraftConfiguration",
    "LPCraftConfigurationError",
    ]

from zope.interface import Interface
from zope.schema import (
    Dict,
    List,
    TextLine,
    )


class LPCraftConfigurationError(Exception):
    """Parsing lpcraft's configuration file failed."""


class ILPCraftConfiguration(Interface):
    """An object representation of a `.launchpad.yaml` file."""

    pipeline = List(
        title="List of stages",
        description="Each stage is a list of job names.",
        value_type=TextLine())

    jobs = Dict(
        title="Mapping of job names to job definitions",
        key_type=TextLine(),
        value_type=Dict(key_type=TextLine()))
