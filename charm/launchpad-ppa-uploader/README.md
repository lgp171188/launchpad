# Launchpad PPA Uploader

Processes PPA uploads from users, inserting them into the database if they
are properly authorized and well-formed.

You will need the following relations:

```
    juju relate launchpad-ppa-uploader:db postgresql:db
    juju relate launchpad-ppa-uploader nrpe
    juju relate launchpad-ppa-uploader rabbitmq-server
    juju relate launchpad-ppa-uploader txpkgupload
```
