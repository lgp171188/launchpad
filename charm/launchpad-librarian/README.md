# Launchpad librarian

This charm runs a Launchpad librarian.

You will need the following relations:

    juju relate launchpad-librarian:db postgresql:db
    juju relate launchpad-librarian:session-db postgresql:db
    juju relate launchpad-librarian rabbitmq-server

You can also relate it to a load balancer, which is especially useful if you
set `workers` to something other than 1:

    juju relate launchpad-librarian:loadbalancer haproxy:reverseproxy

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

## Migrating between instances

Only one instance of the librarian may be active at any one time, and very
little downtime is acceptable on production.  This means that we have to be
especially careful when redeploying.  The general procedure is as follows:

1. Deploy a new unit with `active=false`.  This will disable periodic jobs
   that would modify the database, the contents of the librarian, or the
   contents of Swift.  Downloads are possible, and if uploads happen they
   will be spooled locally, but that's low-risk since only Launchpad itself
   uploads to the librarian.  This mode allows testing connectivity.

1. Create a Ceph volume for locally-spooled librarian data.  On production
   this should be a 2 TiB volume to allow some breathing room if uploading
   to Swift is temporarily unavailable: `openstack volume create --size 2048
   --type Ceph_NVMe --description 'spooled production librarian data'
   librarian-data`.

1. Attach this Ceph volume to the new unit using `openstack server add
   volume`.

1. On the librarian unit, create a filesystem on the new volume using `sudo
   mkfs.ext4 /dev/vdb` (check that this device node matches the new volume).

1. On the librarian unit, add `/dev/vdb /srv/launchpad/librarian ext4
   defaults 0 2` to `/etc/fstab`.

1. On the librarian unit, stop the librarian using `sudo systemctl stop
   launchpad-librarian.service`.

1. On the librarian unit, mount the new volume using `sudo mount
   /srv/launchpad/librarian`.

1. On the librarian unit, set the correct permissions on the new volume
   using `sudo chown launchpad:launchpad /srv/launchpad/librarian && sudo
   chmod 700 /srv/launchpad/librarian`.

1. On the librarian unit, start the librarian using `sudo systemctl start
   launchpad-librarian.service`.

1. On the librarian unit, run `systemctl status
   launchpad-librarian@1.service` to ensure that the librarian is running.
   (If it crashes then it will restart automatically, so make sure that it's
   been running for at least a few minutes.)  You may need to ensure that
   the appropriate firewall rules exist to give it access to the Launchpad
   database, Launchpad's XML-RPC appserver, Swift, and some other details;
   for Canonical's production deployment, it should be enough to add the new
   unit to `services/lp/librarian/servers` in our firewall configuration.

1. Find a librarian URL of something at least a day old from Launchpad (the
   `.dsc` of an older source package in Ubuntu will do) and check that you
   can fetch it from any of the public download ports of the new unit.
   There is one public download port per worker, assigned sequentially
   starting from `port_download_base`.  This checks basic database and Swift
   connectivity.

1. Use `rsync` to copy the temporary spool from the old unit; on pre-Juju
   production instances this lived in
   `/srv/launchpadlibrarian.net/production/librarian/`, while on instances
   of this charm it lives in `/srv/launchpad/librarian/`.  The `rsync`
   process should run as the `launchpad` user on the new unit, and should
   _not_ use the `--delete` option; extra copies of files aren't a problem,
   and will be cleaned up by automatic garbage collection after the
   migration is complete.  Keep this running in a loop throughout the
   migration; once it has caught up it should only take a minute or so per
   iteration.

1. As `stg-launchpad@launchpad-bastion-ps5.internal`, run `lpndt
   service-stop cron-fdt` to disable all cron jobs, then (after a minute)
   `lpndt service-stop buildd-manager` to stop `buildd-manager`.

1. Comment out the `librarian-gc` and `librarian-feed-swift` cron jobs on
   the old unit (if it was deployed using this charm and is in a different
   Juju application, you can do this by setting `active=false` using Juju),
   and wait for the associated processes to stop.

1. Switch the `haproxy` frontends over to the new unit.  On production,
   you'll need to update the IP addresses of the `dl_librarian_[1-6]`,
   `ul_librarian_[1-6]`, `dl_librarian_internal_[1-6]`, and
   `ul_librarian_internal_[1-6]` servers.

1. Ensure that librarian access via the web frontend still works.

1. Set `active=true` on the new unit using Juju.

1. Check that logs from `librarian-feed-swift` (and later `librarian-gc`,
   which only runs daily) look good.

1. Stop the `rsync` loop.

1. As `stg-launchpad@launchpad-bastion-ps5.internal`, run `lpndt
   service-start buildd-manager` to start `buildd-manager, then (after a
   minute) `lpndt service-start cron-fdt` to enable all cron jobs.

## Clearing librarian storage

If you have reset the associated database, then it may be useful to clear
the librarian's storage as well, since the IDs used for stored files will no
longer exist in the database.  To do this, run:

    juju run-action --wait launchpad-librarian/leader clear-storage host=launchpadlibrarian.test

The value passed to `host=` must match the hostname part of the
`librarian_download_url` configuration option.
