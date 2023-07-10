# Launchpad ftpmaster-publisher

Launchpad publisher for the primary Ubuntu archive.

This charm deals with publishing the primary Ubuntu archive.

You will need the following relations:

    juju relate launchpad-ftpmaster-publisher:db postgresql:db
    juju relate launchpad-ftpmaster-publisher rabbitmq-server
    juju relate launchpad-ftpmaster-publisher nrpe
