# Launchpad Native Publisher

This charm sets up and runs the Launchpad Native Publisher.

You will need the following relations:

    juju relate launchpad-native-publisher:db postgresql:db
    juju relate launchpad-native-publisher rabbitmq-server

This charm installs a cron job and celery workers to automatically publish
artifacts (rust crates, java jars, etc.) to their native package registry,
using native tooling (cargo, maven, etc.).

## Maintenance actions

To stop Celery workers (perhaps in preparation for a
schema upgrade), run:

    juju run-action --wait launchpad-native-publisher/leader stop-services

To start them again once maintenance is complete:

    juju run-action --wait launchpad-native-publisher/leader start-services
