#
# OpenWrt / ImmortalWrt package for amtc
#   https://github.com/schnoddelbotz/amtc
#
# Intel AMT / vPro mass management CLI (one thread per host), including
# serial-over-LAN via the bundled GPL'ed amtterm code.
#
# Verified with the ImmortalWrt 25.12.2 (apk) SDK and gcc 14 / musl.
#
# Directory of this package (has to be evaluated before anything else is
# included, $(MAKEFILE_LIST) is clobbered by the build system's includes).
AMTC_PKGDIR:=$(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

include $(TOPDIR)/rules.mk

PKG_NAME:=amtc
PKG_VERSION:=0.8.5
PKG_RELEASE:=1

PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/schnoddelbotz/amtc.git
PKG_SOURCE_VERSION:=4c2a69adea0a61534fd34aa691ffbc3dfa37bdbd
PKG_MIRROR_HASH:=skip

# The repo has a .gitmodules pointing at git://git.kraxel.org/amtterm, which
# does not resolve any more. OpenWrt would try to "git submodule update" and
# die, so tell it to skip submodules - we fetch amtterm ourselves below.
PKG_SOURCE_SUBMODULES:=skip

# amtc itself is MIT licensed, but its serial-over-LAN support statically
# links amtterm (GPL-2.0-only), so the resulting binary is GPL-2.0-only.
PKG_LICENSE:=MIT GPL-2.0-only
PKG_LICENSE_FILES:=LICENSE.txt
PKG_MAINTAINER:=

# We link against libcurl, so curl has to be built (and installed into
# staging_dir) before us. A plain DEPENDS:=+libcurl only adds a *runtime*
# dependency - "make package/amtc/compile" would happily try to compile
# amtc.c without curl/curl.h being present. "curl" here is the source package
# name (it builds libcurl4, which provides the virtual name "libcurl").
PKG_BUILD_DEPENDS:=curl

# amtterm, the submodule amtc expects, taken from the upstream GitHub mirror.
# The commit below is exactly the one recorded in amtc's git tree (v1.4).
# Do NOT bump this to amtterm 1.8: redir.h there includes <stdbool.h>, which
# collides with amtc's own "typedef enum { false, true } bool;".
AMTTERM_URL:=https://github.com/kraxel/amtterm.git
AMTTERM_COMMIT:=a75e48e010e92dc5540e2142efc445ccb0ab1a42

include $(INCLUDE_DIR)/package.mk

# Host helper dir (contains the "xxd" shim), put in front of the build PATH.
TARGET_PATH_PKG:=$(AMTC_PKGDIR)/host-tools:$(TARGET_PATH_PKG)

define Package/amtc
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Threaded Intel AMT/vPro mass management tool
  URL:=https://github.com/schnoddelbotz/amtc
  DEPENDS:=+libcurl +libpthread
endef

define Package/amtc/description
 amtc is a threaded Intel AMT (vPro) mass management command line tool.
 It powers machines on/off/reset/cycle, queries hardware info, sets the
 next boot device (PXE/HDD), toggles AMT features (redirection, web UI,
 ping replies, graceful shutdown) and opens a serial-over-LAN console -
 for a single host or for a whole list of hosts in parallel.
endef

define Build/Prepare
	$(call Build/Prepare/Default)
	# src/Makefile expects src/amtterm to be a checked out submodule and
	# stops with "git submodule update" if src/amtterm/.git is missing.
	rm -rf $(PKG_BUILD_DIR)/src/amtterm
	git clone --quiet $(AMTTERM_URL) $(PKG_BUILD_DIR)/src/amtterm
	cd $(PKG_BUILD_DIR)/src/amtterm && git checkout --quiet $(AMTTERM_COMMIT)
endef

# Upstream has neither configure nor CMake, so drive src/Makefile directly with
# the OpenWrt toolchain.
#
#  * TARGET_PATH_PKG is prefixed with host-tools/: the "xxd" that OpenWrt
#    ships in staging_dir/host/bin is scripts/xxdi.pl, which does not support
#    xxd's output-file argument, so a small perl shim is put in front of it.
#  * -Wno-implicit-function-declaration: gcc >= 14 turns implicit function
#    declarations into a hard error; amtc.c calls amtterm_session() before it
#    is defined (the prototype only comes in later via amtc-amtterm.c).
define Build/Compile
	$(MAKE) -C $(PKG_BUILD_DIR)/src \
		CC="$(TARGET_CC)" \
		CFLAGS="$(TARGET_CPPFLAGS) $(TARGET_CFLAGS) -Wno-implicit-function-declaration" \
		LDLIBS="$(TARGET_LDFLAGS) -lcurl -lpthread" \
		amtc
endef

define Package/amtc/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/src/amtc $(1)/usr/bin/amtc
	$(INSTALL_DIR) $(1)/usr/share/man/man1
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/src/man/man1/amtc.1 \
		$(1)/usr/share/man/man1/amtc.1
endef

$(eval $(call BuildPackage,amtc))
