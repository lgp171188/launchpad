-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- STEP 2, HOT
-- Backfill KarmaCache._id.
UPDATE KarmaCache SET _id=id WHERE _id IS NULL;

-- STEP 3, HOT
-- To be done CONCURRENTLY, create the UNIQUE index on KarmaCache._id.
CREATE UNIQUE INDEX karmacache_id_key ON KarmaCache(_id);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 39, 1);
