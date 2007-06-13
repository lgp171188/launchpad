SET client_min_messages=ERROR;

CREATE TABLE Entitlement (
    id SERIAL PRIMARY KEY,

    person int NOT NULL REFERENCES Person,
    entitlement_type integer NOT NULL,
    quota integer NOT NULL,
    amount_used integer DEFAULT 0 NOT NULL,

    date_starts timestamp WITHOUT TIME ZONE NOT NULL,
    date_expires timestamp WITHOUT TIME ZONE NOT NULL,

    registrant int REFERENCES Person, -- NULL if autogenerated
    date_created timestamp WITHOUT TIME ZONE NOT NULL
        DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    approved_by int REFERENCES Person, -- NULL if autoapproved
    date_approved timestamp WITHOUT TIME ZONE, -- NULL if autoapproved

    status integer DEFAULT 0 NOT NULL,

    whiteboard text
);

-- Indexes for people merge
CREATE INDEX entitlement__person__idx ON Entitlement(person);
CREATE INDEX entitlement__registrant__idx ON Entitlement(registrant)
    WHERE registrant IS NOT NULL;
CREATE INDEX entitlement__approved_by__idx ON Entitlement(approved_by)
    WHERE approved_by IS NOT NULL;

-- Support for
-- SELECT * FROM Entitlement
-- WHERE
--   CURRENT_TIMESTAMP AT TIME ZONE 'UTC' BETWEEN date_starts AND date_expires
--   AND entitlement_type=42
--   AND person=69∆
--   AND status=0
CREATE INDEX entitlement_lookup_idx
    ON Entitlement(date_starts, date_expires, entitlement_type, person, status);


INSERT INTO LaunchpadDatabaseRevision VALUES (87, 18, 0);
