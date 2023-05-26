# Launchpad Debian importer

This charm runs a job that imports Debian packages into Launchpad.

You will need the following relations:

    juju relate launchpad-debian-importer:db postgresql:db
    juju relate launchpad-debian-importer rabbitmq-server

You will also need to set the `librarian_upload_host` and
`librarian_upload_port` options to point to a local
[launchpad-librarian](https://charmhub.io/launchpad-librarian) instance;
this is not currently handled using relations.
