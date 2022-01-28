# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""This module provides a parser for lpcraft's configuration file.

As currently Launchpad is only compatible with Python 3.5, it was not possible
to reuse lpcraft's parser.

The implementation was copied from https://launchpad.net/lpcraft ->
`lpcraft/config.py`.

XXX jugmac00 2022-01-07: use lpcraft for parsing the configuration file once
we are on Python 3.8
"""

__all__ = ["load_configuration"]

import yaml
from zope.interface import implementer

from lp.code.interfaces.lpcraft import (
    ILPCraftConfiguration,
    LPCraftConfigurationError,
    )


def _expand_job_values(values):
    expanded_values = []
    if "matrix" in values:
        base_values = values.copy()
        del base_values["matrix"]
        for variant in values["matrix"]:
            variant_values = base_values.copy()
            variant_values.update(variant)
            # normalize `architectures` into a list
            architectures = variant_values.get("architectures")
            if isinstance(architectures, str):
                variant_values["architectures"] = [architectures]
            expanded_values.append(variant_values)
    else:
        expanded_values.append(values)
    return expanded_values


def load_configuration(configuration_file):
    """Loads a `.launchpad.yaml` file into a `Configuration` object.

    :param configuration_file: Anything that you can pass to `yaml.safe_load`,
        i.e. a stream or a string containing `.launchpad.yaml` content.
    """
    # load yaml
    content = yaml.safe_load(configuration_file)
    if content is None:
        raise LPCraftConfigurationError("Empty configuration file")
    for required_key in "pipeline", "jobs":
        if required_key not in content:
            raise LPCraftConfigurationError(
                "Configuration file does not declare '{}'".format(
                    required_key))
    # normalize each element of `pipeline` into a list
    expanded_values = content.copy()
    expanded_values["pipeline"] = [
        [stage] if isinstance(stage, str) else stage
        for stage in expanded_values["pipeline"]]
    # expand matrix
    expanded_values["jobs"] = {
        job_name: _expand_job_values(job_values)
        for job_name, job_values in content["jobs"].items()
    }
    for job_name, expanded_job_values in expanded_values["jobs"].items():
        for i, job_values in enumerate(expanded_job_values):
            for required_key in "series", "architectures":
                if required_key not in job_values:
                    raise LPCraftConfigurationError(
                        "Job {}:{} does not declare '{}'".format(
                            job_name, i, required_key))
    # create "data class"
    return LPCraftConfiguration(expanded_values)


@implementer(ILPCraftConfiguration)
class LPCraftConfiguration:
    """See `ILPCraftConfiguration`."""

    def __init__(self, d):
        self.__dict__.update(d)
