# Launchpad build farm manager

This charm runs a service that supervises the Launchpad build farm.

You will need the following relations:

    juju relate launchpad-buildd-manager:db postgresql:db
    juju relate launchpad-buildd-manager rabbitmq-server
