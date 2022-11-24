-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Builder
    ADD COLUMN open_resources jsonb,
    ADD COLUMN restricted_resources jsonb;
ALTER TABLE BuildQueue ADD COLUMN builder_constraints jsonb;
ALTER TABLE CIBuild ADD COLUMN builder_constraints jsonb;
ALTER TABLE GitRepository ADD COLUMN builder_constraints jsonb;

COMMENT ON COLUMN Builder.open_resources IS 'An array of resource tags offered by this builder, that can be required by a build and if required must match.';
COMMENT ON COLUMN Builder.restricted_resources IS 'An array of resource tags offered by this builder, indicating that the builder may only be used by builds that explicitly require these tags.';
COMMENT ON COLUMN BuildQueue.builder_constraints IS 'An array of builder resource tags required by the associated build farm job.';
COMMENT ON COLUMN CIBuild.builder_constraints IS 'An array of builder resource tags required by this CI build.';
COMMENT ON COLUMN GitRepository.builder_constraints IS 'An array of builder resource tags required by builds of this repository.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 13, 0);
