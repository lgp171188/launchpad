#!/usr/bin/env python
# Copyright 2005 Canonical Ltd.  All rights reserved.

import _pythonpath

import sys
from optparse import OptionParser

from zope.component import getUtility

from canonical.config import config
from canonical.lp import initZopeless
from canonical.lp.dbschema import TeamMembershipStatus
from canonical.launchpad.scripts import (
        execute_zcml_for_scripts, logger_options, logger
        )
from canonical.launchpad.scripts.lockfile import LockFile
from canonical.launchpad.interfaces import ITeamMembershipSet

_default_lock_file = '/var/lock/launchpad-flag-expired-memberships.lock'


def flag_expired_memberships():
    ztm = initZopeless(
        dbuser=config.expiredmembershipsflagger.dbuser, implicitBegin=False)

    ztm.begin()
    # XXX: Need to find out why this thing is not sending status change
    # notification emails.
    # XXX: Should probably use a celebrity here to indicate that it's not a
    # user who's flagging requests as expired.
    for membership in getUtility(ITeamMembershipSet).getMembershipsToExpire():
        membership.setStatus(TeamMembershipStatus.EXPIRED)
    ztm.commit()


if __name__ == '__main__':
    parser = OptionParser()
    logger_options(parser)
    (options, arguments) = parser.parse_args()
    if arguments:
        parser.error("Unhandled arguments %s" % repr(arguments))
    execute_zcml_for_scripts()

    log = logger(options, 'membershipupdater')
    log.info("Flagging expired team memberships.")

    lockfile = LockFile(_default_lock_file, logger=log)
    try:
        lockfile.acquire()
    except OSError:
        log.info("lockfile %s already exists, exiting", _default_lock_file)
        sys.exit(1)

    try:
        flag_expired_memberships()
    finally:
        lockfile.release()

    log.info("Finished flagging expired team memberships.")

