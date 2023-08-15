-- Copyright 2023 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE RevisionStatusReport
    ADD COLUMN distro_arch_series integer REFERENCES distroarchseries;

COMMENT ON COLUMN RevisionStatusReport.distro_arch_series IS 'The series and architecture for the CI build job that produced this report.';

CREATE INDEX revisionstatusreport__distro_arch_series__idx
    ON RevisionStatusReport (distro_arch_series);

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 21, 0);
