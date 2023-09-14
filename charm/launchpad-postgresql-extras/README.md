# Extra Launchpad PostgreSQL configuration

The `launchpad-postgresql-extras` subordinate adds extra things needed on
the Launchpad database units, particularly `pgbouncer` configuration and
some refinements to backup handling.

The following relation is useful:

    juju relate postgresql:juju-info launchpad-postgresql-extras:juju-info
