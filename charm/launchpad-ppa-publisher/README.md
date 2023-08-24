# Launchpad PPA Publisher

This charm runs a Launchpad PPA publisher. Takes all PPAs that are pending
in the database (added there by a launchpad-ppa-uploader unit) and arranges
for contents of the disk to match.

You will need the following relations:

```
    juju relate launchpad-ppa-publisher:apache-website apache2:apache-website
    juju relate launchpad-ppa-publisher:db postgresql:db
    juju relate launchpad-ppa-publisher rabbitmq-server
    juju relate launchpad-ppa-publisher nrpe
    juju relate launchpad-ppa-publisher memcached
```
