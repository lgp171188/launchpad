# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Utilities for dealing with channels in Canonical's stores."""

__all__ = [
    "CHANNEL_COMPONENTS_DELIMITER",
    "channel_list_to_string",
    "channel_string_to_list",
]

from lp.registry.enums import StoreRisk

# delimiter separating channel components
CHANNEL_COMPONENTS_DELIMITER = "/"


def _is_risk(component):
    """Does this channel component identify a risk?"""
    return component in {item.title for item in StoreRisk.items}


def channel_string_to_list(channel):
    """Return extracted track, risk, and branch from given channel name.

    The conversions are as follows, where 'stable', 'candidate', 'beta', and
    'edge' are possible risks:

    'stable' becomes (None, 'stable', None)
    'foo/edge' becomes ('foo', 'edge', None)
    'beta/hotfix' becomes (None, 'beta', 'hotfix')
    'foo/stable/hotfix' becomes ('foo', 'stable', 'hotfix')

    :raises ValueError: If the channel string is invalid.
    """
    components = channel.split(CHANNEL_COMPONENTS_DELIMITER)
    if len(components) == 3:
        track, risk, branch = components
    elif len(components) == 2:
        # Identify risk to determine if this is track/risk or risk/branch.
        if _is_risk(components[0]):
            if _is_risk(components[1]):
                raise ValueError(
                    "Branch name cannot match a risk name: %r" % channel
                )
            track = None
            risk, branch = components
        elif _is_risk(components[1]):
            track, risk = components
            branch = None
        else:
            raise ValueError("No valid risk provided: %r" % channel)
    elif len(components) == 1:
        track = None
        risk = components[0]
        branch = None
    else:
        raise ValueError("Invalid channel name: %r" % channel)
    return track, risk, branch


def channel_list_to_string(track, risk, branch):
    """Return channel name composed from given track, risk, and branch.

    (None, 'stable', None) or ('latest', 'stable', None) becomes 'stable'
    ('foo', 'edge', None) becomes 'foo/edge'
    (None, 'beta', 'hotfix') becomes 'beta/hotfix'
    ('foo', 'stable', 'hotfix') becomes 'foo/stable/hotfix'
    """
    if track == "latest":
        track = None
    return CHANNEL_COMPONENTS_DELIMITER.join(
        [c for c in (track, risk, branch) if c is not None]
    )
