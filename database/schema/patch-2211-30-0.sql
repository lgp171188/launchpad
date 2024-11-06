-- Copyright 2024 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

ALTER TABLE distribution ADD COLUMN content_templates JSONB;
ALTER TABLE distributionsourcepackage ADD COLUMN content_templates JSONB;
ALTER TABLE product ADD COLUMN content_templates JSONB;
ALTER TABLE ociproject ADD COLUMN content_templates JSONB;
ALTER TABLE project ADD COLUMN content_templates JSONB;

COMMENT ON COLUMN distribution.content_templates IS 'A JSON object that contains the content templates for a distribution'; 
COMMENT ON COLUMN distributionsourcepackage.content_templates IS 'A JSON object that contains the content templates for a distribution source package';
COMMENT ON COLUMN product.content_templates IS 'A JSON object that contains the content templates for a product';
COMMENT ON COLUMN ociproject.content_templates IS 'A JSON object that contains the content templates for an OCI project';
COMMENT ON COLUMN project.content_templates IS 'A JSON object that contains the content templates for a project';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 30, 0);

