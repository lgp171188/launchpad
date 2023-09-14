# Launchpad copy-archive-publisher

This charm provides scripts which are sometimes used to publish test rebuilds
for Ubuntu.

Historically, they were used for the Ubuntu phone project.

You will need the following relations:

    juju relate launchpad-copy-archive-publisher:db postgresql:db
    juju relate launchpad-copy-archive-publisher rabbitmq-server
    juju relate launchpad-copy-archive-publisher nrpe
