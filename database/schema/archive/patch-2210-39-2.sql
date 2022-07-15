-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- STEP 4, COLD
-- Constraints, swap into place, and the rest.

-- Set KarmaCache._id to NOT NULL.
ALTER TABLE KarmaCache ALTER COLUMN _id SET NOT NULL;

-- We no longer need the trigger.
DROP TRIGGER karmacache_sync_id_t ON KarmaCache;
DROP FUNCTION karmacache_sync_id_t();

-- Fix the SEQUENCE owner, so it doesn't get removed when the old id column
-- is dropped.
ALTER SEQUENCE karmacache_id_seq OWNED BY KarmaCache._id;

-- Swap in the wide column.
ALTER TABLE KarmaCache DROP COLUMN id;
ALTER TABLE KarmaCache RENAME _id TO id;

-- Fix up the primary key.
ALTER INDEX karmacache_id_key RENAME TO karmacache_pkey;
ALTER TABLE KarmaCache
    ALTER COLUMN id SET DEFAULT nextval('karmacache_id_seq'),
    ADD CONSTRAINT karmacache_pkey PRIMARY KEY USING INDEX karmacache_pkey;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 39, 2);
