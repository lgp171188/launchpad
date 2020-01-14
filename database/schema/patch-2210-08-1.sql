-- Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE GitRepository
    ADD COLUMN ociprojectname integer REFERENCES ociprojectname,
    DROP CONSTRAINT one_container,
    ADD CONSTRAINT one_container CHECK (
        -- Project
        (project IS NOT NULL AND distribution IS NULL AND sourcepackagename IS NULL AND ociprojectname IS NULL) OR
        -- Distribution source package
        (project IS NULL AND distribution IS NOT NULL AND sourcepackagename IS NOT NULL AND ociprojectname IS NULL) OR
        -- Distribution OCI project
        (project IS NULL AND distribution IS NOT NULL AND sourcepackagename IS NULL AND ociprojectname IS NOT NULL) OR
        -- Personal
        (project IS NULL AND distribution IS NULL AND sourcepackagename IS NULL AND ociprojectname IS NULL));

COMMENT ON COLUMN GitRepository.ociprojectname IS 'The OCI project that this repository belongs to.';

-- Rename some indexes in preparation for replacing them with versions that
-- include the condition that sourcepackagename is non-NULL.

ALTER INDEX gitrepository__owner__distribution__sourcepackagename__name__key
    RENAME TO old__gitrepository__owner__distribution__sourcepackagename__name__key;
ALTER INDEX gitrepository__distribution__spn__target_default__key
    RENAME TO old__gitrepository__distribution__spn__target_default__key;
ALTER INDEX gitrepository__owner__distribution__spn__owner_default__key
    RENAME TO old__gitrepository__owner__distribution__spn__owner_default__key;
ALTER INDEX gitrepository__distribution__spn__date_last_modified__idx
    RENAME TO old__gitrepository__distribution__spn__date_last_modified__idx;
ALTER INDEX gitrepository__distribution__spn__id__idx
    RENAME TO old__gitrepository__distribution__spn__id__idx;
ALTER INDEX gitrepository__owner__distribution__spn__date_last_modified__idx
    RENAME TO old__gitrepository__owner__distribution__spn__date_last_modified__idx;
ALTER INDEX gitrepository__owner__distribution__spn__id__idx
    RENAME TO old__gitrepository__owner__distribution__spn__id__idx;

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 08, 1);
