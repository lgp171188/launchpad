# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "determine_instances_to_build",
]

import json
from collections import Counter, OrderedDict

from lp.services.helpers import english_list


class RockBasesParserError(Exception):
    """Base class for all exceptions in this module."""


class MissingPropertyError(RockBasesParserError):
    """Error for when an expected property is not present in the YAML."""

    def __init__(self, prop):
        super().__init__(
            f"Base specification is missing the {prop!r} property"
        )
        self.property = prop


class BadPropertyError(RockBasesParserError):
    """Error for when a YAML property is malformed in some way."""


class DuplicateRunOnError(RockBasesParserError):
    """Error for when multiple `run-on`s include the same architecture."""

    def __init__(self, duplicates):
        super().__init__(
            "{} {} present in the 'run-on' of multiple items".format(
                english_list([str(d) for d in duplicates]),
                "is" if len(duplicates) == 1 else "are",
            )
        )


class RockBase:
    """A single base in rockcraft.yaml."""

    def __init__(self, name, channel, architectures=None):
        self.name = name
        if not isinstance(channel, str):
            raise BadPropertyError(
                "Channel {!r} is not a string (missing quotes?)".format(
                    channel
                )
            )
        self.channel = channel
        self.architectures = architectures

    @classmethod
    def from_dict(cls, properties):
        """Create a new base from a dict."""
        try:
            name = properties["name"]
        except KeyError:
            raise MissingPropertyError("name")
        try:
            channel = properties["channel"]
        except KeyError:
            raise MissingPropertyError("channel")
        return cls(
            name=name,
            channel=channel,
            architectures=properties.get("architectures"),
        )

    def __eq__(self, other):
        return (
            self.name == other.name
            and self.channel == other.channel
            and self.architectures == other.architectures
        )

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((self.name, self.channel, tuple(self.architectures)))

    def __str__(self):
        return "{} {} {}".format(
            self.name, self.channel, json.dumps(self.architectures)
        )


class RockBaseConfiguration:
    """A base configuration entry in rockcraft.yaml."""

    def __init__(self, build_on, run_on=None):
        self.build_on = build_on
        self.run_on = list(build_on) if run_on is None else run_on

    @classmethod
    def from_dict(cls, properties):
        """Create a new base configuration from a dict."""
        # Expand short-form configuration into long-form.  Account for
        # common typos in case the user intends to use long-form but did so
        # incorrectly (for better error message handling).
        if not any(
            item in properties
            for item in ("run-on", "run_on", "build-on", "build_on")
        ):
            base = RockBase.from_dict(properties)
            return cls([base], run_on=[base])

        try:
            build_on = properties["build-on"]
        except KeyError:
            raise MissingPropertyError("build-on")
        build_on = [RockBase.from_dict(item) for item in build_on]
        run_on = properties.get("run-on")
        if run_on is not None:
            run_on = [RockBase.from_dict(item) for item in run_on]
        return cls(build_on, run_on=run_on)


def determine_instances_to_build(
    rockcraft_data, supported_arches, default_distro_series
):
    """Return a list of instances to build based on rockcraft.yaml.

    :param rockcraft_data: A parsed rockcraft.yaml.
    :param supported_arches: An ordered list of all `DistroArchSeries` that
        we can create builds for.  Note that these may span multiple
        `DistroSeries`.
    :param default_distro_series: The default `DistroSeries` to use if
        rockcraft.yaml does not explicitly declare any bases.
    :return: A list of `DistroArchSeries`.
    """
    bases_list = rockcraft_data.get("bases")

    if bases_list:
        configs = [
            RockBaseConfiguration.from_dict(item) for item in bases_list
        ]
    else:
        # If no bases are specified, build one for each supported
        # architecture for the default series.
        configs = [
            RockBaseConfiguration(
                [
                    RockBase(
                        default_distro_series.distribution.name,
                        default_distro_series.version,
                        das.architecturetag,
                    ),
                ]
            )
            for das in supported_arches
            if das.distroseries == default_distro_series
        ]

    # Ensure that multiple `run-on` items don't overlap; this is ambiguous
    # and forbidden by rockcraft.
    run_ons = Counter()
    for config in configs:
        run_ons.update(config.run_on)
    duplicates = {config for config, count in run_ons.items() if count > 1}
    if duplicates:
        raise DuplicateRunOnError(duplicates)

    instances = OrderedDict()
    for config in configs:
        # Rocks are allowed to declare that they build on architectures
        # that Launchpad doesn't currently support (perhaps they're
        # upcoming, or perhaps they used to be supported).  We just ignore
        # those.
        for build_on in config.build_on:
            for das in supported_arches:
                if (
                    das.distroseries.distribution.name == build_on.name
                    and build_on.channel
                    in (das.distroseries.name, das.distroseries.version)
                    and das.architecturetag in build_on.architectures
                ):
                    instances[das] = None
                    break
            else:
                continue
            break
    return list(instances)
