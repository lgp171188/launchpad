-- Copyright 2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

-- Create new UNIQUE constraints to replace existing distribution + ociprojectname ones.
CREATE UNIQUE INDEX gitrepository__owner__oci_project__name__key
    ON GitRepository (owner, oci_project, name)
    WHERE oci_project IS NOT NULL;

CREATE UNIQUE INDEX gitrepository__owner__oci_project__owner_default__key
    ON GitRepository (owner, oci_project)
    WHERE oci_project IS NOT NULL AND owner_default;

CREATE UNIQUE INDEX gitrepository__oci_project__target_default__key
    ON GitRepository (oci_project)
    WHERE oci_project IS NOT NULL AND target_default;


-- Create new indexes to replace existing ociprojectname ones
CREATE INDEX "gitrepository__oci_project__date_last_modified__idx"
    ON GitRepository (oci_project, date_last_modified)
    WHERE oci_project IS NOT NULL;

CREATE INDEX "gitrepository__oci_project__id__idx"
    ON GitRepository (oci_project, id)
    WHERE oci_project IS NOT NULL;

CREATE INDEX "gitrepository__owner__oci_project__date_last_modified__idx"
    ON GitRepository (owner, oci_project, date_last_modified)
    WHERE oci_project IS NOT NULL;

CREATE INDEX "gitrepository__owner__oci_project__id__idx"
    ON GitRepository (owner, oci_project, id)
    WHERE oci_project IS NOT NULL;


ALTER TABLE GitRepository VALIDATE CONSTRAINT one_container;
ALTER TABLE GitRepository VALIDATE CONSTRAINT default_implies_target;


INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 8, 9);
