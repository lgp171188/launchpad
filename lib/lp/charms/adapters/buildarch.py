# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "determine_instances_to_build",
]

import json
from collections import Counter

from craft_platforms import CraftPlatformsError, get_build_plan

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


class CraftPlatformsBuildPlanError(CharmBasesParserError):
    """Error raised when craft-platforms fails while generating a build
    plan.
    """

    def __init__(self, message, resolution=None):
        if resolution:
            message += f" Resolution: {resolution}"
        super().__init__(message)


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


def determine_instances_to_build(
    charmcraft_data, supported_arches, default_distro_series
):
    """Return a list of instances to build based on charmcraft.yaml.

    Handles three cases:
    1) 'bases' configuration
       Legacy format. Deprecated in favor of the unified format and expected
       to be removed in the future.
    2) Unified format configuration
       The recommended format using 'base', 'build-base', and 'platforms'.
       Supported by craft-platforms and actively maintained.
    3) With no bases specified configuration
       Launchpad specific fallback behavior when no base/platform is declared.
       To be removed once the unified format is fully adopted.

    :param charmcraft_data: A parsed charmcraft.yaml.
    :param supported_arches: An ordered list of all `DistroArchSeries` that
        we can create builds for.  Note that these may span multiple
        `DistroSeries`.
    :param default_distro_series: The default `DistroSeries` to use if
        charmcraft.yaml does not explicitly declare any bases.
    :return: A list of `DistroArchSeries`.
    """

    def _check_duplicate_run_on(configs):
        """Ensure that multiple `run-on` items don't overlap;
        this is ambiguous and forbidden by charmcraft.

        :param configs: List of CharmBaseConfiguration objects
        :raises DuplicateRunOnError if any architecture appears in
        multiple run-on configurations
        """

        run_ons = Counter()
        for config in configs:
            run_ons.update(config.run_on)
        duplicates = {config for config, count in run_ons.items() if count > 1}
        if duplicates:
            raise DuplicateRunOnError(duplicates)

    def _process_configs_to_instances(configs, supported_arches):
        """Convert base configurations to buildable instances.

        Filters configurations to only include supported architectures and
        distro series.

        :param configs: List of CharmBaseConfiguration objects
        :param supported_arches: List of supported DistroArchSeries
        :return: OrderedDict of filtered DistroArchSeries instances
        """

        _check_duplicate_run_on(configs)
        instances = {}
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
                        # Build on all supported architectures for the
                        # requested series.
                        instances[das] = None
                    elif das.architecturetag in build_on.architectures:
                        # Build on the first matching supported architecture
                        # for the requested series.
                        instances[das] = None
                        break
                else:
                    continue
                break
        return instances

    from lp.charms.model.charmrecipe import is_unified_format

    # 1) Charm with 'bases' format
    bases_list = charmcraft_data.get("bases")
    if bases_list:
        configs = [
            CharmBaseConfiguration.from_dict(item) for item in bases_list
        ]
        instances = _process_configs_to_instances(configs, supported_arches)
        instances_to_build = [(None, das) for das in instances.keys()]
        return instances_to_build

    # 2) Charm with unified format
    elif is_unified_format(charmcraft_data):

        # Validate base format, dict not allowed
        base = charmcraft_data.get("base")
        if isinstance(base, dict):
            raise BadPropertyError(
                f"'base' must be a string, but got a dict: {base}"
            )

        # Generate exhaustive build plan
        try:
            exhaustive_build_plan = get_build_plan(
                app="charmcraft",
                project_data=charmcraft_data,
            )
        # XXX alvarocs 2025-04-04: craft-platforms currently raises
        # 'ValueError' when it encounters malformed input such as an invalid
        # base or platform name. These should instead raise
        # 'CraftPlatformsError'. Bug tracked at:
        # https://github.com/canonical/craft-platforms/issues/116
        except (CraftPlatformsError, ValueError) as e:
            message = getattr(e, "message", str(e))
            resolution = getattr(e, "resolution", None)
            raise CraftPlatformsBuildPlanError(
                f"Failed to compute the build plan for base={base}, "
                f"build base={charmcraft_data.get('build-base')}, "
                f"platforms={charmcraft_data.get('platforms')}: {message}",
                resolution=resolution,
            )

        # Filter exhaustive build plan
        filtered_plan = []
        for info in exhaustive_build_plan:
            for das in supported_arches:
                # Compare DAS-BuildInfo and append if match
                if (
                    das.distroseries.distribution.name
                    == info.build_base.distribution
                    and info.build_base.series == das.distroseries.version
                    and das.architecturetag == info.build_on.value
                ):
                    filtered_plan.append((info, das))
                    break
        # Group by platform
        platform_plans = {}
        for info, das in filtered_plan:
            platform_plans.setdefault(info.platform, []).append((info, das))
        # Pick one BuildInfo per platform
        instances_to_build = []
        for _platform, pairs in platform_plans.items():
            # One way of building for that platform, i.e one (info, das)
            if len(pairs) == 1:
                instances_to_build.append(pairs[0])
                continue
            # More than one way of building for that platform
            for info, das in pairs:
                # Pick the native build
                if info.build_on == info.build_for:
                    instances_to_build.append((info, das))
                    break
            # Pick first one if none are native
            else:
                instances_to_build.append(pairs[0])
        return instances_to_build

    # 3) Charms with no bases specified
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
        instances = _process_configs_to_instances(configs, supported_arches)
        instances_to_build = [(None, das) for das in instances.keys()]
        return instances_to_build
