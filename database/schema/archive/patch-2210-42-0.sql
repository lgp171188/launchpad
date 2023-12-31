-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE vulnerability (
    id serial PRIMARY KEY,
    distribution integer REFERENCES Distribution NOT NULL,
    cve integer REFERENCES CVE,
    status integer NOT NULL,
    description text,
    notes text,
    mitigation text,
    importance integer NOT NULL,
    importance_explanation text,
    information_type integer DEFAULT 1 NOT NULL,
    date_created timestamp without time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    creator integer REFERENCES Person NOT NULL,
    date_made_public timestamp without time zone
);

COMMENT ON TABLE vulnerability IS 'Expresses the notion of whether a CVE affects a distribution.';
COMMENT ON COLUMN vulnerability.distribution IS 'The distribution affected by this vulnerability.';
COMMENT ON COLUMN vulnerability.cve IS 'The external CVE reference corresponding to this vulnerability, if any.';
COMMENT ON COLUMN vulnerability.status IS 'Indicates current status of the vulnerability.';
COMMENT ON COLUMN vulnerability.description IS 'Overrides the Cve.description.';
COMMENT ON COLUMN vulnerability.notes IS 'Free-form notes.';
COMMENT ON COLUMN vulnerability.mitigation IS 'Explain why we''re ignoring something.';
COMMENT ON COLUMN vulnerability.importance IS 'Indicates work priority, not severity.';
COMMENT ON COLUMN vulnerability.importance_explanation IS 'Used to explain why our importance differs from somebody else''s CVSS score.';
COMMENT ON COLUMN vulnerability.information_type IS 'Indicates privacy of the vulnerability.';
COMMENT ON COLUMN vulnerability.date_created IS 'The date when the vulnerability was created.';
COMMENT ON COLUMN vulnerability.creator IS 'The person that created the vulnerability.';
COMMENT ON COLUMN vulnerability.date_made_public IS 'The date this vulnerability was made public.';

CREATE UNIQUE INDEX vulnerability__distribution__cve__key
    ON vulnerability (distribution, cve);

CREATE INDEX vulnerability__cve__idx
    ON vulnerability (cve);

CREATE INDEX vulnerability__creator__idx
    ON vulnerability (creator);

CREATE TABLE vulnerabilityactivity (
    id serial PRIMARY KEY,
    vulnerability integer REFERENCES Vulnerability NOT NULL,
    changer integer REFERENCES Person NOT NULL,
    date_changed timestamp without time zone NOT NULL,
    what_changed integer NOT NULL,
    old_value text,
    new_value text
);

COMMENT ON TABLE vulnerabilityactivity IS 'Tracks changes to vulnerability rows.';
COMMENT ON COLUMN vulnerabilityactivity.vulnerability IS 'The vulnerability that the changes refer to.';
COMMENT ON COLUMN vulnerabilityactivity.changer IS 'The person that made the changes.';
COMMENT ON COLUMN vulnerabilityactivity.date_changed IS 'The date when the vulnerability details last changed.';
COMMENT ON COLUMN vulnerabilityactivity.what_changed IS 'Indicates what field changed for the vulnerability by means of an enum.';
COMMENT ON COLUMN vulnerabilityactivity.old_value IS 'The value prior to the change.';
COMMENT ON COLUMN vulnerabilityactivity.new_value IS 'The current value.';

CREATE INDEX vulnerabilityactivity__vulnerability__date_changed__idx
    ON vulnerabilityactivity (vulnerability, date_changed);

CREATE INDEX vulnerabilityactivity__changer__idx
    ON vulnerabilityactivity (changer);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 42, 0);
