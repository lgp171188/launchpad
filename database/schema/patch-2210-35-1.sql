-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE INDEX snapbuild__snap__store_upload_revision__idx
ON SnapBuild(snap, store_upload_revision);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 35, 1);
