# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "determine_instances_to_build",
]


import json
import re


class CraftBasesParserError(Exception):
    """Base class for all exceptions in this module."""


class MissingPropertyError(CraftBasesParserError):
    """Error for when an expected property is not present in the YAML."""

    def __init__(self, prop, msg=None):
        if msg is None:
            msg = f"Craft specification is missing the {prop!r} property"
        super().__init__(msg)
        self.property = prop


class BadPropertyError(CraftBasesParserError):
    """Error for when a YAML property is malformed in some way."""


class CraftBase:
    """A single base in sourcecraft.yaml."""

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


class CraftBaseConfiguration:
    """A configuration in sourcecraft.yaml."""

    def __init__(self, build_on, build_for=None):
        self.build_on = build_on
        self.build_for = list(build_on) if build_for is None else build_for

    @classmethod
    def from_dict(
        cls, sourcecraft_data, supported_arches, requested_architectures
    ):
        base = sourcecraft_data.get("base")
        if not base:
            raise MissingPropertyError("base")

        if isinstance(base, str):
            if base == "bare" and "build-base" not in sourcecraft_data:
                raise MissingPropertyError(
                    "build-base",
                    "If base is 'bare', then build-base must be specified",
                )
            if base == "bare":
                base = sourcecraft_data["build-base"]
            # Expected short-form value looks like 'ubuntu@24.04'
            match = re.match(r"(.+)@(.+)", base)
            if not match:
                raise BadPropertyError(
                    f"Invalid value for base '{base}'. Expected value should "
                    "be like 'ubuntu@24.04'"
                )
            base_name, base_channel = match.groups()

        platforms = sourcecraft_data.get("platforms")
        if not platforms:
            raise MissingPropertyError("platforms")

        configs = []
        supported_arch_names = {
            das.architecturetag for das in supported_arches
        }

        for platform, configuration in platforms.items():
            if (
                requested_architectures
                and platform not in requested_architectures
            ):
                continue

            build_on = None
            build_for = None

            # Check if platform is a supported architecture
            is_supported_arch = platform in supported_arch_names

            if configuration:
                # Check build-for first
                if "build-for" in configuration:
                    build_for = configuration["build-for"]
                    if isinstance(build_for, list):
                        if len(build_for) != 1:
                            raise BadPropertyError(
                                f"'build-for' must be a single string or a "
                                "list with exactly one element for platform "
                                f"{platform}"
                            )
                        build_for = build_for[0]
                    if build_for not in supported_arch_names:
                        raise BadPropertyError(
                            f"Unsupported architecture {build_for} in "
                            f"platform {platform}"
                        )
                elif not is_supported_arch:
                    raise MissingPropertyError(
                        "build-for",
                        f"'build-for' is required for unsupported "
                        f"architecture {platform}",
                    )

                # Now check build-on
                if "build-on" in configuration:
                    build_on = configuration["build-on"]
                    if isinstance(build_on, str):
                        build_on = [build_on]
                    for arch in build_on:
                        if arch not in supported_arch_names:
                            raise BadPropertyError(
                                f"Unsupported architecture {arch} in "
                                f"platform {platform}"
                            )
                elif "build-for" in configuration or not is_supported_arch:
                    raise MissingPropertyError(
                        "build-on",
                        f"'build-on' is required when 'build-for' is "
                        f"specified or for unsupported architecture "
                        f"{platform}",
                    )
            elif not is_supported_arch:
                raise MissingPropertyError(
                    "configuration",
                    f"Configuration is required for unsupported architecture "
                    f"{platform}",
                )

            # Set defaults if not specified and platform is a
            # supported architecture
            if is_supported_arch:
                if build_on is None:
                    build_on = [platform]
                if build_for is None:
                    build_for = platform

            build_on = [
                CraftBase(base_name, base_channel, architecture)
                for architecture in build_on
            ]
            build_for = CraftBase(base_name, base_channel, build_for)

            configs.append(cls(build_on, [build_for]))

        return configs


def determine_instances_to_build(
    sourcecraft_data, supported_arches, requested_architectures=None
):
    """Return a list of instances to build based on sourcecraft.yaml.

    :param sourcecraft_data: A parsed sourcecraft.yaml.
    :param supported_arches: An ordered list of all `DistroArchSeries` that
        we can create builds for. Note that these may span multiple
        `DistroSeries`.
    :return: A list of `DistroArchSeries`.
    """
    configs = CraftBaseConfiguration.from_dict(
        sourcecraft_data, supported_arches, requested_architectures
    )

    instances = {}
    for config in configs:
        for build_on in config.build_on:
            for das in supported_arches:
                if (
                    das.distroseries.distribution.name == build_on.name
                    and build_on.channel
                    in (das.distroseries.name, das.distroseries.version)
                    and das.architecturetag in build_on.architectures
                ):
                    instances[das] = config
                    break

    return instances
