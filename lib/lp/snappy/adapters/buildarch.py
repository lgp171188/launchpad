# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["determine_architectures_to_build", "BadPropertyError"]

from collections import Counter
from typing import Any, Dict, List, Optional, Union

from craft_platforms import BuildInfo, CraftPlatformsError, get_build_plan

from lp.services.helpers import english_list
from lp.snappy.interfaces.snapbase import SnapBaseFeature
from lp.snappy.model.snapbase import SnapBase


class SnapArchitecturesParserError(Exception):
    """Base class for all exceptions in this module."""


class MissingPropertyError(SnapArchitecturesParserError):
    """Error for when an expected property is not present in the YAML."""

    def __init__(self, prop):
        super().__init__(
            "Architecture specification is missing the {!r} property".format(
                prop
            )
        )
        self.property = prop


class BadPropertyError(Exception):
    """Error for when a YAML property is malformed in some way."""


class IncompatibleArchitecturesStyleError(SnapArchitecturesParserError):
    """Error for when architectures mix incompatible styles."""

    def __init__(self):
        super().__init__(
            "'architectures' must either be a list of strings or dicts, not "
            "both"
        )


class AllConflictInBuildForError(SnapArchitecturesParserError):
    """Error for when `build-for` contains `all` and another architecture."""

    def __init__(self):
        super().__init__(
            "'build-for' contains both 'all' and another architecture name"
        )


class AllConflictInBuildOnError(SnapArchitecturesParserError):
    """Error for when `build-on` contains `all` and another architecture."""

    def __init__(self):
        super().__init__(
            "'build-on' contains both 'all' and another architecture name"
        )


class DuplicateBuildOnError(SnapArchitecturesParserError):
    """Error for when multiple `build-on`s include the same architecture."""

    def __init__(self, duplicates):
        super().__init__(
            "{} {} present in the 'build-on' of multiple items".format(
                english_list(duplicates),
                "is" if len(duplicates) == 1 else "are",
            )
        )


class UnsupportedBuildOnError(SnapArchitecturesParserError):
    """Error for when a requested architecture is not supported."""

    def __init__(self, build_on):
        super().__init__(
            "build-on specifies no supported architectures: {!r}".format(
                build_on
            )
        )
        self.build_on = build_on


class CraftPlatformsBuildPlanError(SnapArchitecturesParserError):
    """Error raised when craft-platforms fails while generating
    a build plan."""

    def __init__(Self, message, resolution=None):
        if resolution:
            message += f" Resolution: {resolution}"
        super().__init__(message)


class SnapArchitecture:
    """A single entry in the snapcraft.yaml 'architectures' list."""

    def __init__(
        self,
        build_on: Union[str, List[str]],
        build_for: Optional[Union[str, List[str]]] = None,
        build_error: Optional[str] = None,
        build_info: Optional[BuildInfo] = None,
    ):
        """Create a new architecture entry.

        :param build_on: string or list; build-on property from
            snapcraft.yaml.
        :param build_for: string or list; build-for property from
            snapcraft.yaml (defaults to build_on).
        :param build_error: string; build-error property from
            snapcraft.yaml.
        """
        self.build_on: List[str] = (
            [build_on] if isinstance(build_on, str) else build_on
        )
        if build_for:
            self.build_for: List[str] = (
                [build_for] if isinstance(build_for, str) else build_for
            )
        else:
            self.build_for = self.build_on
        self.build_error = build_error
        self.build_info = build_info

    @classmethod
    def from_dict(cls, properties):
        """Create a new architecture entry from a dict."""
        try:
            build_on = properties["build-on"]
        except KeyError:
            raise MissingPropertyError("build-on")

        build_for = properties.get("build-for", properties.get("run-on"))

        return cls(
            build_on=build_on,
            build_for=build_for,
            build_error=properties.get("build-error"),
        )


class SnapBuildInstance:
    """A single instance of a snap that should be built.

    If has the following useful attributes:

      - architecture: The architecture tag that should be used to build the
            snap.
      - target_architectures: The architecture tags of the snaps expected to
            be produced by this recipe (which may differ from `architecture`
            in the case of cross-building)
      - required: Whether or not failure to build should cause the entire
            set to fail.
      - platform_name: The platform to build for.
    """

    def __init__(
        self,
        architecture: SnapArchitecture,
        supported_architectures: List[str],
        platform_name: str = None,
    ):
        """Construct a new `SnapBuildInstance`.

        :param architecture: `SnapArchitecture` instance.
        :param supported_architectures: List of supported architectures,
            sorted by priority.
        : param platform_name: The platform to build for.
        """
        build_on = architecture.build_on
        # "all" indicates that the architecture doesn't matter.  Try to pick
        # an appropriate architecture in this case.
        # `Snap.requestBuildsFromJob` orders `supported_architectures` such
        # that we can reasonably pick the first one if all else fails.
        if "all" in build_on:
            build_on = architecture.build_for
            if "all" in build_on:
                build_on = supported_architectures[0]
        try:
            self.architecture = next(
                arch for arch in supported_architectures if arch in build_on
            )
        except StopIteration:
            raise UnsupportedBuildOnError(build_on)

        self.target_architectures = architecture.build_for
        self.required = architecture.build_error != "ignore"
        self.platform_name = platform_name


def determine_architectures_to_build(
    snap_base: Optional[SnapBase],
    snapcraft_data: Dict[str, Any],
    supported_arches: List[str],
) -> List[SnapBuildInstance]:
    """Return a list of architectures to build based on snapcraft.yaml.

    :param snap_base: Name of the snap base.
    :param snapcraft_data: A parsed snapcraft.yaml.
    :param supported_arches: An ordered list of all architecture tags that
        we can create builds for.
    :return: a list of `SnapBuildInstance`s.
    """
    architectures = None
    # 1) Snap with 'architectures' format
    if "architectures" in snapcraft_data and snapcraft_data.get(
        "architectures"
    ):
        # XXX tushar5526 2025-04-15: craft_platforms do not support
        # "architectures" format used in core22 or older,
        # fallback to the existing LP parsing logic in that case.
        architectures_list: Optional[List] = snapcraft_data.get(
            "architectures"
        )
        architectures = parse_architectures_list(architectures_list)
    # 2) Snap with 'platforms' format
    elif "platforms" in snapcraft_data:
        # Use craft-platforms to generate the build plan
        architectures = parse_platforms(snapcraft_data)
    # 3) Snap with no 'architectures' or 'platforms' format:
    # XXX alvarocs 2025-04-29: craft-platforms handles cases where
    # neither 'platforms' nor 'architectures' are defined, but makes
    # legacy tests fail. For compatibility, still use Launchpad logic
    # of building for all supported architectures.
    if not architectures:
        # If no architectures are specified, build one for each supported
        # architecture.
        architectures = [
            SnapArchitecture(build_on=a) for a in supported_arches
        ]

    validate_architectures(architectures)

    allow_duplicate_build_on = (
        snap_base
        and snap_base.features.get(SnapBaseFeature.ALLOW_DUPLICATE_BUILD_ON)
    ) or False

    if not allow_duplicate_build_on:
        check_for_duplicate_build_on(architectures)

    return build_architectures_list(architectures, supported_arches)


def parse_architectures_list(
    architectures_list: List,
) -> List[SnapArchitecture]:
    # First, determine what style we're parsing.  Is it a list of
    # strings or a list of dicts?
    if all(isinstance(a, str) for a in architectures_list):
        # If a list of strings (old style), then that's only a single
        # item.
        return [SnapArchitecture(build_on=architectures_list)]
    elif all(isinstance(arch, dict) for arch in architectures_list):
        # If a list of dicts (new style), then that's multiple items.
        return [SnapArchitecture.from_dict(a) for a in architectures_list]
    else:
        # If a mix of both, bail.  We can't reasonably handle it.
        raise IncompatibleArchitecturesStyleError()


def parse_platforms(
    snapcraft_data: Dict[str, Any],
) -> List[SnapArchitecture]:

    try:
        exhaustive_build_plan = get_build_plan(
            app="snapcraft",
            project_data=snapcraft_data,
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
            "Failed to compute the build plan for the snapcraft file "
            "with error: "
            f"{message}",
            resolution=resolution,
        )
    platform_plans: Dict[str, BuildInfo] = {}
    for plan in exhaustive_build_plan:
        platform_plans.setdefault(plan.platform, []).append(plan)
    instances_to_build: List[BuildInfo] = []
    for _platform, pairs in platform_plans.items():
        # One way of building for that platform, i.e one (info, das)
        if len(pairs) == 1:
            instances_to_build.append(pairs[0])
            continue
        # Multiple ways of building for that platform:
        for info in pairs:
            # Pick the native build
            if info.build_on == info.build_for:
                instances_to_build.append(info)
                break
        # Pick first one if none are native
        else:
            instances_to_build.append(pairs[0])
    return [
        SnapArchitecture(
            build_on=str(instance.build_on),
            build_for=str(instance.build_for),
            build_info=instance,
        )
        for instance in instances_to_build
    ]


def validate_architectures(architectures: List[SnapArchitecture]):
    for arch in architectures:
        if "all" in arch.build_on and len(arch.build_on) > 1:
            raise AllConflictInBuildOnError()
        if "all" in arch.build_for and len(arch.build_for) > 1:
            raise AllConflictInBuildForError()


def check_for_duplicate_build_on(architectures: List[SnapArchitecture]):
    # Ensure that multiple `build-on` items don't include the same
    # architecture; this is ambiguous and forbidden by snapcraft prior
    # to core22. Checking this here means that we don't get duplicate
    # supported_arch results below.
    build_ons = Counter()
    for arch in architectures:
        build_ons.update(arch.build_on)
    duplicates = {arch for arch, count in build_ons.items() if count > 1}
    if duplicates:
        raise DuplicateBuildOnError(duplicates)


def build_architectures_list(
    architectures: List[SnapArchitecture], supported_arches: List[str]
) -> List[SnapBuildInstance]:
    architectures_to_build = []
    for arch in architectures:
        try:
            platform_name = (
                arch.build_info.platform
                if arch.build_info is not None
                else None
            )
            architectures_to_build.append(
                SnapBuildInstance(arch, supported_arches, platform_name)
            )
        except UnsupportedBuildOnError:
            # Snaps are allowed to declare that they build on architectures
            # that Launchpad doesn't currently support (perhaps they're
            # upcoming, or perhaps they used to be supported).  We just
            # ignore those.
            pass
    return architectures_to_build
