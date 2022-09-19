====================
Contributing changes
====================

This guide shows you how to contribute a change to Launchpad.

Discuss the change
------------------

To begin with, it is usually helpful to discuss the change you'd like to make, in a `bug <https://bugs.launchpad.net/launchpad>`_, in the `launchpad-users <https://launchpad.net/~launchpad-users>`_ or `launchpad-dev <https://launchpad.net/~launchpad-dev>`_ mailing lists, or on IRC (``irc.libera.chat``).

Get the Launchpad source
----------------------------

Once you have decided on the change to be made, clone the repository.

.. code-block:: bash

    git clone https://git.launchpad.net/launchpad

Make your changes
-------------------

Create a branch from a reasonable point, such as ``master``.

.. code-block:: bash

    git checkout -b my-change

Make your changes on the branch. Be sure to test them locally!

Run the pre-commit hook
-----------------------

If you followed the instructions to `set up and run Launchpad <https://launchpad.readthedocs.io/en/latest/how-to/running.html#>`_, you should have ``pre-commit`` installed and have the ``pre-commit`` git hook `installed <https://launchpad.readthedocs.io/en/latest/how-to/running.html#installing-the-pre-commit-hook>`_. If not, complete these steps before proceeding.

Once you are happy with your changes, stage and commit them.

Push your changes
--------------------

Push to a personal repository

Next, you need to share your changes with the Launchpad maintainers, but you probably don't have permissions to push to the ``master`` branch of the Launchpad codebase. To share your changes with the Launchpad maintainers, you need to push your commit to a personal git repository.

Create a merge proposal
-----------------------

Once your commit has been pushed to a personal git repository, in a web browser, visit 

.. code-block:: bash

    https://code.launchpad.net/~<username>/+git

Remember to replace your username in the URL.

Navigate to the personal repository to which you pushed your changes, and then to the branch containing your commit.

Select Propose for merging, provide a reasonable commit message, and description of your changes.

What comes next?
----------------

Once you have created a merge proposal, a Launchpad maintainer will inspect your commit and either approve or reject the changes. If approved, your changes will be merged into the ``master`` branch of the Launchpad code base!