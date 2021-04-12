-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- OCIRecipe privacy model is based only on ownership, similarly to Archives.
ALTER TABLE OCIRecipe
    ADD COLUMN information_type integer,
    ADD COLUMN access_policy integer,
    ADD COLUMN access_grants integer[];

COMMENT ON COLUMN OCIRecipe.information_type IS
    'Enum describing what type of information is stored, such as type of private or security related data, and used to determine to apply an access policy.';


CREATE TABLE OCIRecipeSubscription (
    id serial PRIMARY KEY,
    recipe integer NOT NULL REFERENCES OCIRecipe(id),
    person integer NOT NULL REFERENCES Person(id),
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    subscribed_by integer NOT NULL REFERENCES Person(id)
);

COMMENT ON TABLE OCIRecipeSubscription IS 'Person subscription for OCI recipe.';
COMMENT ON COLUMN OCIRecipeSubscription.person IS
    'The person who subscribed to the OCI recipe.';
COMMENT ON COLUMN OCIRecipeSubscription.recipe IS
    'The OCI recipe to which the person subscribed.';
COMMENT ON COLUMN OCIRecipeSubscription.date_created IS
    'When the subscription was created.';
COMMENT ON COLUMN OCIRecipeSubscription.subscribed_by IS
    'The person performing the action of subscribing someone to the OCI recipe.';

CREATE UNIQUE INDEX ocirecipesubscription__recipe__person__key
    ON OCIRecipeSubscription(recipe, person);

CREATE INDEX ocirecipesubscription__person__idx
    ON OCIRecipeSubscription(person);

CREATE INDEX ocirecipesubscription__subscribed_by__idx
    ON OCIRecipeSubscription(subscribed_by);

ALTER TABLE AccessArtifact
    ADD COLUMN ocirecipe integer REFERENCES OCIRecipe;


ALTER TABLE AccessArtifact DROP CONSTRAINT has_artifact;
ALTER TABLE AccessArtifact
    ADD CONSTRAINT has_artifact CHECK (
    (null_count(ARRAY[bug, branch, gitrepository, snap, specification, ocirecipe]) = 5)) NOT VALID;


CREATE OR REPLACE FUNCTION ocirecipe_denorm_access(ocirecipe_id integer)
    RETURNS void LANGUAGE plpgsql AS
$$
DECLARE
    info_type integer;
BEGIN
    SELECT
        -- information type: 1 = public
        COALESCE(ocirecipe.information_type, 1)
    INTO info_type
    FROM ocirecipe WHERE id = ocirecipe_id;

    UPDATE OCIRecipe
        SET access_policy = policies[1], access_grants = grants
        FROM
            build_access_cache(
                (SELECT id FROM accessartifact WHERE ocirecipe = ocirecipe_id),
                info_type)
            AS (policies integer[], grants integer[])
        WHERE id = ocirecipe_id;
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
    RETURN;
END;
$$;

COMMENT ON FUNCTION accessartifact_denorm_to_artifacts(artifact_id integer) IS
    'Denormalize the policy access and artifact grants to bugs, branches, git repositories, snaps, specifications and ocirecipe.';

-- A trigger to handle ocirecipe.information_type changes.
CREATE OR REPLACE FUNCTION ocirecipe_maintain_access_cache_trig() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    PERFORM ocirecipe_denorm_access(NEW.id);
    RETURN NULL;
END;
$$;

CREATE TRIGGER ocirecipe_maintain_access_cache
    AFTER INSERT OR UPDATE OF information_type ON OCIRecipe
    FOR EACH ROW EXECUTE PROCEDURE ocirecipe_maintain_access_cache_trig();

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 26, 3);
