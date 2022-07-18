-- Copyright 2022 Canonical Ltd.  This software is licensed under the
-- GNU Affero General Public License version 3 (see the file LICENSE).

SET client_min_messages=ERROR;

COMMENT ON TABLE public.builder IS 'Builder: This table stores the build-worker registry and status information as: name, url, trusted, builderok, builderaction, failnotes.';
COMMENT ON COLUMN public.builder.builderok IS 'Should a builder fail for any reason, from out-of-disk-space to not responding to the buildd manager, the builderok flag is set to false and the failnotes column is filled with a reason.';
COMMENT ON COLUMN public.builder.url IS 'The url to the build worker. There may be more than one build worker on a given host so this url includes the port number to use. The default port number for a build worker is 8221';
COMMENT ON COLUMN public.builder.version IS 'The version of launchpad-buildd on the worker.';
COMMENT ON COLUMN public.buildqueue.logtail IS 'The tail end of the log of the current build. This is updated regularly as the buildd manager polls the buildd workers. Once the build is complete; the full log will be lodged with the librarian and linked into the build table.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 00, 1);
