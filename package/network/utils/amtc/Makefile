include $(TOPDIR)/rules.mk

PKG_NAME:=amtc
PKG_VERSION:=0.8.5
PKG_RELEASE:=1

PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/schnoddelbotz/amtc.git
PKG_SOURCE_VERSION:=master
PKG_SOURCE_SUBDIR:=$(PKG_NAME)-$(PKG_VERSION)
PKG_SOURCE:=$(PKG_NAME)-$(PKG_VERSION).tar.gz
PKG_MIRROR_HASH:=skip

PKG_MAINTAINER:=you@example.com
PKG_LICENSE:=GPL-2.0

PKG_BUILD_PARALLEL:=1

include $(INCLUDE_DIR)/package.mk

define Package/amtc
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Intel AMT/vPro mass remote power management tool
  DEPENDS:=+libcurl +libgnutls +libpthread
endef

define Package/amtc/description
  Lightweight CLI tool for Intel AMT/vPro out-of-band power management.
endef

AMTC_HEADERS:=amtc_usage cmd_powerdown cmd_powerup cmd_info cmd_powerreset \
	cmd_powercycle wsman_info wsman_info_step2 wsman_up wsman_down \
	wsman_reset wsman_xenum wsman_xenum_step2 wsman_pxeboot wsman_hddboot wsman_bootconfig \
	wsman_solredir_enable wsman_solredir_disable \
	wsman_webui_enable wsman_webui_disable \
	wsman_ping_enable wsman_ping_disable \
	wsman_shutdown_graceful wsman_reset_graceful

# 不再依赖上游 src/Makefile 的隐式规则链(该链条在 OpenWrt 构建沙箱里
# 存在环境差异导致 amt.h 生成失败,已在 SSH 现场验证手动执行完全没问题)。
# 直接把验证成功的步骤原样搬到这里,全程自己掌控环境。
define Build/Compile
	export PATH="$$$$PATH:/usr/bin:/bin"; \
	cd $(PKG_BUILD_DIR)/src; \
	rm -rf amtterm; \
	git clone --depth 1 https://github.com/kraxel/amtterm.git amtterm; \
	sed -e '1,/\* ----/d' -e '/static void usage/,1000d' amtterm/amtterm.c > amtc-amtterm.c; \
	AMTCV=`cat ../version`; \
	cp amtc_usage amtc_usage.bak; \
	perl -pi -e "s/#AMTCV#/$$$$AMTCV/" amtc_usage; \
	for H in $(AMTC_HEADERS); do \
		xxd -i "$$$$H" "$$$$H.h"; \
	done; \
	mv amtc_usage.bak amtc_usage; \
	cat amtc_usage.h cmd_*.h wsman_*.h wsman.h > amt.h; \
	perl -pi -e 's/(0x\S\S)$$$$/$$$$1, 0x00/' amt.h; \
	perl -pi -e 's/(\d+);$$$$/$$$$1 + 1 .";"/e' amt.h; \
	$(TARGET_CC) $(TARGET_CFLAGS) -I. -I$(STAGING_DIR)/usr/include \
		-DWITH_GPL_AMTTERM \
		amtterm/tcp.c amtterm/redir.c amtc-amtterm.c amtc.c \
		$(TARGET_LDFLAGS) -L$(STAGING_DIR)/usr/lib -lcurl -lpthread \
		-o amtc
endef

define Package/amtc/install
	$(INSTALL_DIR) $(1)/usr/sbin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/src/amtc $(1)/usr/sbin/amtc
endef

$(eval $(call BuildPackage,amtc))