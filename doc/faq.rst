==========================
Frequently Asked Questions
==========================

Are there Launchpad packages available?
=======================================

No, Launchpad is not packaged and there are no plans to do so.  Launchpad
deployment is done straight from Git branches and is quite complex.

Why PostgreSQL?
===============

PostgreSQL was chosen in 2004 because it supported most of the features we
thought we would need; MySQL did not.  The other contender was Oracle, and
for a while we made sure we would be able to switch to Oracle if necessary
but PostgreSQL has worked great.

How integrated is the database in the code?
===========================================

Highly. We make use of PostgreSQL specific features, such as:

* SQL language extensions
* PL/pgSQL and Python stored procedures
* Triggers
* Functional indexes
* Automatic load balancing over the replicas with Slony-I
* Transactional DDL
* tsearch2 full text search
* Database permissions

What version of Python is required?
===================================

Currently, Python 3.5.

Can I look at the code without downloading it all?
==================================================

Yes, you can browse the `source code
<https://git.launchpad.net/launchpad/tree>`_ on Launchpad.  You can also use
``git clone https://git.launchpad.net/launchpad`` to download the code
without setting up a development environment.

I have Launchpad running but mails are not sent...
==================================================

Development Launchpads don't send email to the outside world, for obvious
reasons.  They connect to the local SMTP server and send to root.  To create
new users, create a new account and check the local mailbox, or check
:ref:`this FAQ <create-additional-user-accounts-dev-env>`.

.. _create-additional-user-accounts-dev-env:

How do I create additional user accounts in the dev environment?
================================================================
You can create a new account using the ``utilities/make-lp-user`` script and log
in to that account at ``https://launchpad.test``.

My database permissions keep getting deleted!
=============================================

If your local account is called "launchpad" it conflicts with a role called
"launchpad" which is defined in ``database/schema/security.cfg``.  You need
to rename your local account and re-assign it superuser permissions as the
``utilities/launchpad-database-setup`` script does.
