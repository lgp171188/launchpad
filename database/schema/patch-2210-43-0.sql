-- Copyright 2022 Canonical Ltd. This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE Cve
    ADD COLUMN date_made_public timestamp without time zone,
    ADD COLUMN discoverer integer REFERENCES Person,
    ADD COLUMN cvss jsonb;

COMMENT ON COLUMN Cve.date_made_public IS 'The date on which the CVE was made public.';

COMMENT ON COLUMN Cve.discoverer IS 'The person who discovered this CVE.';

COMMENT ON COLUMN Cve.cvss IS 'The CVSS score for this CVE.';

CREATE INDEX cve__discoverer__idx ON Cve (discoverer);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 43, 0);
