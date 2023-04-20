# Launchpad librarian

This charm runs a Launchpad librarian.

You will need the following relations:

    juju relate launchpad-librarian:db postgresql:db
    juju relate launchpad-librarian:session-db postgresql:db
    juju relate launchpad-librarian rabbitmq-server

The librarian listens on four ports.  By default, these are:

- Public download: 8000
- Public upload: 9090
- Restricted download: 8005
- Restricted upload: 9095

As well as public files, the restricted ports allow access to restricted
files without authentication; firewall rules should ensure that they are
only accessible by other parts of Launchpad.

You will normally want to mount a persistent volume on
`/srv/launchpad/librarian/`.  (Even when writing uploads to Swift, this is
currently used as a temporary spool; it is therefore not currently valid to
deploy more than one unit of this charm.)
