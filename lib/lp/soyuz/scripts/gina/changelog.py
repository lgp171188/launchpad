# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

"""Gina's changelog parser and muncher for great justice"""

import re
import sys

import six

from lp.archivepublisher.debversion import Version


first_re = re.compile(br"^([a-z0-9][a-z0-9\\+\\.\\-]+)\s+\(([^ ]+)\)")
urgency_re = re.compile(br'(?:urgency|priority)=([^ ,;:.]+)')


def parse_first_line(line):
    # SRCPKGNAME (VERSION).*((urgency|priority)=\S+)?
    match = first_re.match(line)
    if not match:
        raise ValueError(line)
    srcpkg = match.group(1)
    version = match.group(2)

    urgency = None
    match = urgency_re.search(line)
    if match:
        # XXX kiko 2005-11-05: Why do we do lower() here?
        urgency = match.group(1).lower()

    return (srcpkg, version, urgency)


def parse_last_line(line):
    maint = line[:line.find(b">") + 1].strip()
    date = line[line.find(b">") + 1:].strip()
    return (maint, date)


def parse_changelog_stanza(firstline, stanza, lastline):
    srcpkg, version, urgency = parse_first_line(firstline)
    maint, date = parse_last_line(lastline)

    return {
        "package": srcpkg,
        "version": version,
        "urgency": urgency,
        "maintainer": maint,
        "date": date,
        "changes": b"".join(stanza).strip(b"\n")
    }


def parse_changelog(changelines):
    state = 0
    firstline = b""
    stanza = []
    rets = []

    for line in changelines:
        #print line[:-1]
        if state == 0:
            if (line.startswith(b" ") or line.startswith(b"\t") or
                not line.rstrip()):
                #print "State0 skip"
                continue
            try:
                (source, version, urgency) = parse_first_line(line.strip())
                Version(six.ensure_text(version))
            except Exception:
                stanza.append(line)
                #print "state0 Exception skip"
                continue
            firstline = line.strip()
            stanza = [line, b'\n']
            state = 1
            continue

        if state == 1:
            stanza.append(line)
            stanza.append(b'\n')

            if line.startswith(b" --") and b"@" in line:
                #print "state1 accept"
                # Last line of stanza
                rets.append(parse_changelog_stanza(firstline,
                                                   stanza,
                                                   line.strip()[3:]))
                state = 0

    # leftovers with no close line
    if state == 1:
        rets[-1]["changes"] += firstline
        if len(rets):
            rets[-1]["changes"] += b"".join(stanza).strip(b"\n")

    return rets


if __name__ == '__main__':
    import pprint
    with open(sys.argv[1], "rb") as f:
        pprint.pprint(parse_changelog(f))
