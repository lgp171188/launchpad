-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Webhook ADD COLUMN git_ref_pattern text;
ALTER TABLE CIBuild ADD COLUMN git_refs text[];

COMMENT ON COLUMN Webhook.git_ref_pattern IS 'Pattern to use to filter git repository webhook triggers by their git refs.';
COMMENT ON COLUMN CIBuild.git_refs IS 'Git refs that originated the CI Build.';

ALTER TABLE Webhook ADD CONSTRAINT ref_pattern_for_git CHECK (
    (git_ref_pattern IS NULL OR git_repository IS NOT NULL)
);

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 20, 0);
