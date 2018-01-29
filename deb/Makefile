# This file is part of xcollector.
# Copyright (C) 2017  AgilX Inc.
#

ifeq ($(PACKAGE_VERSION),)
PACKAGE_VERSION := 0.1.0
endif

PACKAGE_REVISION := 1

# Various commands we need.
# In some environment this command can be called `gsha1sum' or `digest'.
PYTHON_VERSION := 2.6
PYTHON := python$(PYTHON_VERSION)

# Our "source tree" is in the parent directory, always.
VPATH := ..

git_version := \
  `git rev-list --pretty=format:%h HEAD --max-count=1 | sed 1d || echo unknown`
git_fullsha1 := \
  `git rev-list --pretty=format:%H HEAD --max-count=1 | sed 1d || echo unknown`

# What / where do we build.
DEB_TARGET := all
BASENAME := xcollector_$(PACKAGE_VERSION)-$(PACKAGE_REVISION)
DEB := $(BASENAME)_$(DEB_TARGET).deb

all: clean deb

deb:
	mkdir -p dist/
	mkdir -p build/DEBIAN/
	mkdir -p build/usr/local/xcollector/collectors/0/
	mkdir -p build/usr/local/xcollector/collectors/etc/
	mkdir -p build/usr/local/xcollector/collectors/lib/
	mkdir -p build/usr/local/xcollector/conf/
	cp -r DEBIAN/* build/DEBIAN/
	cp -r etc/ build/
	cp $(VPATH)/collectors/0/dfstat.py build/usr/local/xcollector/collectors/0/
	cp $(VPATH)/collectors/0/ifstat.py build/usr/local/xcollector/collectors/0/
	cp $(VPATH)/collectors/0/iostat.py build/usr/local/xcollector/collectors/0/
	cp $(VPATH)/collectors/0/memcache.py build/usr/local/xcollector/collectors/0/
	cp $(VPATH)/collectors/0/mysql.py build/usr/local/xcollector/collectors/0/
	cp $(VPATH)/collectors/0/netstat.py build/usr/local/xcollector/collectors/0/
	cp $(VPATH)/collectors/0/procnettcp.py build/usr/local/xcollector/collectors/0/
	cp $(VPATH)/collectors/0/procstats.py build/usr/local/xcollector/collectors/0/
	cp $(VPATH)/collectors/__init__.py build/usr/local/xcollector/collectors/
	cp $(VPATH)/collectors/etc/__init__.py build/usr/local/xcollector/collectors/etc/
	cp $(VPATH)/collectors/etc/config.py build/usr/local/xcollector/collectors/etc/
	cp $(VPATH)/collectors/etc/grok_scraper_conf.py build/usr/local/xcollector/collectors/etc/
	cp $(VPATH)/collectors/etc/metric_naming.py build/usr/local/xcollector/collectors/etc/
	cp $(VPATH)/collectors/etc/mysqlconf.py build/usr/local/xcollector/collectors/etc/
	cp $(VPATH)/collectors/etc/yaml_conf.py build/usr/local/xcollector/collectors/etc/
	cp $(VPATH)/collectors/lib/__init__.py build/usr/local/xcollector/collectors/lib/
	cp $(VPATH)/collectors/lib/utils.py build/usr/local/xcollector/collectors/lib/
	cp $(VPATH)/conf/*.yml build/usr/local/xcollector/conf/
	cp -r $(VPATH)/grok_exporter/ build/usr/local/xcollector/
	cp $(VPATH)/tcollector.py build/usr/local/xcollector/xcollector.py
	cp $(VPATH)/grok_scraper.py build/usr/local/xcollector/grok_scraper.py
	set -e; { \
	  sed \
            -e 's/@PACKAGE_VERSION@/$(PACKAGE_VERSION)/' \
            -e 's/@DEB_TARGET@/$(DEB_TARGET)/' \
            -e 's/@PYTHON_VERSION@/$(PYTHON_VERSION)/' \
            -e "s/@GIT_SHORTSHA1@/$(git_version)/" \
            -e "s/@GIT_FULLSHA1@/$(git_fullsha1)/" \
            -e 's/@PACKAGE_REVISION@/$(PACKAGE_REVISION)/' \
	    DEBIAN/control; \
        } >build/DEBIAN/control
	cd build; find . -type f ! -regex '.*?DEBIAN.*' -printf '%P ' | xargs md5sum > DEBIAN/md5sums
	dpkg-deb -b build dist/$(DEB)

clean:
	rm -rf build dist

.PHONY: all deb clean
.SUFFIXES: .deb
