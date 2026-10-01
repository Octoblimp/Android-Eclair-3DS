from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/arch/arm/configs/nintendo3ds_defconfig"
with open(path) as f:
    content = f.read()

old = """# Phase 2: WiFi bring-up (ath6kl over the nwm SDIO controller)
CONFIG_CFG80211=y
CONFIG_ATH6KL=y
CONFIG_ATH6KL_SDIO=y
CONFIG_ATH6KL_DEBUG=y

# Phase 2: WiFi bring-up (ath6kl over the nwm SDIO controller)
# CONFIG_NET itself was off in this defconfig -- the entire networking
# subsystem, not just wireless -- so it has to be enabled first or every
# symbol below it (WIRELESS, CFG80211, ATH6KL, ...) stays unreachable
# and any explicit =y for them here gets silently dropped by olddefconfig.
CONFIG_NET=y
CONFIG_PACKET=y
CONFIG_UNIX=y
CONFIG_INET=y
CONFIG_NETDEVICES=y
CONFIG_WLAN=y
CONFIG_WIRELESS=y
CONFIG_CFG80211=y
CONFIG_ATH6KL=y
CONFIG_ATH6KL_SDIO=y
CONFIG_ATH6KL_DEBUG=y"""

new = """# Phase 2: WiFi bring-up.
# CONFIG_NET itself was off in this defconfig -- the entire networking
# subsystem, not just wireless -- so it has to be enabled first or every
# symbol below it (WIRELESS, CFG80211, ATH6K_LEGACY, ...) stays unreachable
# and any explicit =y for them here gets silently dropped by olddefconfig.
CONFIG_NET=y
CONFIG_PACKET=y
CONFIG_UNIX=y
CONFIG_INET=y
CONFIG_NETDEVICES=y
CONFIG_WLAN=y
CONFIG_WIRELESS=y
CONFIG_CFG80211=y

# The 3DS's WiFi chip reports SDIO ID 0271:0201 -- confirmed AR6002
# generation hardware (see include/common/AR6002/hw4.0 in the legacy
# driver source). The modern in-tree ath6kl/ath6kl_sdio driver explicitly
# dropped AR6002/AR6001 support; only the old pre-mainline ATH6K_LEGACY
# staging driver (deleted from the kernel tree around 3.2, resurrected
# here from an archived kernel fork under drivers/staging/ath6k_legacy)
# actually speaks this chip's protocol. Board data doesn't match any of
# the stock reference-design choices (Nintendo's is a custom design), so
# AR600x_CUSTOM_XXX is the closest honest option -- still needs a real
# bdata.CUSTOM.bin sourced from somewhere to actually associate.
CONFIG_ATH6K_LEGACY=y
CONFIG_AR600x_CUSTOM_XXX=y
CONFIG_ATH6KL_DEBUG=y
CONFIG_ATH6KL_ENABLE_HOST_DEBUG=y"""

count = content.count(old)
assert count == 1, f"expected exactly 1 match, found {count}"
content = content.replace(old, new)

with open(path, 'w') as f:
    f.write(content)
print("OK")
