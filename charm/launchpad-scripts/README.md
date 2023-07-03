# Launchpad scripts

This charm sets up and runs the Launchpad scripts.

You will need the following relations:

    juju relate launchpad-scripts:db postgresql:db
    juju relate launchpad-scripts:session-db postgresql:db
    juju relate launchpad-scripts memcached
    juju relate launchpad-scripts rabbitmq-server

## Maintenance actions

To stop Celery workers and `number-cruncher` (perhaps in preparation for a
schema upgrade), run:

    juju run-action --wait launchpad-scripts/leader stop-services

To start them again once maintenance is complete:

    juju run-action --wait launchpad-scripts/leader start-services
