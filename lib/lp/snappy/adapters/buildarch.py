# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "determine_architectures_to_build",
]

from collections import Counter
from typing import Any, Dict, List, Optional, Union

from lp.charms.adapters.buildarch import BadPropertyError
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


class SnapArchitecture:
    """A single entry in the snapcraft.yaml 'architectures' list."""

    def __init__(
        self,
        build_on: Union[str, List[str]],
        build_for: Optional[Union[str, List[str]]] = None,
        build_error: Optional[str] = None,
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

    It has two useful attributes:

      - architecture: The architecture tag that should be used to build the
            snap.
      - target_architectures: The architecture tags of the snaps expected to
            be produced by this recipe (which may differ from `architecture`
            in the case of cross-building)
      - required: Whether or not failure to build should cause the entire
            set to fail.
    """

    def __init__(
        self,
        architecture: SnapArchitecture,
        supported_architectures: List[str],
    ):
        """Construct a new `SnapBuildInstance`.

        :param architecture: `SnapArchitecture` instance.
        :param supported_architectures: List of supported architectures,
            sorted by priority.
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
    architectures_list: Optional[List] = snapcraft_data.get("architectures")

    if architectures_list:
        architectures = parse_architectures_list(architectures_list)
    elif "platforms" in snapcraft_data:
        architectures = parse_platforms(snapcraft_data, supported_arches)
    else:
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


def parse_architectures_list(architectures_list: List) -> List[SnapArchitecture]:
    # First, determine what style we're parsing.  Is it a list of
    # strings or a list of dicts?
    if all(isinstance(a, str) for a in architectures_list):
        # If a list of strings (old style), then that's only a single
        # item.
        return [SnapArchitecture(build_on=architectures_list)]
    elif all(isinstance(arch, dict) for arch in architectures_list):
        # If a list of dicts (new style), then that's multiple items.
        return [
            SnapArchitecture.from_dict(a) for a in architectures_list
        ]
    else:
        # If a mix of both, bail.  We can't reasonably handle it.
        raise IncompatibleArchitecturesStyleError()


def parse_platforms(snapcraft_data: Dict[str, Any], supported_arches: List[str]) -> List[SnapArchitecture]:
    architectures = []
    supported_arch_names = supported_arches

    for platform, configuration in snapcraft_data["platforms"].items():
        # The 'platforms' property and its values look like
        # platforms:
        #   ubuntu-amd64:
        #     build-on: [amd64]
        #     build-for: [amd64]
        # 'ubuntu-amd64' will be the value of 'platform' and its value dict
        # containing the keys 'build-on', 'build-for' will be the value of
        # 'configuration'.
        if configuration:
            build_on = configuration.get("build-on", [platform])
            build_for = configuration.get("build-for", build_on)
            architectures.append(
                SnapArchitecture(
                    build_on=build_on,
                    build_for=build_for,
                )
            )
        elif platform in supported_arch_names:
            architectures.append(
                SnapArchitecture(
                    build_on=[platform], build_for=[platform]
                )
            )
        else:
            base = snapcraft_data["base"]
            raise BadPropertyError(
                f"'{platform}' is not a supported platform "
                f"for '{base}'."
            )

    return architectures


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
    

def build_architectures_list(architectures: List[SnapArchitecture], supported_arches: List[str]) -> List[SnapBuildInstance]:
    architectures_to_build = []
    for arch in architectures:
        try:
            architectures_to_build.append(
                SnapBuildInstance(arch, supported_arches)
            )
        except UnsupportedBuildOnError:
            # Snaps are allowed to declare that they build on architectures
            # that Launchpad doesn't currently support (perhaps they're
            # upcoming, or perhaps they used to be supported).  We just
            # ignore those.
            pass
    return architectures_to_build
