"""Phase 4: add the DSP coprocessor's device-tree node.

Register base 0x10203000 and IRQ confirmed against 3dbrew's ARM11
interrupt table (DSP General Interrupt = raw ID 0x4A). This DTS's
GIC_SPI numbering is raw-ID minus 0x20 -- cross-checked against two
already-working nodes in this same file: nwm (WiFi SDIO) is raw ID
0x40/0x41 in 3dbrew's table and GIC_SPI 0x20/0x21 here; i2c1 is raw ID
0x54 in 3dbrew's table and GIC_SPI 0x34 here. Both match the -0x20
formula exactly, so DSP's GIC_SPI is 0x4A - 0x20 = 0x2A. Verified 0x2A
isn't already claimed by any other node in this file.
"""
from a3ds_paths import A3DS_ROOT

DTSI = f"{A3DS_ROOT}/third_party/linux/arch/arm/boot/dts/nintendo3ds.dtsi"

with open(DTSI) as f:
    c = f.read()

anchor = """		pxi: virtio-bridge@10163000 {
			compatible = "nintendo,3ds-pxi";
			reg = <0x10163000 0x10>;

			interrupts =
				<GIC_SPI 0x30 IRQ_TYPE_EDGE_RISING>,
				<GIC_SPI 0x32 IRQ_TYPE_EDGE_RISING>,
				<GIC_SPI 0x33 IRQ_TYPE_EDGE_RISING>;
		};
"""
assert c.count(anchor) == 1, "pxi node not found verbatim"

dsp_node = """
		dsp: dsp@10203000 {
			compatible = "nintendo,3ds-dsp";
			reg = <0x10203000 0x1000>;

			/* DSP General Interrupt (semaphore + cmd/reply
			 * register status change) -- see 3dbrew ARM11
			 * Interrupts, raw ID 0x4A. */
			interrupts = <GIC_SPI 0x2A IRQ_TYPE_EDGE_RISING>;
		};
"""

c = c.replace(anchor, anchor + dsp_node)
with open(DTSI, "w") as f:
    f.write(c)

print("OK")
