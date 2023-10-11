# Launchpad database schema updates

This charm provides tools for managing schema updates of Launchpad
deployments.

Launchpad has two separate "trunk" branches: the `master` branch (feeding
`stable` after tests pass) and the `db-devel` branch (feeding `db-stable`
after tests pass).  On production, database permissions are updated on each
deployment from `stable`, and full database schema updates are applied
separately from `db-stable`.

For a simple local deployment, you will need the following relations:

    juju relate launchpad-db-update:db postgresql:db
    juju relate launchpad-db-update:db-admin postgresql:db-admin
    juju relate launchpad-db-update rabbitmq-server

An action is available to perform a schema update:

    juju run-action --wait launchpad-db-update/leader db-update

## pgbouncer management

In deployments that use it, this charm can administer the `pgbouncer` load
balancer to disable connections to the primary database for the duration of
the update.

To use this mode, you need to use the
[external-services](https://code.launchpad.net/~ubuntuone-hackers/external-services/+git/external-services)
proxy charm in place of relating directly to `postgresql`, in order to have
greater control over connection strings.  `external-services` will need to
be configured along the lines of the following:

    options:
      db_connections: |
        launchpad_db_update:
          master: "postgresql://user:password@host:port/dbname"
          standbys: []
          admin: "postgresql://user:password@host:port/dbname"
        launchpad_pgbouncer:
          master: "postgresql://user:password@host:port/dbname"

`launchpad_db_update` and `launchpad_pgbouncer` may have other names if
needed as long as they match the `databases` option below;
`launchpad_db_update` must define a direct connection to the primary
database, bypassing `pgbouncer`, while `launchpad_pgbouncer` must define a
connection to `pgbouncer` itself.

`launchpad-db-update` will need configuration similar to the following (the
values of the entries in `databases` serve as keys into the `db_connections`
option above):

    options:
      databases: |
        db:
          name: "launchpad_db_update"
        pgbouncer:
          name: "launchpad_pgbouncer"

You will need the following relations:

    juju relate launchpad-db-update:db external-services:db
    juju relate launchpad-db-update:db-admin external-services:db-admin
    juju relate launchpad-db-update:pgbouncer external-services:db
    juju relate launchpad-db-update rabbitmq-server

In this mode, an additional action is available:

    juju run-action --wait launchpad-db-update/leader preflight

This checks whether the system is ready for a database schema update (i.e.
that no processes are connected that would have problems if they were
interrupted).  The operator should ensure that it succeeds before running
the `db-update` action.
