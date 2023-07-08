# The charmcraft tool is shipped as a snap, so make sure it's on $PATH.
export PATH := $(PATH):/snap/bin

APP_NAME := launchpad

BUILDDIR := $(CURDIR)/dist

CHARM_SERIES ?= 20.04
ARCH := $(shell dpkg --print-architecture)
charm_file = $(1)_ubuntu-$(CHARM_SERIES)-$(ARCH).charm

BUILD_LABEL = $(shell git rev-parse HEAD)
TARBALL = $(APP_NAME).tar.gz
ASSET = ../build/$(BUILD_LABEL)/$(TARBALL)

CHARMS := \
	launchpad-admin \
	launchpad-appserver \
	launchpad-assets \
	launchpad-buildd-manager \
	launchpad-debian-importer \
	launchpad-librarian

all: ## alias to build
all: build

help: ## display this help message
	@echo "Please use \`make <target>' where <target> is one of"
	@grep '^[a-zA-Z]' $(MAKEFILE_LIST) | sort | awk -F ':.*?## ' 'NF==2 {printf "\033[36m  %-25s\033[0m %s\n", $$1, $$2}'

$(BUILDDIR):
	@mkdir -p $@

build: ## build all the charms
build: $(foreach charm,$(CHARMS),build-$(charm))

build-launchpad-admin: ## build the launchpad-admin charm
build-launchpad-admin: dist/$(call charm_file,launchpad-admin)

build-launchpad-appserver: ## build the launchpad-appserver charm
build-launchpad-appserver: dist/$(call charm_file,launchpad-appserver)

dist/%_ubuntu-$(CHARM_SERIES)-$(ARCH).charm: $(BUILDDIR)
	echo "Building $*..."
	cd $* && charmcraft pack
	cp -a $*/$(call charm_file,$*) dist/

clean: ## clean the build environment
clean: $(foreach charm,$(CHARMS),clean-$(charm))
	@find . -name \*.pyc -delete
	@find . -depth -name '__pycache__' -exec rm -rf '{}' \;
	@rm -f bundle.yaml
	@rm -rf $(BUILDDIR)

clean-%:
	@echo "Cleaning $*..."
	@cd $* && charmcraft clean
	@rm -f dist/$(call charm_file,$*)

bundle.yaml: ## create the bundle.yaml file from the bundle.yaml.in template
bundle.yaml: bundle.yaml.in
	sed \
	    -e 's/%BUILD_LABEL%/$(BUILD_LABEL)/g' \
	    bundle.yaml.in >bundle.yaml

deploy: ## deploy the built charm
deploy: build bundle.yaml
	@echo "Deploying $(APP_NAME)..."
	@juju deploy ./bundle.yaml

payload: ## build a launchpad tarball
payload: $(ASSET)
$(ASSET):
	@echo "Building asset for $(BUILD_LABEL)..."
	@$(MAKE) -C .. build-tarball


setup-jenkaas: ## prepare a Jenkins-as-a-service container for charm building
setup-jenkaas:
	sudo systemctl stop snapd.socket
	sudo systemctl stop snapd
	echo SNAPPY_STORE_NO_CDN=1 | sudo tee -a /etc/environment >/dev/null
	echo SNAPPY_TESTING=1 | sudo tee -a /etc/environment >/dev/null
	sudo systemctl start snapd.socket
	sudo snap install --classic charm

.PHONY: $(foreach charm,$(CHARMS),build-$(charm))
.PHONY: all build clean deploy payload setup-jenkaas
