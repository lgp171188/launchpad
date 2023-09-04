# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Common helpers for replication scripts."""

__all__ = []

import subprocess
from tempfile import NamedTemporaryFile
from textwrap import dedent

import psycopg2

from lp.services.config import config
from lp.services.database.postgresql import ConnectionString
from lp.services.database.sqlbase import (
    ISOLATION_LEVEL_DEFAULT,
    connect,
    sqlvalues,
)
from lp.services.scripts.logger import DEBUG2, log

# The Slony-I clustername we use with Launchpad. Hardcoded because there
# is no point changing this, ever.
CLUSTERNAME = "sl"

# The namespace in the database used to contain all the Slony-I tables.
CLUSTER_NAMESPACE = "_%s" % CLUSTERNAME

# Replication set id constants. Don't change these without DBA help.
LPMAIN_SET_ID = 1
HOLDING_SET_ID = 666
SSO_SET_ID = 3
LPMIRROR_SET_ID = 4


def slony_installed(con):
    """Return True if the connected database is part of a Launchpad Slony-I
    cluster.
    """
    cur = con.cursor()
    cur.execute(
        """
        SELECT TRUE FROM pg_class,pg_namespace
        WHERE
            nspname = %s
            AND relname = 'sl_table'
            AND pg_class.relnamespace = pg_namespace.oid
        """
        % sqlvalues(CLUSTER_NAMESPACE)
    )
    return cur.fetchone() is not None


def sync(timeout, exit_on_fail=True):
    """Generate a sync event and wait for it to complete on all nodes.

    This means that all pending events have propagated and are in sync
    to the point in time this method was called. This might take several
    hours if there is a large backlog of work to replicate.

    :param timeout: Number of seconds to wait for the sync. 0 to block
                    indefinitely.

    :param exit_on_fail: If True, on failure of the sync
                         SystemExit is raised using the slonik return code.

    :returns: True if the sync completed successfully. False if
              exit_on_fail is False and the script failed for any reason.
    """
    return execute_slonik("", sync=timeout, exit_on_fail=exit_on_fail)


def execute_slonik(script, sync=None, exit_on_fail=True, auto_preamble=True):
    """Use the slonik command line tool to run a slonik script.

    :param script: The script as a string. Preamble should not be included.

    :param sync: Number of seconds to wait for sync before failing. 0 to
                 block indefinitely.

    :param exit_on_fail: If True, on failure of the slonik script
                         SystemExit is raised using the slonik return code.

    :param auto_preamble: If True, the generated preamble will be
                          automatically included.

    :returns: True if the script completed successfully. False if
              exit_on_fail is False and the script failed for any reason.
    """

    # Add the preamble and optional sync to the script.
    if auto_preamble:
        script = preamble() + script

    if sync is not None:
        sync_script = dedent(
            """\
            sync (id = @primary_node);
            wait for event (
                origin = @primary_node, confirmed = ALL,
                wait on = @primary_node, timeout = %d);
            """
            % sync
        )
        script = script + sync_script

    # Copy the script to a NamedTemporaryFile rather than just pumping it
    # to slonik via stdin. This way it can be examined if slonik appears
    # to hang.
    script_on_disk = NamedTemporaryFile(prefix="slonik", suffix=".sk")
    print(script, file=script_on_disk, flush=True)

    # Run slonik
    log.debug("Executing slonik script %s" % script_on_disk.name)
    log.log(DEBUG2, "Running script:\n%s" % script)
    returncode = subprocess.call(["slonik", script_on_disk.name])

    if returncode != 0:
        log.error("slonik script failed")
        if exit_on_fail:
            raise SystemExit(1)

    return returncode == 0


class Node:
    """Simple data structure for holding information about a Slony node."""

    def __init__(self, node_id, nickname, connection_string, is_primary):
        self.node_id = node_id
        self.nickname = nickname
        self.connection_string = connection_string
        self.is_primary = is_primary

    def connect(self, isolation=ISOLATION_LEVEL_DEFAULT):
        con = psycopg2.connect(str(self.connection_string))
        con.set_isolation_level(isolation)
        return con


def _get_nodes(con, query):
    """Return a list of Nodes."""
    if not slony_installed(con):
        return []
    cur = con.cursor()
    cur.execute(query)
    nodes = []
    for node_id, nickname, connection_string, is_primary in cur.fetchall():
        nodes.append(Node(node_id, nickname, connection_string, is_primary))
    return nodes


def get_primary_node(con, set_id=1):
    """Return the primary Node, or None if the cluster is still being setup."""
    nodes = _get_nodes(
        con,
        """
        SELECT DISTINCT
            set_origin AS node_id,
            'primary',
            pa_conninfo AS connection_string,
            True
        FROM _sl.sl_set
        LEFT OUTER JOIN _sl.sl_path ON set_origin = pa_server
        WHERE set_id = %d
        """
        % set_id,
    )
    if not nodes:
        return None
    assert len(nodes) == 1, "More than one primary found for set %s" % set_id
    return nodes[0]


def get_standby_nodes(con, set_id=1):
    """Return the list of standby Nodes."""
    return _get_nodes(
        con,
        """
        SELECT DISTINCT
            pa_server AS node_id,
            'standby' || pa_server,
            pa_conninfo AS connection_string,
            False
        FROM _sl.sl_set
        JOIN _sl.sl_subscribe ON set_id = sub_set
        JOIN _sl.sl_path ON sub_receiver = pa_server
        WHERE
            set_id = %d
        ORDER BY node_id
        """
        % set_id,
    )


def get_nodes(con, set_id=1):
    """Return a list of all Nodes."""
    primary_node = get_primary_node(con, set_id)
    if primary_node is None:
        return []
    else:
        return [primary_node] + get_standby_nodes(con, set_id)


def get_all_cluster_nodes(con):
    """Return a list of all Nodes in the cluster.

    node.is_primary will be None, as this boolean doesn't make sense
    in the context of a cluster rather than a single replication set.
    """
    if not slony_installed(con):
        return []
    nodes = _get_nodes(
        con,
        """
        SELECT DISTINCT
            pa_server AS node_id,
            'node' || pa_server || '_node',
            pa_conninfo AS connection_string,
            NULL
        FROM _sl.sl_path
        ORDER BY node_id
        """,
    )
    if not nodes:
        # There are no subscriptions yet, so no paths. Generate the
        # primary Node.
        cur = con.cursor()
        cur.execute("SELECT no_id from _sl.sl_node")
        node_ids = [row[0] for row in cur.fetchall()]
        if len(node_ids) == 0:
            return []
        assert len(node_ids) == 1, "Multiple nodes but no paths."
        primary_node_id = node_ids[0]
        primary_connection_string = ConnectionString(
            config.database.rw_main_primary
        )
        primary_connection_string.user = "slony"
        return [
            Node(
                primary_node_id,
                "node%d_node" % primary_node_id,
                primary_connection_string,
                True,
            )
        ]
    return nodes


def preamble(con=None):
    """Return the preable needed at the start of all slonik scripts."""

    if con is None:
        con = connect(user="slony")

    primary_node = get_primary_node(con)
    nodes = get_all_cluster_nodes(con)
    if primary_node is None and len(nodes) == 1:
        primary_node = nodes[0]

    preamble = [
        dedent(
            """\
        #
        # Every slonik script must start with a clustername, which cannot
        # be changed once the cluster is initialized.
        #
        cluster name = sl;

        # Symbolic ids for replication sets.
        define lpmain_set   %d;
        define holding_set  %d;
        define sso_set      %d;
        define lpmirror_set %d;
        """
            % (LPMAIN_SET_ID, HOLDING_SET_ID, SSO_SET_ID, LPMIRROR_SET_ID)
        )
    ]

    if primary_node is not None:
        preamble.append(
            dedent(
                """\
        # Symbolic id for the main replication set primary node.
        define primary_node %d;
        define primary_node_conninfo '%s';
        """
                % (primary_node.node_id, primary_node.connection_string)
            )
        )

    for node in nodes:
        preamble.append(
            dedent(
                """\
            define %s %d;
            define %s_conninfo '%s';
            node @%s admin conninfo = @%s_conninfo;
            """
                % (
                    node.nickname,
                    node.node_id,
                    node.nickname,
                    node.connection_string,
                    node.nickname,
                    node.nickname,
                )
            )
        )

    return "\n\n".join(preamble)
