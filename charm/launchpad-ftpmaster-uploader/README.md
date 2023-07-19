# Launchpad ftpmaster-uploader

Launchpad upload processor for the primary Ubuntu archive.

This charm deals with processing uploads to the primary Ubuntu archive.

You will need the following relations:

    juju relate launchpad-ftpmaster-uploader:db postgresql:db
    juju relate launchpad-ftpmaster-uploader rabbitmq-server
    juju relate launchpad-ftpmaster-uploader nrpe
    juju relate launchpad-ftpmaster-uploader txpkgupload
