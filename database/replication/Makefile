# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
#
# This makefile is used to build and replicate the staging database.
# To build a replicated development environent, replicate your 10 main
# cluster with standard PG 10 streaming replication per the PG docs.
#
# To test the staging rebuild script:
#
#  $ mkdir -p /srv/staging.launchpad.net/staging-logs
#  $ cd database/replication
#  $ pg_dump --format=c launchpad_dev > launchpad.dump
#  $ make stagingsetup \
#        STAGING_CONFIG=dev-staging STAGING_DUMP=launchpad.dump
#  $ make stagingswitch STAGING_CONFIG=dev-staging
#
# To restore a dogfood database:
#
#  $ cd database/replication
#  $ make dogfood DOGFOOD_DBNAME=launchpad_dogfood DOGFOOD_DUMP=launchpad.dump
#

# For real restores, this is being run on an 8 core system. Let pg_restore
# run multiprocess.
## No multiprocess for now - don't want to overflow replication
## MULTIPROC=-j 4
MULTIPROC=

STAGING_CONFIG=staging-db # For swapping fresh db into place.
STAGING_DUMP=launchpad.dump # Dumpfile to build new staging from.
STAGING_TABLESPACE=pg_default # 'pg_default' for default
STAGING_LOGDIR=/srv/launchpad/logs
STAGING_POSTGRESQL_VERSION=10
DOGFOOD_DUMP=launchpad.dump

# Database options to pass to PostgreSQL tools.
STAGING_DBOPTS:=$(shell LPCONFIG=${STAGING_CONFIG} ../../utilities/pgoptions.py)

# If we're restoring locally, then block the restore process while there are
# too many unshipped WAL files.  If we're restoring remotely, we can't
# easily do this, so we have to just hope that the remote systems can keep
# up.
ifeq (,${STAGING_DBOPTS})
STAGING_WALBLOCK=./walblock.py -n 5000 -d /var/lib/postgresql/${STAGING_POSTGRESQL_VERSION}/staging/pg_wal
else
STAGING_WALBLOCK=cat
endif

# Names of underlying PostgreSQL databases.
STAGING_DBNAME_MAIN=lpmain_staging
STAGING_DBNAME_SESSION=session_staging
DOGFOOD_DBNAME=launchpad_dogfood

# Names in pgbouncer.ini's `[databases]` section.
STAGING_PGBOUNCER_MAIN=launchpad_staging launchpad_staging_standby1
STAGING_PGBOUNCER_SESSION=session_staging

STAGING_PGBOUNCER=psql -p 6432 -U pgbouncer -d pgbouncer

PGMASSACRE=../../utilities/pgmassacre.py

CREATEDB=createdb --encoding=UTF8 --locale=C --template=template0

# Turn off output silencing so we can see details of staging deployments.
# Without the timestamps, we are unable to estimate production deployment
# times.
#SHHH=../../utilities/shhh.py
SHHH=

default:
	echo Need a target

# Build _new staging databases from a production dump.
stagingsetup: DUMPLIST:=$(shell tempfile --suffix=.lst --prefix=lpstag)
stagingsetup:
	# List the dump first to make sure it is usable.
	pg_restore --list ${STAGING_DUMP} | \
	    grep -v -E 'TRIGGER public [^ ]+ _sl_' > ${DUMPLIST}

	# Kill the existing temporary staging database if it exists from an
	# aborted run.
	-LPCONFIG=${STAGING_CONFIG} LP_DESTROY_REMOTE_DATABASE=yes \
		${PGMASSACRE} ${STAGING_DBNAME_MAIN}_new

	# Quickly clear out the session DB. No need to DISABLE here, as
	# we bring the DB back quickly.
	${STAGING_PGBOUNCER} -c 'KILL ${STAGING_PGBOUNCER_SESSION}'
	psql ${STAGING_DBOPTS} -d ${STAGING_DBNAME_SESSION} -c 'TRUNCATE sessiondata CASCADE;'
	${STAGING_PGBOUNCER} -c 'RESUME ${STAGING_PGBOUNCER_SESSION}'

	# Create the DB with the desired default tablespace.
	${CREATEDB} ${STAGING_DBOPTS} --tablespace ${STAGING_TABLESPACE} \
		${STAGING_DBNAME_MAIN}_new
	# Restore the database. We need to restore permissions, despite
	# later running security.py, to pull in permissions granted on
	# production to users not maintained by security.py.
	< ${STAGING_DUMP} ${STAGING_WALBLOCK} \
	    | pg_restore ${STAGING_DBOPTS} --dbname=${STAGING_DBNAME_MAIN}_new \
		--no-owner ${EXIT_ON_ERROR} \
		--use-list=${DUMPLIST} -v
	rm ${DUMPLIST}
	# Apply database patches.
	@echo Running upgrade.py `date`.
	LPCONFIG=${STAGING_CONFIG} ${SHHH} ../schema/upgrade.py \
		--dbname=${STAGING_DBNAME_MAIN}_new \
		--log-file=INFO:${STAGING_LOGDIR}/dbupgrade.log
	@echo Running security.py `date`
	LPCONFIG=${STAGING_CONFIG} ${SHHH} ../schema/security.py \
		--dbname=${STAGING_DBNAME_MAIN}_new \
		--log-file=INFO:${STAGING_LOGDIR}/dbupgrade.log
	@echo Setting feature flags
	psql ${STAGING_DBOPTS} -d ${STAGING_DBNAME_MAIN}_new -c "INSERT INTO featureflag (flag, scope, priority, value) VALUES ('profiling.enabled', 'team:launchpad', 0, 'on') ON CONFLICT DO NOTHING"
	psql ${STAGING_DBOPTS} -d ${STAGING_DBNAME_MAIN}_new -c "INSERT INTO featureflag (flag, scope, priority, value) VALUES ('librarian.swift.enabled', 'default', 0, 'on') ON CONFLICT DO NOTHING"

stagingswitch:
	set -e; for verb in DISABLE KILL RESUME; do \
		for db in ${STAGING_PGBOUNCER_MAIN}; do \
			${STAGING_PGBOUNCER} -c "$$verb $$db"; \
		done; \
	done
	# Kill the existing staging database if it exists.
	-LPCONFIG=${STAGING_CONFIG} LP_DESTROY_REMOTE_DATABASE=yes \
		${PGMASSACRE} ${STAGING_DBNAME_MAIN}
	# Rename the newly-built staging databases.
	psql ${STAGING_DBOPTS} -d template1 -c \
	    "ALTER DATABASE ${STAGING_DBNAME_MAIN}_new RENAME TO ${STAGING_DBNAME_MAIN};"
	set -e; for db in ${STAGING_PGBOUNCER_MAIN}; do \
		${STAGING_PGBOUNCER} -c "ENABLE $$db"; \
	done

dogfood: DUMPLIST:=$(shell tempfile --suffix=.lst --prefix=lpdogf)
dogfood:
	${CREATEDB} ${DOGFOOD_DBNAME}
	pg_restore --list ${DOGFOOD_DUMP} | \
	    grep -v -E 'TRIGGER public [^ ]+ _sl_' > ${DUMPLIST}
	pg_restore --dbname=${DOGFOOD_DBNAME} --no-acl --no-owner \
	    --use-list=${DUMPLIST} ${EXIT_ON_ERROR} ${MULTIPROC} ${DOGFOOD_DUMP}
	rm ${DUMPLIST}
	../schema/upgrade.py -d ${DOGFOOD_DBNAME}
	../schema/security.py -d ${DOGFOOD_DBNAME}
