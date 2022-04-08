Landing updates for Loggerhead
==============================

`Loggerhead <https://launchpad.net/loggerhead/>`_ is a web-based
`Bazaar <https://bazaar.canonical.com/>`_ code browser.

Landing changes for Loggerhead itself
-------------------------------------

- create a merge proposal for https://launchpad.net/loggerhead
- get approval
- mark merge proposal as **Approved**

Landing changes in Launchpad itself
-----------------------------------

- update the revision number in ``utilities/sourcedeps.conf``
- run ``utilities/update-sourcecode``
- make sure ``utilities/sourcedeps.cache`` was updated
- propose changes as merge proposal
- mark merge proposal as **Approved**

Performing QA
-------------

After the changes have landed and passed through buildbot,
they will be available at https://bazaar.staging.launchpad.net.

Please note that only a few Bazaar branches are synced from production to
staging.

You should create a repository and push some changes to perform QA:

.. code-block:: bash

    bzr push lp://staging/~you/+junk/foo

Deployment
----------

To get the changes into production, you need to perform a regular Launchpad
deployment.