# Launchpad codehosting

This charm sets up and runs the Launchpad codehosting service. It is
a subordinate charm that should be deployed on the same instance as a
primary apache2 charm. Let's call the apache2 charm application
`codehosting-apache2` for the purpose of the below explanation.

This charm also requires one or more `haproxy` instances reverse proxying
to it. Let us call these `codehosting-lb`, which proxies services
that have to be exposed to the internet and does TLS termination, and
`services-lb`, which proxies internal-only private services.

You will need the following relations:

    juju relate launchpad-codehosting:db postgresql:db
    juju relate launchpad-codehosting rabbitmq-server
    juju relate launchpad-codehosting:apache-website codehosting-apache2:apache-website
    juju relate launchpad-codehosting:loadbalancer services-lb:reverseproxy
    juju relate launchpad-codehosting:frontend-loadbalancer codehosting-lb:reverseproxy

In Canonical's deployment of this charm, an additional volume is provisioned and mounted
at the directory configured to store the `bzr` repositories.

* Create a Ceph volume of an appropriate size using a command like the
  one below to create this volume in the `qastaging` environment.

      openstack volume create --size 200 \
          --description 'Bazaar repositories - lp/qastaging' \
          lp-qastaging-bzr-repositories

* Attach this Ceph volume to the `launchpad-codehosting` unit using the following
  command. The instance ID of the `launchpad-codehosting` unit can be found
  from the output of the `juju status` command.

      openstack server add volume <instance id> lp-qastaging-bzr-repositories

* Log in to the `launchpad-codehosting` unit and perform the following steps.

* Create a filesystem on the new volume using `sudo mkfs.ext4 /dev/vdb`. Do
  check and verify that this device node matches the new volume.

* Create the `/srv/launchpad/data` directory, if it does not exist already.
  Here, `/srv/launchpad` corresponds to the `base_dir` template context
  variable.

* Add `/dev/vdb /srv/launchpad/data ext4 defaults 0 2` to `/etc/fstab`.

* Mount the new volume using `sudo mount /srv/launchpad/data`.

* Set the correct permissions on the new volume using the following commands.

      sudo chown launchpad: /srv/launchpad/data
      sudo chmod 755 /srv/launchpad/data

* Ensure that the `mirrors` directory exists in the new volume using
  `sudo -u launchpad mkdir -m755 /srv/launchpad/data/mirrors`.

## Maintenance actions

To stop bzr-sftp workers run:

    juju run-action --wait launchpad-codehosting/leader stop-services

To start them again once maintenance is complete:

    juju run-action --wait launchpad-codehosting/leader start-services
