# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Validators for attachments."""

__all__ = ["attachment_size_constraint"]

from lp.app.validators import LaunchpadValidationError
from lp.services.config import config


def attachment_size_constraint(value):
    """Constraint for an attachment's file size.

    The file is not allowed to be empty.
    """
    size = len(value)
    max_size = config.launchpad.max_attachment_size
    if size == 0:
        raise LaunchpadValidationError("Cannot upload empty file.")
    elif max_size > 0 and size > max_size:
        raise LaunchpadValidationError(
            "Cannot upload files larger than %i bytes" % max_size
        )
    else:
        return True
