# Launchpad scripts

This charm sets up and runs the Launchpad scripts.

You will need the following relations:

    juju relate launchpad-scripts:db postgresql:db
    juju relate launchpad-scripts:session-db postgresql:db
    juju relate launchpad-scripts memcached
    juju relate launchpad-scripts rabbitmq-server
