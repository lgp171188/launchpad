-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- STEP 1, COLD
-- Add the new wide column to KarmaCache.
ALTER TABLE KarmaCache ADD COLUMN _id bigint;

-- KarmaCache needs an INSERT trigger, ensuring that new rows get a
-- KarmaCache._id matching KarmaCache.id.
CREATE FUNCTION karmacache_sync_id_t() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW._id := NEW.id;
    RETURN NEW;
END;
$$;

CREATE TRIGGER karmacache_sync_id_t
    BEFORE INSERT ON KarmaCache
    FOR EACH ROW EXECUTE PROCEDURE karmacache_sync_id_t();


-- Subsequent statements, to be executed live and in subsequent patches
-- after timing and optimization.

/*
-- STEP 2, HOT
-- Backfill KarmaCache._id, but do so in small batches.
UPDATE KarmaCache SET _id=id WHERE _id IS NULL;


-- STEP 3, HOT
-- To be done CONCURRENTLY, create the UNIQUE index on KarmaCache._id.
CREATE UNIQUE INDEX karmacache_id_key ON KarmaCache(_id);


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
*/

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 39, 0);
