# Launchpad administrative tools

This charm provides administrative tools for use with a Launchpad
deployment.

You will need the following relations:

    juju relate launchpad-admin:db postgresql:db
    juju relate launchpad-admin:db-admin postgresql:db-admin
    juju relate launchpad-admin:session-db postgresql:db
    juju relate launchpad-admin rabbitmq-server

This will give you an environment you can SSH into for interactive database
tasks.

The `db` and `db-admin` commands give you `launchpad_main` and
superuser-level PostgreSQL clients respectively connected to the main
database, while the `db-session` command gives you a PostgreSQL client
connected to the session database.

You can run `/srv/launchpad/code/bin/iharness launchpad_main` to get an
interactive Python harness authenticated as `launchpad_main`.
