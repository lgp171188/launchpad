# This file modified from Zope3/Makefile
# Licensed under the ZPL, (c) Zope Corporation and contributors.

# Macro to lazily evaluate a shell command and cache the output.  This
# allows us to set variables to the output of shell commands without having
# to invoke those commands on every make invocation.
# Use like this: FOO = $(call lazy_eval,FOO,command and arguments)
# Borrowed from dpkg.
lazy_eval ?= $(or $(value CACHE_$(1)),$(eval CACHE_$(1) := $(shell $(2)))$(value CACHE_$(1)))

PYTHON:=python2.7

WD:=$(shell pwd)
PY=$(WD)/bin/py
PYTHONPATH:=$(WD)/lib:${PYTHONPATH}
VERBOSITY=-vv

# virtualenv and pip fail if setlocale fails, so force a valid locale.
PIP_ENV := LC_ALL=C.UTF-8
# Run with "make PIP_NO_INDEX=" if you want pip to find software
# dependencies *other* than those in our download-cache.  Once you have the
# desired software, commit it to lp:lp-source-dependencies if it is going to
# be reviewed/merged/deployed.
PIP_NO_INDEX := 1
PIP_ENV += PIP_NO_INDEX=$(PIP_NO_INDEX)
PIP_ENV += PIP_FIND_LINKS="file://$(WD)/wheels/ file://$(WD)/download-cache/dist/"

VIRTUALENV := $(PIP_ENV) virtualenv
PIP := PYTHONPATH= $(PIP_ENV) env/bin/pip --cache-dir=$(WD)/download-cache/

VENV_PYTHON := env/bin/$(PYTHON)

SITE_PACKAGES := \
	$$($(VENV_PYTHON) -c 'from distutils.sysconfig import get_python_lib; print(get_python_lib())')

TESTFLAGS=-p $(VERBOSITY)
TESTOPTS=

SHHH=utilities/shhh.py

LPCONFIG?=development

LISTEN_ADDRESS?=127.0.0.88

ICING=lib/canonical/launchpad/icing
LP_BUILT_JS_ROOT=${ICING}/build

JS_BUILD_DIR := build/js
YARN_VERSION := 1.22.4
YARN_BUILD := $(JS_BUILD_DIR)/yarn
YARN := utilities/yarn
YUI_SYMLINK := $(JS_BUILD_DIR)/yui
LP_JS_BUILD := $(JS_BUILD_DIR)/lp
NODE_ARCH = $(call lazy_eval,NODE_ARCH,nodejs -p process.arch)
NODE_ABI = $(call lazy_eval,NODE_ABI,nodejs -p process.versions.modules)
NODE_SASS_VERSION = 4.14.1
NODE_SASS_BINDING = linux-$(NODE_ARCH)-$(NODE_ABI)
NODE_SASS_BINARY = $(WD)/download-cache/yarn/node-sass-$(NODE_SASS_VERSION)-$(NODE_SASS_BINDING)_binding.node

MINS_TO_SHUTDOWN=15

CODEHOSTING_ROOT=/var/tmp/bazaar.launchpad.test

CONVOY_ROOT?=/srv/launchpad.test/convoy

VERSION_INFO = version-info.py

APIDOC_DIR = lib/canonical/launchpad/apidoc
APIDOC_TMPDIR = $(APIDOC_DIR).tmp/
API_INDEX = $(APIDOC_DIR)/index.html

# It is impossible to get pip to tell us all the files it would build, since
# each package's setup.py doesn't tell us that information.
#
# NB: It's important PIP_BIN only mentions things genuinely produced by pip.
PIP_BIN = \
    $(PY) \
    $(VENV_PYTHON) \
    bin/bingtestservice \
    bin/build-twisted-plugin-cache \
    bin/harness \
    bin/iharness \
    bin/ipy \
    bin/jsbuild \
    bin/lpjsmin \
    bin/killservice \
    bin/kill-test-services \
    bin/retest \
    bin/run \
    bin/run-testapp \
    bin/sprite-util \
    bin/start_librarian \
    bin/test \
    bin/tracereport \
    bin/twistd \
    bin/watch_jsbuild \
    bin/with-xvfb

# DO NOT ALTER : this should just build by default
default: inplace

schema: build
	$(MAKE) -C database/schema
	$(RM) -r /var/tmp/fatsam

newsampledata:
	$(MAKE) -C database/schema newsampledata

hosted_branches: $(PY)
	$(PY) ./utilities/make-dummy-hosted-branches

$(API_INDEX): $(VERSION_INFO) $(PY)
	$(RM) -r $(APIDOC_DIR) $(APIDOC_DIR).tmp
	mkdir -p $(APIDOC_DIR).tmp
	LPCONFIG=$(LPCONFIG) $(PY) ./utilities/create-lp-wadl-and-apidoc.py \
	    --force "$(APIDOC_TMPDIR)"
	mv $(APIDOC_TMPDIR) $(APIDOC_DIR)

ifdef LP_MAKE_NO_WADL
apidoc:
	@echo "Skipping WADL generation."
else
apidoc: compile $(API_INDEX)
endif

# Used to generate HTML developer documentation for Launchpad.
doc:
	$(MAKE) -C doc/ html

# Run by PQM.
check_config: build $(JS_BUILD_DIR)/.development
	bin/test -m lp.services.config.tests -vvt test_config

# Clean before running the test suite, since the build might fail depending
# what source changes happened. (e.g. apidoc depends on interfaces)
check: clean build $(JS_BUILD_DIR)/.development
	# Run all tests. test_on_merge.py takes care of setting up the
	# database.
	${PY} -t ./test_on_merge.py $(VERBOSITY) $(TESTOPTS)
	bzr status --no-pending

lint: ${PY} $(JS_BUILD_DIR)/.development
	@bash ./utilities/lint

lint-verbose: ${PY} $(JS_BUILD_DIR)/.development
	@bash ./utilities/lint -v

logs:
	mkdir logs

codehosting-dir:
	mkdir -p $(CODEHOSTING_ROOT)
	mkdir -p $(CODEHOSTING_ROOT)/mirrors
	mkdir -p $(CODEHOSTING_ROOT)/config
	mkdir -p /var/tmp/bzrsync
	touch $(CODEHOSTING_ROOT)/rewrite.log
	chmod 777 $(CODEHOSTING_ROOT)/rewrite.log
	touch $(CODEHOSTING_ROOT)/config/launchpad-lookup.txt
ifneq ($(SUDO_UID),)
	if [ "$$(id -u)" = 0 ]; then \
		chown -R $(SUDO_UID):$(SUDO_GID) $(CODEHOSTING_ROOT); \
	fi
endif

inplace: build logs clean_logs codehosting-dir
	if [ -d /srv/launchpad.test ]; then \
		ln -sfn $(WD)/build/js $(CONVOY_ROOT); \
	fi

build: compile apidoc jsbuild css_combine

# LP_SOURCEDEPS_PATH should point to the sourcecode directory, but we
# want the parent directory where the download-cache and env directories
# are. We re-use the variable that is using for the rocketfuel-get script.
download-cache:
ifdef LP_SOURCEDEPS_PATH
	utilities/link-external-sourcecode $(LP_SOURCEDEPS_PATH)/..
else
	@echo "Missing ./download-cache."
	@echo "Developers: please run utilities/link-external-sourcecode."
	@exit 1
endif

css_combine: jsbuild_widget_css
	${SHHH} bin/sprite-util create-image
	${SHHH} bin/sprite-util create-css
	ln -sfn ../../../../yarn/node_modules/yui $(ICING)/yui
	# Compile the base.css file separately for tests
	SASS_BINARY_PATH=$(NODE_SASS_BINARY) $(YARN) run node-sass --include-path $(WD)/$(ICING) --follow --output $(WD)/$(ICING)/ $(WD)/$(ICING)/css/base.scss
	# Compile the combo.css for the main site
	# XXX 2020-06-12 twom This should have `--output-style compressed`. Removed for debugging purposes
	SASS_BINARY_PATH=$(NODE_SASS_BINARY) $(YARN) run node-sass --include-path $(WD)/$(ICING) --follow --output $(WD)/$(ICING) $(WD)/$(ICING)/combo.scss

css_watch: jsbuild_widget_css
	${SHHH} bin/sprite-util create-image
	${SHHH} bin/sprite-util create-css
	ln -sfn ../../../../yarn/node_modules/yui $(ICING)/yui
	SASS_BINARY_PATH=$(NODE_SASS_BINARY) $(YARN) run node-sass --include-path $(WD)/$(ICING) --follow --output $(WD)/$(ICING) $(WD)/$(ICING)/ --watch --recursive


jsbuild_widget_css: bin/jsbuild
	${SHHH} bin/jsbuild \
	    --srcdir lib/lp/app/javascript \
	    --builddir $(LP_BUILT_JS_ROOT)

jsbuild_watch:
	$(PY) bin/watch_jsbuild

$(JS_BUILD_DIR):
	mkdir -p $@

$(YARN_BUILD): | $(JS_BUILD_DIR)
	mkdir -p $@/tmp
	tar -C $@/tmp -xf download-cache/dist/yarn-v$(YARN_VERSION).tar.gz
	mv $@/tmp/yarn-v$(YARN_VERSION)/* $@
	$(RM) -r $@/tmp

$(JS_BUILD_DIR)/.production: yarn/package.json | $(YARN_BUILD)
	SASS_BINARY_PATH=$(NODE_SASS_BINARY) $(YARN) install --offline --frozen-lockfile --production
	# We don't use YUI's Flash components and they have a bad security
	# record. Kill them.
	find yarn/node_modules/yui -name '*.swf' -delete
	touch $@

$(JS_BUILD_DIR)/.development: $(JS_BUILD_DIR)/.production
	SASS_BINARY_PATH=$(NODE_SASS_BINARY) $(YARN) install --offline --frozen-lockfile
	touch $@

$(YUI_SYMLINK): $(JS_BUILD_DIR)/.production
	ln -sfn ../../yarn/node_modules/yui $@

$(LP_JS_BUILD): | $(JS_BUILD_DIR)
	mkdir -p $@/services
	for jsdir in lib/lp/*/javascript lib/lp/services/*/javascript; do \
		app=$$(echo $$jsdir | sed -e 's,lib/lp/\(.*\)/javascript,\1,'); \
		cp -a $$jsdir $@/$$app; \
	done
	find $@ -name 'tests' -type d | xargs rm -rf
	bin/lpjsmin -p $@

jsbuild: $(LP_JS_BUILD) $(YUI_SYMLINK)
	utilities/js-deps -n LP_MODULES -s build/js/lp -x '-min.js' -o \
	build/js/lp/meta.js >/dev/null
	utilities/check-js-deps

requirements/combined.txt: \
		requirements/setup.txt \
		requirements/ztk-versions.cfg \
		requirements/launchpad.txt
	$(PYTHON) utilities/make-requirements.py \
		--exclude requirements/setup.txt \
		--buildout requirements/ztk-versions.cfg \
		--include requirements/launchpad.txt \
		>"$@"

# This target is used by LOSAs to prepare a build to be pushed out to
# destination machines.  We only want wheels: they are the expensive bits,
# and the other bits might run into problems like bug 575037.  This target
# runs pip, builds a wheelhouse with predictable paths that can be used even
# if the build is pushed to a different path on the destination machines,
# and then removes everything created except for the wheels.
#
# It doesn't seem to be straightforward to build a wheelhouse of all our
# dependencies without also building a useless wheel of Launchpad itself;
# fortunately that doesn't take too long, and we just remove it afterwards.
build_wheels: $(PIP_BIN) requirements/combined.txt
	$(RM) -r wheelhouse wheels
	$(SHHH) $(PIP) wheel \
		-c requirements/setup.txt -c requirements/combined.txt \
		-w wheels .
	$(RM) wheels/lp-[0-9]*.whl
	$(MAKE) clean_pip

# Compatibility
build_eggs: build_wheels

# setuptools won't touch files that would have the same contents, but for
# Make's sake we need them to get fresh timestamps, so we touch them after
# building.
#
# If we listed every target on the left-hand side, a parallel make would try
# multiple copies of this rule to build them all.  Instead, we nominally build
# just $(VENV_PYTHON), and everything else is implicitly updated by that.
$(VENV_PYTHON): download-cache requirements/combined.txt setup.py
	rm -rf env
	mkdir -p env
	$(VIRTUALENV) \
		--python=$(PYTHON) --never-download \
		--extra-search-dir=$(WD)/download-cache/dist/ \
		--extra-search-dir=$(WD)/wheels/ \
		env
	ln -sfn env/bin bin
	$(SHHH) $(PIP) install -r requirements/setup.txt
	$(SHHH) LPCONFIG=$(LPCONFIG) $(PIP) \
		install \
		-c requirements/setup.txt -c requirements/combined.txt -e . \
		|| { code=$$?; rm -f $@; exit $$code; }
	touch $@

$(subst $(VENV_PYTHON),,$(PIP_BIN)): $(VENV_PYTHON)

# Explicitly update version-info.py rather than declaring $(VERSION_INFO) as
# a prerequisite, to make sure it's up to date when doing deployments.
compile: $(VENV_PYTHON)
	${SHHH} utilities/relocate-virtualenv env
	$(PYTHON) utilities/link-system-packages.py \
		"$(SITE_PACKAGES)" system-packages.txt
	${SHHH} bin/build-twisted-plugin-cache
	scripts/update-version-info.sh

test_build: build
	bin/test $(TESTFLAGS) $(TESTOPTS)

test_inplace: inplace
	bin/test $(TESTFLAGS) $(TESTOPTS)

ftest_build: build
	bin/test -f $(TESTFLAGS) $(TESTOPTS)

ftest_inplace: inplace
	bin/test -f $(TESTFLAGS) $(TESTOPTS)

run: build inplace stop
	bin/run -r librarian,bing-webservice,memcached,rabbitmq \
	-i $(LPCONFIG)

run-testapp: LPCONFIG=testrunner-appserver
run-testapp: build inplace stop
	LPCONFIG=$(LPCONFIG) INTERACTIVE_TESTS=1 bin/run-testapp \
	-r memcached -i $(LPCONFIG)

run.gdb:
	echo 'run' > run.gdb

start-gdb: build inplace stop support_files run.gdb
	nohup gdb -x run.gdb --args bin/run -i $(LPCONFIG) \
		-r librarian,bing-webservice
		> ${LPCONFIG}-nohup.out 2>&1 &

run_all: build inplace stop
	bin/run \
	 -r librarian,sftp,codebrowse,bing-webservice,\
	memcached,rabbitmq -i $(LPCONFIG)

run_codebrowse: compile
	BRZ_PLUGIN_PATH=brzplugins $(PY) scripts/start-loggerhead.py

start_codebrowse: compile
	BRZ_PLUGIN_PATH=$(shell pwd)/brzplugins $(PY) scripts/start-loggerhead.py --daemon

stop_codebrowse:
	$(PY) scripts/stop-loggerhead.py

run_codehosting: build inplace stop
	bin/run -r librarian,sftp,codebrowse,rabbitmq -i $(LPCONFIG)

start_librarian: compile
	bin/start_librarian

stop_librarian:
	bin/killservice librarian

$(VERSION_INFO):
	scripts/update-version-info.sh

support_files: $(API_INDEX) $(VERSION_INFO)

# Intended for use on developer machines
start: inplace stop support_files initscript-start

# Run as a daemon - hack using nohup until we move back to using zdaemon
# properly. We also should really wait until services are running before
# exiting, as running 'make stop' too soon after running 'make start'
# will not work as expected. For use on production servers, where
# we know we don't need the extra steps in a full "make start"
# because of how the code is deployed/built.
initscript-start:
	nohup bin/run -i $(LPCONFIG) > ${LPCONFIG}-nohup.out 2>&1 &

# Intended for use on developer machines
stop: build initscript-stop

# Kill launchpad last - other services will probably shutdown with it,
# so killing them after is a race condition. For use on production
# servers, where we know we don't need the extra steps in a full
# "make stop" because of how the code is deployed/built.
initscript-stop:
	bin/killservice librarian launchpad

shutdown: scheduleoutage stop
	$(RM) +maintenancetime.txt

scheduleoutage:
	echo Scheduling outage in ${MINS_TO_SHUTDOWN} mins
	date --iso-8601=minutes -u -d +${MINS_TO_SHUTDOWN}mins > +maintenancetime.txt
	echo Sleeping ${MINS_TO_SHUTDOWN} mins
	sleep ${MINS_TO_SHUTDOWN}m

harness: bin/harness
	bin/harness

iharness: bin/iharness
	bin/iharness

rebuildfti:
	@echo Rebuilding FTI indexes on launchpad_dev database
	$(PY) database/schema/fti.py -d launchpad_dev --force

clean_js:
	$(RM) -r $(JS_BUILD_DIR)
	$(RM) -r yarn/node_modules

clean_pip:
	$(RM) -r build
	if [ -d $(CONVOY_ROOT) ]; then $(RM) -r $(CONVOY_ROOT) ; fi
	$(RM) -r bin
	$(RM) -r env
	$(RM) -r parts
	$(RM) .installed.cfg

# Compatibility.
clean_buildout: clean_pip

clean_logs:
	$(RM) logs/thread*.request

lxc-clean: clean_js clean_pip clean_logs
	# XXX: BradCrittenden 2012-05-25 bug=1004514:
	# It is important for parallel tests inside LXC that the
	# $(CODEHOSTING_ROOT) directory not be completely removed.
	# This target removes its contents but not the directory and
	# it does everything expected from a clean target.  When the
	# referenced bug is fixed, this target may be reunited with
	# the 'clean' target.
	$(RM) -r env wheelhouse wheels
	$(RM) requirements/combined.txt
	$(RM) -r $(LP_BUILT_JS_ROOT)/*
	$(RM) -r $(CODEHOSTING_ROOT)/*
	$(RM) -r $(APIDOC_DIR)
	$(RM) -r $(APIDOC_DIR).tmp
	$(RM) -r build
	$(RM) $(VERSION_INFO)
	$(RM) +config-overrides.zcml
	$(RM) -r /var/tmp/builddmaster \
			  /var/tmp/bzrsync \
			  /var/tmp/codehosting.test \
			  /var/tmp/codeimport \
			  /var/tmp/fatsam.test \
			  /var/tmp/lperr \
			  /var/tmp/lperr.test \
			  /var/tmp/ppa \
			  /var/tmp/ppa.test \
			  /var/tmp/testkeyserver
	# /var/tmp/launchpad_mailqueue is created read-only on ec2test
	# instances.
	if [ -w /var/tmp/launchpad_mailqueue ]; then \
		$(RM) -r /var/tmp/launchpad_mailqueue; \
	fi

clean: lxc-clean
	$(RM) -r $(CODEHOSTING_ROOT)

realclean: clean
	$(RM) TAGS tags

potemplates: launchpad.pot

# Generate launchpad.pot by extracting message ids from the source
# XXX cjwatson 2017-09-04: This was previously done using i18nextract from
# z3c.recipe.i18n, but has been broken for some time.  The place to start in
# putting this together again is probably zope.app.locales.
launchpad.pot:
	echo "POT generation not currently supported; help us fix this!" >&2
	exit 1

# Called by the rocketfuel-setup script. You probably don't want to run this
# on its own.
install: reload-apache

copy-certificates:
	mkdir -p /etc/apache2/ssl
	cp configs/$(LPCONFIG)/launchpad.crt /etc/apache2/ssl/
	cp configs/$(LPCONFIG)/launchpad.key /etc/apache2/ssl/

copy-apache-config: codehosting-dir
	# We insert the absolute path to the branch-rewrite script
	# into the Apache config as we copy the file into position.
	set -e; \
	apachever="$$(dpkg-query -W --showformat='$${Version}' apache2)"; \
	if dpkg --compare-versions "$$apachever" ge 2.4.1-1~; then \
		base=local-launchpad.conf; \
	else \
		base=local-launchpad; \
	fi; \
	sed -e 's,%BRANCH_REWRITE%,$(shell pwd)/scripts/branch-rewrite.py,' \
		-e 's,%WSGI_ARCHIVE_AUTH%,$(shell pwd)/scripts/wsgi-archive-auth.py,' \
		-e 's,%LISTEN_ADDRESS%,$(LISTEN_ADDRESS),' \
		configs/$(LPCONFIG)/local-launchpad-apache > \
		/etc/apache2/sites-available/$$base
	if [ ! -d /srv/launchpad.test ]; then \
		mkdir /srv/launchpad.test; \
		chown $(SUDO_UID):$(SUDO_GID) /srv/launchpad.test; \
	fi

enable-apache-launchpad: copy-apache-config copy-certificates
	[ ! -e /etc/apache2/mods-available/version.load ] || a2enmod version
	a2ensite local-launchpad

reload-apache: enable-apache-launchpad
	service apache2 restart

TAGS: compile
	# emacs tags
	ctags -R -e --languages=-JavaScript --python-kinds=-i -f $@.new \
		$(CURDIR)/lib "$(SITE_PACKAGES)"
	mv $@.new $@

tags: compile
	# vi tags
	ctags -R --languages=-JavaScript --python-kinds=-i -f $@.new \
		$(CURDIR)/lib "$(SITE_PACKAGES)"
	mv $@.new $@

PYDOCTOR = pydoctor
PYDOCTOR_OPTIONS =

pydoctor:
	$(PYDOCTOR) --make-html --html-output=apidocs --add-package=lib/lp \
		--add-package=lib/canonical --project-name=Launchpad \
		--docformat restructuredtext --verbose-about epytext-summary \
		$(PYDOCTOR_OPTIONS)

.PHONY: apidoc build_eggs build_wheels check check_config		\
	clean clean_buildout clean_js clean_logs clean_pip compile	\
	css_combine debug default doc ftest_build ftest_inplace		\
	hosted_branches jsbuild jsbuild_widget_css launchpad.pot	\
	pydoctor realclean reload-apache run run-testapp runner schema	\
	sprite_css sprite_image start stop TAGS tags test_build		\
	test_inplace $(LP_JS_BUILD)
