# Launchpad build farm manager

This charm runs a service that supervises the Launchpad build farm.

You will need the following relations:

    juju relate launchpad-buildd-manager:db postgresql:db
    juju relate launchpad-buildd-manager rabbitmq-server

## Maintenance actions

To stop the build farm manager (perhaps in preparation for network
maintenance affecting the build farm), run:

    juju run-action --wait launchpad-buildd-manager/leader stop-services

To start them again once maintenance is complete:

    juju run-action --wait launchpad-buildd-manager/leader start-services
