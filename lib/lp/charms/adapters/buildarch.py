# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "determine_instances_to_build",
]

import json
import re
from collections import Counter, OrderedDict

from lp.services.helpers import english_list


class CharmBasesParserError(Exception):
    """Base class for all exceptions in this module."""


class MissingPropertyError(CharmBasesParserError):
    """Error for when an expected property is not present in the YAML."""

    def __init__(self, prop, msg=None):
        if msg is None:
            msg = f"Base specification is missing the {prop!r} property"
        super().__init__(msg)
        self.property = prop


class BadPropertyError(CharmBasesParserError):
    """Error for when a YAML property is malformed in some way."""


class DuplicateRunOnError(CharmBasesParserError):
    """Error for when multiple `run-on`s include the same architecture."""

    def __init__(self, duplicates):
        super().__init__(
            "{} {} present in the 'run-on' of multiple items".format(
                english_list([str(d) for d in duplicates]),
                "is" if len(duplicates) == 1 else "are",
            )
        )


class CharmBase:
    """A single base in charmcraft.yaml."""

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
        architectures = (
            None if self.architectures is None else tuple(self.architectures)
        )
        return hash((self.name, self.channel, architectures))

    def __str__(self):
        return "{} {} {}".format(
            self.name, self.channel, json.dumps(self.architectures)
        )


class CharmBaseConfiguration:
    """A base configuration entry in charmcraft.yaml."""

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
            base = CharmBase.from_dict(properties)
            return cls([base], run_on=[base])

        try:
            build_on = properties["build-on"]
        except KeyError:
            raise MissingPropertyError("build-on")
        build_on = [CharmBase.from_dict(item) for item in build_on]
        run_on = properties.get("run-on")
        if run_on is not None:
            run_on = [CharmBase.from_dict(item) for item in run_on]
        return cls(build_on, run_on=run_on)


class UnifiedCharmBaseConfiguration:
    """A unified base configuration in charmcraft.yaml"""

    def __init__(self, build_on, run_on=None):
        self.build_on = build_on
        self.run_on = list(build_on) if run_on is None else run_on

    @classmethod
    def from_dict(cls, charmcraft_data, supported_arches):
        base = charmcraft_data["base"]
        if isinstance(base, str):
            # Expected short-form value looks like 'ubuntu@24.04'
            match = re.match(r"(.+)@(.+)", base)
            if not match:
                raise BadPropertyError(
                    f"Invalid value for base '{base}'. Expected value should "
                    "be like 'ubuntu@24.04'"
                )
            base_name, base_channel = match.groups()
        else:
            # Expected value looks like {"name": "ubuntu", "channel": "24.04"}
            base_name = base["name"]
            # If a value like 24.04 is unquoted in yaml, it will be
            # interpreted as a float. So we convert it to a string.
            base_channel = str(base["channel"])

        # XXX lgp171188 2024-06-11: Find out if we need 'build-base' or not.
        # There is no existing code that is using that.

        platforms = charmcraft_data.get("platforms")
        if not platforms:
            raise MissingPropertyError(
                "platforms", "The 'platforms' property is required"
            )
        configs = []
        for platform, configuration in platforms.items():
            # The 'platforms' property and its values look like
            # platforms:
            #   ubuntu-amd64:
            #     build-on: [amd64]
            #     build-for: [amd64]
            # 'ubuntu-amd64' will be the value of 'platform' and its value dict
            # containing the keys 'build-on', 'build-for' will be the value of
            # 'configuration'.
            name = base_name
            channel = base_channel
            if configuration:
                build_on = configuration["build-on"]
                if isinstance(build_on, str):
                    build_on = [build_on]

                build_on = [
                    CharmBase(name, channel, architecture)
                    for architecture in build_on
                ]

                build_for = configuration["build-for"]
                if isinstance(build_for, str):
                    build_for = [build_for]

                build_for = [
                    CharmBase(name, channel, architecture)
                    for architecture in build_for
                ]
            else:
                supported_arch_names = (
                    das.architecturetag for das in supported_arches
                )
                if platform in supported_arch_names:
                    build_on = [CharmBase(name, channel, platform)]
                    build_for = [CharmBase(name, channel, platform)]
                else:
                    raise BadPropertyError(
                        f"'{platform}' is not a supported architecture "
                        f"for '{base_name}@{base_channel}'."
                    )
            configs.append(cls(build_on, build_for))
        return configs


def determine_instances_to_build(
    charmcraft_data, supported_arches, default_distro_series
):
    """Return a list of instances to build based on charmcraft.yaml.

    :param charmcraft_data: A parsed charmcraft.yaml.
    :param supported_arches: An ordered list of all `DistroArchSeries` that
        we can create builds for.  Note that these may span multiple
        `DistroSeries`.
    :param default_distro_series: The default `DistroSeries` to use if
        charmcraft.yaml does not explicitly declare any bases.
    :return: A list of `DistroArchSeries`.
    """
    from lp.charms.model.charmrecipe import is_unified_format

    bases_list = charmcraft_data.get("bases")

    if bases_list:
        configs = [
            CharmBaseConfiguration.from_dict(item) for item in bases_list
        ]
    elif is_unified_format(charmcraft_data):
        configs = UnifiedCharmBaseConfiguration.from_dict(
            charmcraft_data, supported_arches
        )
    else:
        # If no bases are specified, build one for each supported
        # architecture for the default series.
        configs = [
            CharmBaseConfiguration(
                [
                    CharmBase(
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
    # and forbidden by charmcraft.
    run_ons = Counter()
    for config in configs:
        run_ons.update(config.run_on)
    duplicates = {config for config, count in run_ons.items() if count > 1}
    if duplicates:
        raise DuplicateRunOnError(duplicates)

    instances = OrderedDict()
    for config in configs:
        # Charms are allowed to declare that they build on architectures
        # that Launchpad doesn't currently support (perhaps they're
        # upcoming, or perhaps they used to be supported).  We just ignore
        # those.
        for build_on in config.build_on:
            for das in supported_arches:
                if das.distroseries.distribution.name != build_on.name:
                    continue
                if build_on.channel not in (
                    das.distroseries.name,
                    das.distroseries.version,
                ):
                    continue
                if build_on.architectures is None:
                    # Build on all supported architectures for the requested
                    # series.
                    instances[das] = None
                elif das.architecturetag in build_on.architectures:
                    # Build on the first matching supported architecture for
                    # the requested series.
                    instances[das] = None
                    break
            else:
                continue
            break
    return list(instances)
