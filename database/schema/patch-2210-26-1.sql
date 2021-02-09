-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Snap
    ADD COLUMN project integer REFERENCES product,
    ADD COLUMN access_policy integer,
    ADD COLUMN access_grants integer[];

COMMENT ON COLUMN Snap.project IS 'The project which is the pillar for this Snap';

CREATE TABLE SnapSubscription (
    id serial NOT NULL PRIMARY KEY,
    person integer NOT NULL REFERENCES Person(id),
    snap integer NOT NULL REFERENCES Snap(id),
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    subscribed_by integer NOT NULL REFERENCES Person(id)
);

CREATE UNIQUE INDEX snapsubscription__person_snap__key
    ON SnapSubscription(snap, person);

CREATE INDEX snapsubscription__person__idx
    ON SnapSubscription(person);

ALTER TABLE AccessArtifact
    ADD COLUMN snap integer REFERENCES snap;

CREATE UNIQUE INDEX accessartifact__snap__key
    ON AccessArtifact(snap) WHERE snap IS NOT NULL;


ALTER TABLE AccessArtifact DROP CONSTRAINT has_artifact;
ALTER TABLE AccessArtifact
    ADD CONSTRAINT has_artifact CHECK (
    (null_count(ARRAY[bug, branch, gitrepository, snap, specification]) = 4));


CREATE OR REPLACE FUNCTION snap_denorm_access(snap_id integer)
    RETURNS void LANGUAGE plpgsql AS
$$
DECLARE
    information_type integer;
BEGIN
    SELECT
        -- information type: 1 = public; 5 = proprietary
        CASE WHEN private THEN 5 ELSE 1 END
    INTO information_type
    FROM snap WHERE id = snap_id;

    UPDATE Snap
        SET access_policy = policies[1], access_grants = grants
        FROM
            build_access_cache(
                (SELECT id FROM accessartifact WHERE snap = snap_id),
                information_type)
            AS (policies integer[], grants integer[])
        WHERE id = snap_id;
END;
$$;

CREATE OR REPLACE FUNCTION accessartifact_denorm_to_artifacts(artifact_id integer)
    RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    artifact_row accessartifact%ROWTYPE;
BEGIN
    SELECT * INTO artifact_row FROM accessartifact WHERE id = artifact_id;
    IF artifact_row.bug IS NOT NULL THEN
        PERFORM bug_flatten_access(artifact_row.bug);
    END IF;
    IF artifact_row.branch IS NOT NULL THEN
        PERFORM branch_denorm_access(artifact_row.branch);
    END IF;
    IF artifact_row.gitrepository IS NOT NULL THEN
        PERFORM gitrepository_denorm_access(artifact_row.gitrepository);
    END IF;
    IF artifact_row.snap IS NOT NULL THEN
        PERFORM snap_denorm_access(artifact_row.snap);
    END IF;
    IF artifact_row.specification IS NOT NULL THEN
        PERFORM specification_denorm_access(artifact_row.specification);
    END IF;
    RETURN;
END;
$$;

COMMENT ON FUNCTION accessartifact_denorm_to_artifacts(artifact_id integer) IS
    'Denormalize the policy access and artifact grants to bugs, branches, git repositories, snaps, and specifications.';

-- A trigger to handle snap.{private,project} changes.
CREATE OR REPLACE FUNCTION snap_maintain_access_cache_trig() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    PERFORM snap_denorm_access(NEW.id);
    RETURN NULL;
END;
$$;

CREATE TRIGGER snap_maintain_access_cache
    AFTER INSERT OR UPDATE OF private, project ON Snap
    FOR EACH ROW EXECUTE PROCEDURE snap_maintain_access_cache_trig();


INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 26, 1);
