-- Copyright 2025 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE BranchMergeProposal
    ADD COLUMN merge_type integer DEFAULT 0 NOT NULL;

COMMENT ON COLUMN BranchMergeProposal.merge_type
    IS 'The type of merge used in proposal merged through launchpad API';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 40, 0);
