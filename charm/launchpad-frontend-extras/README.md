# Extra Launchpad frontend configuration

This charm provides various odds and ends for Launchpad frontends that don't
fit in anywhere else.

Assuming that the `haproxy` charm has been deployed as the `services-lb`
application and that the `apache2` charm has been deployed as the
`frontend-main` application, as in lp:launchpad-mojo-specs, the following
relations are useful:

    juju relate launchpad-frontend-extras:juju-info services-lb:juju-info
    juju relate launchpad-frontend-extras:apache-website frontend-main:apache-website

This charm can also be related to the `frontend-librarian` application
(presumed to be an instance of the `apache2` charm) to publish librarian
logs over rsync for use by the `launchpad-scripts` charm:

    juju relate launchpad-frontend-extras:librarian-logs frontend-librarian:juju-info
