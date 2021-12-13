# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Specification views."""

__all__ = [
    'TargetAlreadyHasSpecification',
    ]

import http.client

from lazr.restful.declarations import error_status


@error_status(http.client.BAD_REQUEST)
class TargetAlreadyHasSpecification(Exception):
    """The ISpecificationTarget already has a specification of that name."""

    def __init__(self, target, name):
        msg = "There is already a blueprint named %s for %s." % (
                name, target.displayname)
        super().__init__(msg)
