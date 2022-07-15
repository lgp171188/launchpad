-- Copyright 2019 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE INDEX branchmergeproposal__source_git_repository__source_git_path__idx
    ON BranchMergeProposal (source_git_repository, source_git_path);
CREATE INDEX branchmergeproposal__target_git_repository__target_git_path__idx
    ON BranchMergeProposal (target_git_repository, target_git_path);
CREATE INDEX branchmergeproposal__dependent_git_repository__dependent_git_path__idx
    ON BranchMergeProposal (dependent_git_repository, dependent_git_path);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 01, 2);
