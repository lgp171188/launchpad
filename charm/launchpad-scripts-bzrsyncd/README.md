# Launchpad scripts - bzrsyncd

This charm sets up and runs the Launchpad bzrsyncd scripts and Celery workers.

You will need the following relations:

    juju relate launchpad-scripts-bzrsyncd:db postgresql:db
    juju relate launchpad-scripts-bzrsyncd memcached
    juju relate launchpad-scripts-bzrsyncd rabbitmq-server

## Maintenance actions

To stop Celery workers (perhaps in preparation for a schema upgrade), run:

    juju run-action --wait launchpad-scripts-bzrsyncd/leader stop-services

To start them again once maintenance is complete:

    juju run-action --wait launchpad-scripts-bzrsyncd/leader start-services
