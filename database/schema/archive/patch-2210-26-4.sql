-- Copyright 2021 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE UNIQUE INDEX accessartifact__ocirecipe__key
    ON AccessArtifact(ocirecipe) WHERE ocirecipe IS NOT NULL;

ALTER TABLE AccessArtifact VALIDATE CONSTRAINT has_artifact;


INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 26, 4);
