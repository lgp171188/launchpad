-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Vulnerability
    ADD COLUMN access_policy integer,
    ADD COLUMN access_grants integer[];

CREATE TABLE VulnerabilitySubscription (
    id serial PRIMARY KEY,
    person integer REFERENCES Person NOT NULL,
    vulnerability integer REFERENCES Vulnerability NOT NULL,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    subscribed_by integer REFERENCES Person NOT NULL
);

COMMENT ON TABLE VulnerabilitySubscription IS 'Person subscription for Vulnerabilities.';
COMMENT ON COLUMN VulnerabilitySubscription.person IS 'The person subscribing to the vulnerability.';
COMMENT ON COLUMN VulnerabilitySubscription.vulnerability IS 'The vulnerability being subscribed to.';
COMMENT ON COLUMN VulnerabilitySubscription.date_created IS 'The date when the subscription was created.';
COMMENT ON COLUMN VulnerabilitySubscription.subscribed_by IS 'The person who created the subscription.';

CREATE UNIQUE INDEX vulnerabilitysubscription__person__vulnerability__key
    ON VulnerabilitySubscription (person, vulnerability);

CREATE INDEX vulnerabilitysubscription__vulnerability__idx
    ON VulnerabilitySubscription (vulnerability);

CREATE INDEX vulnerabilitysubscription__subscribed_by__idx
    ON VulnerabilitySubscription (subscribed_by);

ALTER TABLE AccessArtifact
    ADD COLUMN vulnerability integer REFERENCES Vulnerability;


ALTER TABLE AccessArtifact DROP CONSTRAINT has_artifact;
ALTER TABLE AccessArtifact
    ADD CONSTRAINT has_artifact CHECK (
    (null_count(ARRAY[bug, branch, gitrepository, snap, specification, ocirecipe, vulnerability]) = 6)) NOT VALID;


CREATE OR REPLACE FUNCTION vulnerability_denorm_access(vulnerability_id integer)
    RETURNS void LANGUAGE plpgsql AS
$$
DECLARE
    info_type integer;
BEGIN
    SELECT Vulnerability.information_type INTO info_type
    FROM Vulnerability where id = vulnerability_id;

    UPDATE Vulnerability
        SET access_policy = policies[1], access_grants = grants
        FROM
            build_access_cache(
                (SELECT id FROM accessartifact WHERE vulnerability = vulnerability_id),
                info_type)
            AS (policies integer[], grants integer[])
        WHERE id = vulnerability_id;
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
    IF artifact_row.ocirecipe IS NOT NULL THEN
        PERFORM ocirecipe_denorm_access(artifact_row.ocirecipe);
    END IF;
    IF artifact_row.vulnerability IS NOT NULL THEN
        PERFORM vulnerability_denorm_access(artifact_row.vulnerability);
    END IF;
    RETURN;
END;
$$;

COMMENT ON FUNCTION accessartifact_denorm_to_artifacts(artifact_id integer) IS
    'Denormalize the policy access and artifact grants to bugs, branches, git repositories, snaps, specifications, ocirecipes, and vulnerabilities.';

-- A trigger to handle vulnerability.information_type changes.
CREATE OR REPLACE FUNCTION vulnerability_maintain_access_cache_trig() RETURNS trigger
    LANGUAGE plpgsql as $$
BEGIN
    PERFORM vulnerability_denorm_access(NEW.id);
    RETURN NULL;
END;
$$;

CREATE TRIGGER vulnerability_maintain_access_cache
    AFTER INSERT OR UPDATE OF information_type ON Vulnerability
    FOR EACH ROW EXECUTE PROCEDURE vulnerability_maintain_access_cache_trig();

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 02, 0);
