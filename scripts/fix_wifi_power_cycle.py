"""Phase 2 / AR6002: actually power-cycle the WiFi chip, don't just enable it.

Evidence that the chip carries state across the Luma -> firm_linux_loader ->
Linux handoff:

  - Target RAM at 0x5203A8..0x5203C0 and 0x520580..0x52058C contains words like
    0x008E35D8 / 0x008EC97C -- Horizon-side ARM11 heap pointers. Linux never
    writes values in that range. Nintendo's NWM drove this chip and left its
    working state behind.
  - firm_linux_loader touches nothing WiFi-related (only a REG_RESET_SDIO
    define for its own FAT driver), so nothing in our boot chain resets it.
  - The ath6k driver's only ar6000_reset_device() call is on instance destroy,
    and passes coldReset=false for AR6002.

The ARM11 gets replaced at the FIRM handoff, but the AR6002 is a separate
device on the SDIO bus with its own power domain and its own RAM. A soft
reboot from Horizon into Linux leaves it powered and initialised.

This driver already located the power-enable line (3dbrew: GPIO3_DATA2 bit 0
at 0x10147028) but requested it GPIOD_OUT_HIGH -- enabling the chip without
ever taking it down first, so a chip that was already on stays on, state
intact. Request it LOW, hold it there long enough for the rail to drain, then
raise it, giving a genuine cold boot into the target's BMI loop.
"""
from a3ds_paths import A3DS_ROOT

path = f"{A3DS_ROOT}/third_party/linux/drivers/platform/nintendo3ds/ctr_sdhc.c"

with open(path) as f:
    c = f.read()

old = """	{
		struct gpio_desc *wifi_en = devm_gpiod_get_optional(dev, "wifi-enable", GPIOD_OUT_HIGH);
		if (IS_ERR(wifi_en))
			return PTR_ERR(wifi_en);
		if (wifi_en) {
			/* give the chip time to power up before any SDIO command */
			msleep(20);
		}
	}"""

new = """	{
		/* Request the line LOW rather than HIGH: the chip may already be
		 * powered and running Nintendo's firmware, carried over from
		 * Horizon across the Luma -> firm_linux_loader -> Linux handoff
		 * (the ARM11's software is replaced, but this is a separate
		 * device on the SDIO bus with its own power domain and RAM).
		 * Horizon leftovers were observed in its RAM as ARM11 heap
		 * pointers, and nothing else in the boot chain resets it. Only a
		 * real power cycle guarantees the target comes up cold in its
		 * boot ROM's BMI loop with a clean host-interest area. */
		struct gpio_desc *wifi_en = devm_gpiod_get_optional(dev, "wifi-enable", GPIOD_OUT_LOW);
		if (IS_ERR(wifi_en))
			return PTR_ERR(wifi_en);
		if (wifi_en) {
			/* hold it down long enough for the rail to actually drain */
			msleep(100);
			gpiod_set_value_cansleep(wifi_en, 1);
			/* give the chip time to power up before any SDIO command */
			msleep(50);
			dev_info(dev, "ctr_sdhc: WiFi chip power cycled\\n");
		}
	}"""

n = c.count(old)
assert n == 1, f"expected exactly 1 match, found {n}"
c = c.replace(old, new)

with open(path, "w") as f:
    f.write(c)
print("OK")
