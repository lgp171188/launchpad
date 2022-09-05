-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Vulnerability
    ADD COLUMN date_notice_issued timestamp without time zone
;

ALTER TABLE Vulnerability
    ADD COLUMN date_coordinated_release timestamp without time zone
;

COMMENT ON COLUMN Vulnerability.date_notice_issued
    IS 'Date when a security notice was issued for this vulnerability';

COMMENT ON COLUMN Vulnerability.date_coordinated_release
    IS 'Coordinated Release Date';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 04, 0);
