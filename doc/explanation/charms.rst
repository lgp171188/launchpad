=================
Charm development
=================

The direction of our official deployments is to use `Juju charms
<https://juju.is/docs/sdk>`_.  (We still have a number of manually-deployed
systems, so we aren't there yet.)

To get an overview of how this works, you'll need to look in the ``charm/``
directory of Launchpad itself, as well as `ols-layers
<https://git.launchpad.net/ols-charm-deps>`_, `launchpad-layers
<https://git.launchpad.net/launchpad-layers>`_, and `launchpad-mojo-specs
<https://git.launchpad.net/launchpad-mojo-specs>`_.  Each of the
subdirectories of ``charm/`` represents a single logical function which can
be deployed as a Juju `application <https://juju.is/docs/olm/application>`_
with one or more `units <https://juju.is/docs/olm/unit>`_.  The layers
provide common code used by multiple charms.  The specs are used with `Mojo
<https://mojo.canonical.com/>`_ to coordinate whole deployments of multiple
applications; they contain configuration of individual applications and
`integrations <https://juju.is/docs/olm/integration>`_ between applications.

Principles
==========

Wherever possible, charm code should live in the same repository as the code
it deploys (the payload).  This makes it easier to evolve both in parallel.

Launchpad is open source.  Its charms and its configuration (aside from a
small number of necessary secrets) should also be open source.  As well as
being the right thing to do, this also allows using machinery such as
Launchpad's charm recipes that upload to `Charmhub <https://charmhub.io/>`_.
When used in combination with Charmhub, Juju can easily be instructed to
upgrade charms and update configuration using a single `bundle
<https://juju.is/docs/olm/bundle>`_, allowing the top-level spec to be
relatively simple.

Each charm should correspond to a deployment of a single top-level payload.
On the other hand, it's fine for a single payload to have multiple charms
corresponding to different ways in which it can be deployed: for example,
Launchpad itself will have charms for the appservers, buildd-manager,
publishers, and so on.

If a legacy deployment bundled multiple logical functions onto a single
machine purely for economic convenience, don't be afraid to split those up
in a way that makes sense.  However, there's no need to go to extremes: if
multiple cron jobs all have broadly the same system requirements, then we're
unlikely to want each cron job to be deployed using its own Juju
application.

It will not always make sense to expose every single configuration option of
the payload directly in the charm.  Some configuration options may only
exist for internal testing purposes or for backward-compatibility, and some
may make sense for the charm to use internally but not expose in ``juju
config``.  A good rule of thumb is to consider whether a given configuration
option needs to differ between deployments; if it doesn't, there's probably
no need to expose it.

`DRY <https://en.wikipedia.org/wiki/Don%27t_repeat_yourself>`_ applies to
configuration as well as code, and can help to avoid gratuitous differences
between deployments.  `Jinja <https://jinja.palletsprojects.com/>`_
templates are widely used in both charms and Mojo specs as part of this.

Keep multi-datacentre operation in mind where possible.  We don't have
enough experience with this yet to know what we'll need to do, but it's
likely to involve deploying parts of an application in different datacentres
from other parts, so loose coupling will help: for example, it may be useful
to allow configuring connections using explicit configuration as well as or
instead of Juju integrations.

Workflow
========

You can run test deployments using `Juju <https://juju.is/docs/olm>`_ and
`LXD <https://linuxcontainers.org/lxd/introduction/>`_.  If you don't
already have a suitable testbed, then see the `Juju tutorial
<https://juju.is/docs/olm/get-started-with-juju>`_ for how to set one up;
you should use the non-Kubernetes approach here.

Each Mojo spec has a ``README.md`` file explaining how to deploy it, and
that's usually the easiest way to get started.  You should normally use the
corresponding ``devel`` stage, as that's intended for local deployments: for
example, it will normally deploy fewer units, and doesn't assume that parts
of Canonical's internal infrastructure will be available.

Once you've successfully deployed an environment, you will probably want to
iterate on it in various ways.  You can build a new charm using ``charmcraft
pack`` in the appropriate subdirectory, and then use ``juju refresh`` to
upgrade your local deployment to that.  You can change configuration items
using ``juju config``.  Alternatively, you can make a local clone of the
Mojo spec and point ``mojo run`` at that rather than at a repository on
``git.launchpad.net``, and then you can iterate by changing the spec.

Use ``juju debug-log`` and ``juju status`` liberally to observe what's
happening as you make changes.  See `How to debug a charm
<https://juju.is/docs/sdk/debug-a-charm>`_ for more specific advice on that
topic.

Secrets
=======

Cryptographic secrets should not be stored in Mojo specs, and nor should
some other pieces of information (such as configuration relevant to
preventing spam).  These are instead stored in a secrets file on the
relevant deployment host (``launchpad-bastion-ps5.internal`` or
``is-bastion-ps5.internal`` for official deployments), and are updated
manually.  The ``bundle`` command in the Mojo manifest will have a
``local=`` parameter pointing to this file, relative to
``$MOJO_ROOT/LOCAL/$MOJO_PROJECT/$MOJO_STAGE``.

Managing secrets like this is more cumbersome than updating Mojo specs, so
try to keep it to a minimum.  In some cases there may be automation
available to help, such as the `autocert charm
<https://charmhub.io/autocert>`_.

Database roles
==============

PostgreSQL considers "users" and "roles" to be very nearly synonymous.  In
this section, "user" means specifically a role that has login credentials.

Launchpad uses lots of different database roles.  We used to deal with this
by having each user on each machine that runs Launchpad code have a
``.pgpass`` file with credentials for the particular set of users that it
needs, and then it would log in as those users directly.  However, this
approach doesn't work very well with Juju: the ``postgresql`` charm allows
related charms to request access to a single user (per interface), and they
can optionally request that that user be made a member of some other roles;
SQL sessions can then use ``SET ROLE`` to switch to a different role.

In our production, staging, and qastaging environments, we use a proxy charm
to provide charms with database credentials rather than relating them to
``postgresql`` directly (partly for historical reasons, and partly to avoid
complications when the database is deployed in a different region from some
of our applications).  As a result, we need to do some manual user
management in these environments.  On staging and qastaging, developers can
do most of this themselves when adding new charms to those existing
deployment environments.

Taking the librarian as an example: ``charm/launchpad-librarian/layer.yaml``
lists the ``binaryfile-expire``, ``librarian``, ``librarianfeedswift``, and
``librariangc`` roles as being required (this corresponds to the database
users used by the services and jobs installed by that particular charm).  To
create the corresponding user, we first generate a password (e.g. using
``pwgen 30 1``), then log into the management environment (``ssh -t
launchpad-bastion-ps5.internal sudo -iu stg-launchpad``), set up environment
variables for qastaging (``. .mojorc.qastaging``), run ``juju ssh
launchpad-admin/leader``, and run ``db-admin``.  In the resulting PostgreSQL
session, replacing ``<secret>`` with the generated password:

.. code-block:: psql

    CREATE ROLE "juju_launchpad-librarian"
    	WITH LOGIN PASSWORD '<secret>'
        IN ROLE "binaryfile-expire", "librarian", "librarianfeedswift", "librariangc";

The user name here should be ``juju_`` plus the name of the charm, since
that matches what the ``postgresql`` charm would create.

Having done that, we need to install the new credentials.  On
``stg-launchpad@launchpad-bastion-ps5.internal``, find the
``db_connections`` option under the ``external-services`` application, and
add an entry to
``~/.local/share/mojo/LOCAL/mojo-lp/lp/qastaging/deploy-secrets`` that looks
like this, again replacing ``<secret>`` with the generated password:

.. code-block:: yaml

    launchpad_qastaging_librarian:
      master: "postgresql://juju_launchpad-librarian:<secret>@pamola.internal:6432/launchpad_qastaging?connect_timeout=10"
      standbys: []

In the connection string URL, the database host, port, and name (in this
case, ``pamola.internal``, ``6432``, and ``launchpad_qastaging``
respectively) should match those of other entries in ``db_connections``.

The configuration for the ``pgbouncer`` connection pooler must also be
updated to match, which currently requires help from IS.  On
``pamola.internal``, IS should take the relevant username/password pair from
the ``deploy-secrets`` file above and add it to
``/etc/pgbouncer/userlist.txt``.

Staging works similarly with the obvious substitutions of ``staging`` for
``qastaging``.  The qastaging and staging environments currently share a
``pgbouncer``; as a result, while the user still has to be created on both
database clusters, the passwords for a given user on qastaging and staging
must be identical.

Production works similarly, except that IS needs to generate the user on the
production database, add it to the production ``pgbouncer`` by editing
``userlist.txt`` in ``prod-launchpad-db@is-bastion-ps5.internal`` and
pushing it out using Mojo, and update the secrets file found in
``~/.local/share/mojo/LOCAL/mojo-lp/lp/production/deploy-secrets`` on
``prod-launchpad@is-bastion-ps5.internal``.  Developers should request this
via RT, using this document to construct instructions for IS on what to do.

Finally, the corresponding application in `launchpad-mojo-specs
<https://git.launchpad.net/launchpad-mojo-specs>`_ needs to be configured
with the appropriate database name (``launchpad_qastaging_librarian`` in the
example above).  This normally looks something like this, where
``librarian_database_name`` is an option whose value is set depending on the
stage name:

.. code-block:: yaml

  launchpad-librarian:
    ...
    options: {{ base_options() }}
      databases: |
        db:
          name: "{{ librarian_database_name }}"
