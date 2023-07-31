# Extra Launchpad frontend configuration

This charm provides various odds and ends for Launchpad frontends that don't
fit in anywhere else.

Assuming that the `haproxy` charm has been deployed as the `services-lb`
application and that the `apache2` charm has been deployed as the
`main-frontend` application, as in lp:launchpad-mojo-specs, the following
relations are useful:

    juju relate launchpad-frontend-extras:juju-info services-lb:juju-info
    juju relate launchpad-frontend-extras:apache-website main-frontend:apache-website
