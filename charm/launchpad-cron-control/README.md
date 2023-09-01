# Launchpad cron controller

This charm provides a centralized control mechanism for Launchpad's cron
jobs.  It must be related to an `apache2` charm as follows:

    juju relate launchpad-cron-control:apache-website frontend-cron-control:apache-website

Once deployed, it should typically be pointed to by DNS using the same name
as set in the `domain_cron_control` configuration option, and the
`cron_control_url` option in other Launchpad charms should be set to
`http://cron-control.launchpad.test/cron.ini` (substitute the appropriate
domain name).

## Actions

To disable all cron jobs by default:

    juju run-action --wait launchpad-cron-control/leader disable-cron-all

To disable a particular job:

    juju run-action --wait launchpad-cron-control/leader disable-cron job=publish-ftpmaster

To enable all cron jobs:

    juju run-action --wait launchpad-cron-control/leader enable-cron-all

To enable a particular job, even if `disable-cron-all` is in effect:

    juju run-action --wait launchpad-cron-control/leader enable-cron job=publish-ftpmaster
