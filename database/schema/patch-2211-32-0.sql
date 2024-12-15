SET client_min_messages=ERROR;

CREATE OR REPLACE FUNCTION public.activity() RETURNS SETOF pg_stat_activity
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    a pg_stat_activity%ROWTYPE;
BEGIN
    IF EXISTS (
            SELECT 1 FROM pg_attribute WHERE
                attrelid =
                    (SELECT oid FROM pg_class
                     WHERE relname = 'pg_stat_activity')
                AND attname = 'leader_pid') THEN
        -- >= 13
        RETURN QUERY SELECT
            datid, datname, pid, leader_pid, usesysid, usename,
            application_name, client_addr, client_hostname, client_port,
            backend_start, xact_start, query_start, state_change,
            wait_event_type, wait_event, state, backend_xid, backend_xmin,
            query_id, backend_type,
            CASE
                WHEN query LIKE '<IDLE>%'
                    OR query LIKE 'autovacuum:%'
                    THEN query
                ELSE
                    '<HIDDEN>'
            END AS query
        FROM pg_catalog.pg_stat_activity;
    ELSIF EXISTS (
            SELECT 1 FROM pg_attribute WHERE
                attrelid =
                    (SELECT oid FROM pg_class
                     WHERE relname = 'pg_stat_activity')
                AND attname = 'backend_type') THEN
        -- >= 10
        RETURN QUERY SELECT
            datid, datname, pid, usesysid, usename, application_name,
            client_addr, client_hostname, client_port, backend_start,
            xact_start, query_start, state_change, wait_event_type,
            wait_event, state, backend_xid, backend_xmin, backend_type,
            CASE
                WHEN query LIKE '<IDLE>%'
                    OR query LIKE 'autovacuum:%'
                    THEN query
                ELSE
                    '<HIDDEN>'
            END AS query
        FROM pg_catalog.pg_stat_activity;
    ELSIF EXISTS (
            SELECT 1 FROM pg_attribute WHERE
                attrelid =
                    (SELECT oid FROM pg_class
                     WHERE relname = 'pg_stat_activity')
                AND attname = 'wait_event_type') THEN
        -- >= 9.6
        RETURN QUERY SELECT
            datid, datname, pid, usesysid, usename, application_name,
            client_addr, client_hostname, client_port, backend_start,
            xact_start, query_start, state_change, wait_event_type,
            wait_event, state, backend_xid, backend_xmin,
            CASE
                WHEN query LIKE '<IDLE>%'
                    OR query LIKE 'autovacuum:%'
                    THEN query
                ELSE
                    '<HIDDEN>'
            END AS query
        FROM pg_catalog.pg_stat_activity;
    ELSIF EXISTS (
            SELECT 1 FROM pg_attribute WHERE
                attrelid =
                    (SELECT oid FROM pg_class
                     WHERE relname = 'pg_stat_activity')
                AND attname = 'backend_xid') THEN
        -- >= 9.4
        RETURN QUERY SELECT
            datid, datname, pid, usesysid, usename, application_name,
            client_addr, client_hostname, client_port, backend_start,
            xact_start, query_start, state_change, waiting, state,
            backend_xid, backend_xmin,
            CASE
                WHEN query LIKE '<IDLE>%'
                    OR query LIKE 'autovacuum:%'
                    THEN query
                ELSE
                    '<HIDDEN>'
            END AS query
        FROM pg_catalog.pg_stat_activity;
    ELSE
        -- >= 9.2; anything older is unsupported
        RETURN QUERY SELECT
            datid, datname, pid, usesysid, usename, application_name,
            client_addr, client_hostname, client_port, backend_start,
            xact_start, query_start, state_change, waiting, state,
            CASE
                WHEN query LIKE '<IDLE>%'
                    OR query LIKE 'autovacuum:%'
                    THEN query
                ELSE
                    '<HIDDEN>'
            END AS query
        FROM pg_catalog.pg_stat_activity;
    END IF;
END;
$$;

COMMENT ON FUNCTION public.activity() IS 'SECURITY DEFINER wrapper around pg_stat_activity allowing unprivileged users to access most of its information.';

INSERT INTO LaunchpadDatabaseRevision VALUES (2211, 32, 0);
