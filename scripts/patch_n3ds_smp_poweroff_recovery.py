#!/usr/bin/env python3
"""Recover dropped ARM11 IPIs and make the START deadline cut MCU power directly."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(A3DS_ROOT)
SMP = ROOT / "third_party/linux/kernel/smp.c"
ARM_SMP = ROOT / "third_party/linux/arch/arm/kernel/smp.c"
PANIC = ROOT / "third_party/linux/kernel/panic.c"
GIC = ROOT / "third_party/linux/drivers/irqchip/irq-gic.c"
I2C = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_i2c.c"
PWRKEY = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_pwrkey.c"
MCU_POWER = ROOT / "third_party/linux/drivers/platform/nintendo3ds/mcu/poweroff.c"
MCU_HEADER = ROOT / "third_party/linux/drivers/platform/nintendo3ds/mcu/poweroff.h"
I2C_HEADER = ROOT / "third_party/linux/include/linux/platform_data/ctr_i2c.h"
KCONFIG = ROOT / "third_party/linux/drivers/platform/nintendo3ds/Kconfig"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


smp = SMP.read_text()
if "N3DS_CSD_IPI_PROGRESS_RECOVERY" not in smp:
    start = smp.index("static noinline void csd_lock_wait_cpu_slow(")
    end = smp.index("\nstatic __always_inline void csd_lock_wait_cpu(", start)
    smp = smp[:start] + r'''/* N3DS_CSD_IPI_PROGRESS_RECOVERY: the integrated ARM11 MPCore GIC has
 * now produced a hardware trace in which a synchronous TLB callback stays
 * queued while another CPU waits forever in smp_call_function_many().
 *
 * A duplicate call-function SGI is harmless: the per-CPU llist owns the work
 * and an extra handler simply finds it empty. Re-kick the named target after
 * 1 ms, broadcast every 16 retries to survive a bad logical GIC target map,
 * and drain this CPU's own queue to break reciprocal cross-call waits. */
#define CSD_IPI_RETRY_NS	(1ULL * NSEC_PER_MSEC)
#define CSD_IPI_BROADCAST_RETRIES	16

static noinline void csd_lock_wait_cpu_slow(call_single_data_t *csd, int cpu)
{
	u64 ts0 = sched_clock();
	u64 next = ts0 + CSD_STUCK_FIRST_NS;
	u64 next_retry = ts0 + CSD_IPI_RETRY_NS;
	unsigned int retries = 0;
	unsigned int spins = 0;
	bool reported = false;
	u64 now;

	while (READ_ONCE(csd->node.u_flags) & CSD_FLAG_LOCK) {
		/* If two CPUs are synchronously waiting on one another, neither
		 * should depend on a second interrupt edge to run already-queued
		 * local work. Match the IPI handler's IRQ-disabled contract. */
		if (unlikely(!llist_empty(this_cpu_ptr(&call_single_queue)))) {
			unsigned long flags;

			local_irq_save(flags);
			flush_smp_call_function_queue(false);
			local_irq_restore(flags);
			if (!(READ_ONCE(csd->node.u_flags) & CSD_FLAG_LOCK))
				break;
		}

		cpu_relax();

		/* sched_clock() is far too heavy for every iteration of a
		 * spin that normally completes in microseconds. */
		if (++spins & 0xff)
			continue;

		now = sched_clock();
		if (now >= next_retry) {
			arch_send_call_function_single_ipi(cpu);
			retries++;
			if (!(retries % CSD_IPI_BROADCAST_RETRIES))
				arch_send_call_function_ipi_mask(cpu_online_mask);
			next_retry = now + CSD_IPI_RETRY_NS;
		}

		if (now < next)
			continue;
		next = now + CSD_STUCK_AGAIN_NS;

		if (atomic_inc_return(&csd_stuck_reports) > CSD_STUCK_MAX_REPORTS)
			continue;

		reported = true;
		pr_alert("csd: CPU%d stuck %llums on CPU%d retries=%u\n",
			 raw_smp_processor_id(),
			 div_u64(now - ts0, NSEC_PER_MSEC), cpu, retries);
		pr_alert("csd: fn=%pS\n", READ_ONCE(csd->func));
		dump_cpu_task(cpu);
	}

	if (unlikely(reported)) {
		pr_alert("csd: CPU%d unstuck after %llums (CPU%d ran it)\n",
			 raw_smp_processor_id(),
			 div_u64(sched_clock() - ts0, NSEC_PER_MSEC), cpu);
		atomic_set(&csd_stuck_reports, 0);
	}
}
''' + smp[end:]
SMP.write_text(smp)


arm_smp = ARM_SMP.read_text()
if "N3DS_QUIET_CPU_STOP" not in arm_smp:
    arm_smp = replace_once(
        arm_smp,
        '''\t\tpr_crit("CPU%u: stopping\\n", cpu);\n\t\tdump_stack();''',
        '''\t\tpr_crit("CPU%u: stopping\\n", cpu);\n\t\t/* N3DS_QUIET_CPU_STOP: do not obscure the real shutdown cause with\n\t\t * innocent interrupted-task stacks on the tiny framebuffer. */\n\t\tif (!IS_ENABLED(CONFIG_ARCH_CTR))\n\t\t\tdump_stack();''',
        "quiet ARM CPU stop",
    )
if "N3DS_SMP_STOP_RETRY" not in arm_smp:
    old_stop = '''void smp_send_stop(void)
{
\tunsigned long timeout;
\tstruct cpumask mask;

\tcpumask_copy(&mask, cpu_online_mask);
\tcpumask_clear_cpu(smp_processor_id(), &mask);
\tif (!cpumask_empty(&mask))
\t\tsmp_cross_call(&mask, IPI_CPU_STOP);

\t/* Wait up to one second for other CPUs to stop */
\ttimeout = USEC_PER_SEC;
\twhile (num_online_cpus() > 1 && timeout--)
\t\tudelay(1);

\tif (num_online_cpus() > 1)
\t\tpr_warn("SMP: failed to stop secondary CPUs\\n");
}'''
    new_stop = '''void smp_send_stop(void)
{
\tunsigned long timeout;
\tunsigned int retries = 0;
\tstruct cpumask mask;

\t/* N3DS_SMP_STOP_RETRY: re-kick still-online CPUs every millisecond. */
\ttimeout = USEC_PER_SEC;
\twhile (num_online_cpus() > 1 && timeout) {
\t\tif (!(timeout % USEC_PER_MSEC)) {
\t\t\tcpumask_andnot(&mask, cpu_online_mask,
\t\t\t\t       cpumask_of(smp_processor_id()));
\t\t\tif (!cpumask_empty(&mask)) {
\t\t\t\tsmp_cross_call(&mask, IPI_CPU_STOP);
\t\t\t\tretries++;
\t\t\t}
\t\t}
\t\tudelay(1);
\t\ttimeout--;
\t}

\tif (num_online_cpus() > 1)
\t\tpr_warn("SMP: failed to stop secondary CPUs after %u retries\\n",
\t\t\tretries);
}'''
    arm_smp = replace_once(arm_smp, old_stop, new_stop, "ARM SMP stop retry")
ARM_SMP.write_text(arm_smp)


panic = PANIC.read_text()
if "N3DS_PANIC_CAUSE_LAST" not in panic:
    panic = replace_once(
        panic,
        '''\t\tcrash_smp_send_stop();\n\t}\n\n\t/*\n\t * Run any panic handlers,''',
        '''\t\tcrash_smp_send_stop();\n\t}\n\t/* N3DS_PANIC_CAUSE_LAST: keep the primary cause visible after CPU stop. */\n\tif (IS_ENABLED(CONFIG_ARCH_CTR))\n\t\tpr_emerg("N3DS primary panic: %s\\n", buf);\n\n\t/*\n\t * Run any panic handlers,''',
        "last panic cause",
    )
PANIC.write_text(panic)


gic = GIC.read_text()
if "N3DS_GIC_SGI_COMMIT_DSB" not in gic:
    gic = replace_once(
        gic,
        '''\twritel_relaxed(map << 16 | d->hwirq, gic_data_dist_base(&gic_data[0]) + GIC_DIST_SOFTINT);\n\n\tgic_unlock_irqrestore(flags);''',
        '''\twritel_relaxed(map << 16 | d->hwirq, gic_data_dist_base(&gic_data[0]) + GIC_DIST_SOFTINT);\n\t/* N3DS_GIC_SGI_COMMIT_DSB: do not begin a synchronous wait while the\n\t * integrated ARM11 GIC distributor write can still be buffered. */\n\tdsb();\n\n\tgic_unlock_irqrestore(flags);''',
        "GIC SGI completion barrier",
    )
if "N3DS_GIC_CPU_INIT_DSB" not in gic:
    gic = replace_once(
        gic,
        '''\twritel_relaxed(GICC_INT_PRI_THRESHOLD, base + GIC_CPU_PRIMASK);\n\tgic_cpu_if_up(gic);\n\n\treturn 0;''',
        '''\twritel_relaxed(GICC_INT_PRI_THRESHOLD, base + GIC_CPU_PRIMASK);\n\tgic_cpu_if_up(gic);\n\t/* N3DS_GIC_CPU_INIT_DSB: commit banked SGI active-clear, priority,\n\t * and CPU-interface enable before this secondary accepts Linux IPIs. */\n\tdsb();\n\n\treturn 0;''',
        "GIC per-CPU init barrier",
    )
GIC.write_text(gic)


if not I2C_HEADER.exists():
    I2C_HEADER.parent.mkdir(parents=True, exist_ok=True)
    I2C_HEADER.write_text(r'''/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _LINUX_PLATFORM_DATA_CTR_I2C_H
#define _LINUX_PLATFORM_DATA_CTR_I2C_H

#include <linux/i2c.h>

/* N3DS_I2C_EMERGENCY_XFER_API: reset and poll the controller without the
 * I2C core bus lock. Reserved for an irrevocable emergency power cut. */
int ctr_i2c_emergency_xfer(struct i2c_adapter *adap,
			   struct i2c_msg *msgs, int num);

#endif
''')


i2c = I2C.read_text()
if "N3DS_I2C_EMERGENCY_XFER" not in i2c:
    i2c = replace_once(
        i2c,
        '''static u32 ctr_i2c_functionality(struct i2c_adapter *adap)\n{''',
        r'''/* N3DS_I2C_EMERGENCY_XFER: the START deadline must not wait for a bus
 * mutex owned by a task on an SMP-stalled CPU. Reset the controller and use
 * the already-bounded polling backend. This deliberately steals the bus and
 * is only valid when the next successful operation cuts board power. */
int ctr_i2c_emergency_xfer(struct i2c_adapter *adap,
			   struct i2c_msg *msgs, int num)
{
	struct ctr_i2c *i2c = container_of(adap, struct ctr_i2c, adap);
	unsigned long flags;
	int ret;

	local_irq_save(flags);
	ctr_i2c_write_cnt(i2c, 0);
	ctr_i2c_write_cntex(i2c, BIT(1));
	ctr_i2c_write_scl(i2c, 5 << 8);
	udelay(10);
	i2c->atomic = true;
	ret = ctr_i2c_do_xfer(i2c, msgs, num);
	i2c->atomic = false;
	local_irq_restore(flags);
	return ret;
}
EXPORT_SYMBOL_GPL(ctr_i2c_emergency_xfer);

static u32 ctr_i2c_functionality(struct i2c_adapter *adap)
{''',
        "emergency I2C transfer",
    )
if '#include <linux/platform_data/ctr_i2c.h>' not in i2c:
    i2c = replace_once(
        i2c,
        '#include <linux/platform_device.h>\n',
        '#include <linux/platform_device.h>\n#include <linux/platform_data/ctr_i2c.h>\n',
        "emergency I2C header",
    )
I2C.write_text(i2c)


if not MCU_HEADER.exists():
    MCU_HEADER.write_text(r'''/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _NINTENDO3DS_MCU_POWEROFF_H
#define _NINTENDO3DS_MCU_POWEROFF_H

/* N3DS_MCU_EMERGENCY_POWEROFF_API */
int ctr_mcu_emergency_poweroff(void);

#endif
''')


mcu = MCU_POWER.read_text()
if "N3DS_MCU_DIRECT_EMERGENCY_CUT" not in mcu:
    insert = r'''
/* N3DS_MCU_DIRECT_EMERGENCY_CUT: bypass reboot notifiers, SMP stop, the I2C
 * core mutex, and interrupt-driven completion after the START deadline. */
int ctr_mcu_emergency_poweroff(void)
{
	u8 buf[2] = { poweroff_reg, poweroff_value };
	struct i2c_msg msg;
	int attempt, ret = -ENODEV;

	if (!poweroff_mcu)
		return -ENODEV;

	msg.addr = poweroff_mcu->addr;
	msg.flags = 0;
	msg.len = sizeof(buf);
	msg.buf = buf;
	for (attempt = 0; attempt < 3; attempt++) {
		ret = ctr_i2c_emergency_xfer(poweroff_mcu->adapter, &msg, 1);
		if (ret == 1)
			return 0;
		udelay(100);
	}
	return ret >= 0 ? -EIO : ret;
}
EXPORT_SYMBOL_GPL(ctr_mcu_emergency_poweroff);
'''
    pos = mcu.index("\nstatic void ctr_mcu_poweroff_prepare(")
    mcu = mcu[:pos] + insert + mcu[pos:]
if '#include <linux/platform_data/ctr_i2c.h>' not in mcu:
    mcu = replace_once(
        mcu,
        '#include <linux/reboot.h>\n',
        '#include <linux/reboot.h>\n#include <linux/platform_data/ctr_i2c.h>\n#include "poweroff.h"\n',
        "MCU emergency headers",
    )
if "ret = ctr_mcu_emergency_poweroff();" not in mcu:
    mcu = replace_once(
        mcu,
        '''\tret = ctr_mcu_write_poweroff();\n\tpr_emerg("atomic write returned %d\\n", ret);''',
        '''\tret = ctr_mcu_emergency_poweroff();\n\tpr_emerg("atomic emergency write returned %d\\n", ret);''',
        "atomic MCU retry",
    )
MCU_POWER.write_text(mcu)


pwrkey = PWRKEY.read_text()
if "N3DS_PWRKEY_DIRECT_MCU_DEADLINE" not in pwrkey:
    pwrkey = replace_once(
        pwrkey,
        '''\tpr_emerg("userspace did not cut power after %u ms -- forcing kernel poweroff\\n",\n\t\t CTR_PWRKEY_FORCE_MS_DEFAULT);\n\temergency_sync();\n\tkernel_power_off();''',
        '''\tpr_emerg("userspace did not cut power after %u ms -- forcing direct MCU cutoff\\n",\n\t\t CTR_PWRKEY_FORCE_MS_DEFAULT);\n\t/* N3DS_PWRKEY_DIRECT_MCU_DEADLINE: emergency_sync() and\n\t * kernel_power_off() both enter paths that require the already-stalled\n\t * filesystem/SMP machinery. Cut power first, then use them only if the\n\t * board is somehow still alive. */\n\tpr_emerg("direct MCU emergency write returned %d\\n",\n\t\t ctr_mcu_emergency_poweroff());\n\tmdelay(CTR_MCU_POWER_CUT_WAIT_MS);\n\tpr_emerg("direct MCU cutoff failed; trying kernel_power_off fallback\\n");\n\tkernel_power_off();''',
        "direct power-key MCU cutoff",
    )
if '#include "mcu/poweroff.h"' not in pwrkey:
    pwrkey = replace_once(
        pwrkey,
        '#include <linux/moduleparam.h>\n',
        '#include <linux/moduleparam.h>\n#include <linux/delay.h>\n#include "mcu/poweroff.h"\n',
        "power-key MCU header",
    )
if "#define CTR_MCU_POWER_CUT_WAIT_MS" not in pwrkey:
    pwrkey = replace_once(
        pwrkey,
        '#define CTR_PWRKEY_FORCE_MS_DEFAULT\t20000\n',
        '#define CTR_PWRKEY_FORCE_MS_DEFAULT\t20000\n#define CTR_MCU_POWER_CUT_WAIT_MS\t1000\n',
        "power-key cutoff wait",
    )
PWRKEY.write_text(pwrkey)


kconfig = KCONFIG.read_text()
if "N3DS_PWRKEY_REQUIRES_MCU" not in kconfig:
    kconfig = replace_once(
        kconfig,
        '''config CTR_PWRKEY\n\tbool "Nintendo 3DS hold-START-to-power-off"\n\tdepends on INPUT''',
        '''config CTR_PWRKEY\n\tbool "Nintendo 3DS hold-START-to-power-off"\n\tdepends on INPUT\n\t# N3DS_PWRKEY_REQUIRES_MCU: direct deadline calls built-in MCU cutoff.\n\tdepends on CTR_MCU = y''',
        "power-key MCU dependency",
    )
KCONFIG.write_text(kconfig)


checks = (
    (SMP, "N3DS_CSD_IPI_PROGRESS_RECOVERY"),
    (ARM_SMP, "N3DS_QUIET_CPU_STOP"),
    (ARM_SMP, "N3DS_SMP_STOP_RETRY"),
    (PANIC, "N3DS_PANIC_CAUSE_LAST"),
    (GIC, "N3DS_GIC_SGI_COMMIT_DSB"),
    (GIC, "N3DS_GIC_CPU_INIT_DSB"),
    (I2C, "N3DS_I2C_EMERGENCY_XFER"),
    (MCU_POWER, "N3DS_MCU_DIRECT_EMERGENCY_CUT"),
    (PWRKEY, "N3DS_PWRKEY_DIRECT_MCU_DEADLINE"),
    (KCONFIG, "N3DS_PWRKEY_REQUIRES_MCU"),
)
for path, marker in checks:
    if marker not in path.read_text():
        raise SystemExit(f"missing {marker} in {path}")

print("patch_n3ds_smp_poweroff_recovery: IPI progress recovery and direct MCU cutoff enabled")
