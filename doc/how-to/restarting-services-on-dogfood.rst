==============================
Restarting services on Dogfood
==============================

When applying manual changes, it may be necessary to restart services.

Instead of :doc:`restarting all services <resurrect-dogfood>`, it is much
faster to restart individual services.

Restarting launchpad-buildd
===========================

.. code-block:: bash

    launchpad@labbu:~$ /srv/launchpad.net/buildd-manager restart
