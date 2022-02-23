-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

CREATE TABLE vulnerability (
	id serial PRIMARY KEY,
	distribution integer REFERENCES Distribution NOT NULL,
	cve integer REFERENCES CVE,
	status integer,
	description text,
	notes text,
	mitigation text,
	importance integer NOT NULL,
	importance_explanation text,
	private boolean DEFAULT false NOT NULL
);

COMMENT ON TABLE vulnerability IS 'Expresses the notion of whether a CVE affects a distribution.';
COMMENT ON COLUMN vulnerability.distribution IS 'Indicates control by the pillar''s owner.';
COMMENT ON COLUMN vulnerability.cve IS 'Intentionally nullable, since we need to track vulnerabilities not associated with CVEs.';
COMMENT ON COLUMN vulnerability.status IS 'Indicates current status of the vulnerability.';
COMMENT ON COLUMN vulnerability.cve IS 'Overrides the cve description.';
COMMENT ON COLUMN vulnerability.notes IS 'Free-form notes; may need some formatting machinery.';
COMMENT ON COLUMN vulnerability.mitigation IS 'Explain why we''re ignoring something.';
COMMENT ON COLUMN vulnerability.importance IS 'Indicates work priority, not severity.';
COMMENT ON COLUMN vulnerability.importance_explanation IS 'Used to explain why our importance differs from somebody else''s CVSS score.';
COMMENT ON COLUMN vulnerability.private IS 'Indicates privacy of the vulnerability.';

CREATE INDEX vulnerability__distribution__cve__idx
    ON vulnerability (distribution, cve);

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
COMMENT ON COLUMN vulnerabilityactivity.vulnerability IS 'Indicates the vulnerability that the changes refer to.';
COMMENT ON COLUMN vulnerabilityactivity.changer IS 'Indicates the person that made the changes.';
COMMENT ON COLUMN vulnerabilityactivity.date_changed IS 'Indicates the date when the vulnerability details last changed.';
COMMENT ON COLUMN vulnerabilityactivity.what_changed IS 'Indicates what field changed for the vulnerability by means of an enum.';
COMMENT ON COLUMN vulnerabilityactivity.old_value IS 'Indicates the value prior to the change.';
COMMENT ON COLUMN vulnerabilityactivity.new_value IS 'Indicates the current value.';

CREATE INDEX vulnerabilityactivity__vulnerability__changer__idx
    ON vulnerabilityactivity (vulnerability, changer);

CREATE TABLE bugvulnerability (
	bug integer REFERENCES Bug NOT NULL,
	vulnerability integer REFERENCES Vulnerability NOT NULL
);

COMMENT ON TABLE bugvulnerability IS 'Links a vulnerability to the bug.';

CREATE INDEX bugvulnerability__bug__vulnerability__idx
    ON bugvulnerability (bug, vulnerability);

INSERT INTO LaunchpadDatabaseRevision VALUES (2210, 42, 0);
