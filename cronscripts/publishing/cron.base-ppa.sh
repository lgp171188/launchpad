# shellcheck shell=bash
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# Initial setup for PPA cronscripts.

# DO NOT set LPCONFIG here, it should come from the crontab or the shell.
# Define common variables (also used by cron.daily-ppa).
if [ -z "$PPAROOT" ]; then
    PPAROOT=/srv/launchpad.net/ppa-archive
fi

# shellcheck disable=SC2034  # not used here, but used by cron.daily-ppa
if [ -z "$P3AROOT" ]; then
    P3AROOT=/srv/launchpad.net/private-ppa-archive
fi

LOCKFILE=$PPAROOT/.lock
# Default lockfile options, retry once if it's locked.
if [ "$LOCKFILEOPTIONS" == "" ]; then
   LOCKFILEOPTIONS="-r1"
fi

# Claim the lockfile.  ($LOCKFILEOPTIONS is deliberately unquoted, since it
# may expand to either zero words or one word.)
# shellcheck disable=SC2086
if ! lockfile $LOCKFILEOPTIONS "$LOCKFILE"; then
  echo "Could not claim lock file."
  exit 1
fi

# Cleanup the lockfile on exit.
cleanup () {
  echo "Cleaning up lockfile."
  rm -f "$LOCKFILE"
}

trap cleanup EXIT
