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
    """loads a `.launchpad.yaml` file into a `Configuration` object"""
    # load yaml
    with open(configuration_file) as stream:
        content = yaml.safe_load(stream)
    # expand matrix
    expanded_values = content.copy()
    if expanded_values.get("jobs"):
        expanded_values["jobs"] = {
            job_name: _expand_job_values(job_values)
            for job_name, job_values in content["jobs"].items()
        }
    # create "data class"
    return Configuration(expanded_values)


class Configuration:
    """configuration object representation of a `.launchpad.yaml` file"""
    def __init__(self, d):
        self.__dict__.update(d)
