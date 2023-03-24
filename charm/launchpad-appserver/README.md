# Launchpad application server

This charm runs a Launchpad application server.

You will need the following relations:

    juju relate launchpad-appserver:db postgresql:db
    juju relate launchpad-appserver:session-db postgresql:db
    juju relate launchpad-appserver memcached
    juju relate launchpad-appserver rabbitmq-server

By default the main application server runs on port 8085, and the XML-RPC
application server runs on port 8087.
