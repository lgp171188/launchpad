-- Copyright 2010 Canonical Ltd. This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE IncrementalDiff(
    id serial PRIMARY KEY,
    diff integer NOT NULL CONSTRAINT diff_fk REFERENCES Diff ON DELETE CASCADE,
    branch_merge_proposal integer NOT NULL CONSTRAINT branch_merge_proposal_fk REFERENCES BranchMergeProposal ON DELETE CASCADE,
    old_revision integer NOT NULL CONSTRAINT old_revision_fk REFERENCES Revision ON DELETE CASCADE,
    new_revision integer NOT NULL CONSTRAINT new_revision_fk REFERENCES Revision ON DELETE CASCADE);

INSERT INTO LaunchpadDatabaseRevision VALUES (2207, 99, 0);
