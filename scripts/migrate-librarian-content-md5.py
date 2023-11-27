#!/usr/bin/python3 -S
#
# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to generate SQL to add MD5 sums for existing librarian files."""

import _pythonpath  # noqa: F401

import os
import subprocess
import sys

SQL = "UPDATE LibraryFileContent SET md5 = '%s' WHERE id = %d;"


def main(path, minimumID=0):
    if not path.endswith("/"):
        path += "/"

    for dirpath, dirname, filenames in os.walk(path):
        dirname.sort()
        databaseID = dirpath[len(path) :]
        if not len(databaseID) == 8:  # "xx/xx/xx"
            continue
        for filename in filenames:
            databaseID = int(databaseID.replace("/", "") + filename, 16)
            if databaseID < minimumID:
                continue
            filename = os.path.join(dirpath, filename)
            md5sum = subprocess.check_output(
                ["md5sum", filename], text=True
            ).split(" ", 1)[0]
            yield databaseID, md5sum


if __name__ == "__main__":
    if len(sys.argv) > 2:
        minimumID = int(sys.argv[2])
    else:
        minimumID = 0
    for databaseID, md5sum in main(sys.argv[1], minimumID):
        print(SQL % (md5sum, databaseID))
