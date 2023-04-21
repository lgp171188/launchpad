-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Webhook
    ADD COLUMN project integer REFERENCES product,
    ADD COLUMN distribution integer REFERENCES distribution,
    ADD COLUMN source_package_name integer REFERENCES sourcepackagename;

-- Add indexes to new columns
CREATE INDEX webhook__project__id__idx
    ON webhook(project, id) WHERE project IS NOT NULL;

CREATE INDEX webhook__distribution__id__idx
    ON webhook(distribution, id) WHERE distribution IS NOT NULL;

CREATE INDEX webhook__source_package_name__id__idx
    ON webhook(source_package_name, id) WHERE source_package_name IS NOT NULL;

-- There can only be one target, but when the target is source_package_name
-- then both source_package_name and distribution columns should have a value
ALTER TABLE Webhook
    DROP CONSTRAINT one_target,
    ADD CONSTRAINT one_target CHECK (
        (public.null_count(ARRAY[git_repository, branch, snap, livefs, oci_recipe, charm_recipe, project, distribution]) = 7) AND
        (source_package_name IS NULL OR distribution IS NOT NULL)
    );

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 19, 0);
