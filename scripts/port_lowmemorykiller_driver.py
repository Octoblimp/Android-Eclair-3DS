"""Phase 3: port drivers/staging/android/lowmemorykiller.c from
android-goldfish-2.6.29 onto 5.11.

Kernel-internal API changes needed, all mechanical:
  - struct shrinker.shrink(int nr_to_scan, gfp_t) [one callback, dual use
    as both "count" and "scan" depending on nr_to_scan] -> two separate
    callbacks, .count_objects()/.scan_objects(shrinker, shrink_control)
  - register_shrinker() still takes just the shrinker pointer in this
    tree's vmscan.c, but now returns int (can fail: -ENOMEM) instead of
    void -- checked in init.
  - task_struct->oomkilladj [[[removed]]] -> signal->oom_score_adj, a
    DIFFERENT scale (-1000..1000 linear, not -17..15 exponential). The
    kernel's own /proc/<pid>/oom_adj compat write path (fs/proc/base.c,
    oom_adj_write()) converts old-scale writes with
    oom_score_adj = oom_adj * OOM_SCORE_ADJ_MAX / -OOM_DISABLE (*1000/17).
    Real, unmodified Eclair ActivityManager writes raw old-scale numbers
    to /proc/<pid>/oom_adj (that compat file still exists in 5.11, just
    deprecated with a one-time dmesg warning) -- so lowmem_adj[]'s
    thresholds are kept in real Eclair oom_adj units and converted with
    the exact same formula, so this driver's comparisons line up exactly
    with what oom_adj_write() actually produces.
  - global_page_state() split into global_zone_page_state() (NR_FREE_PAGES)
    and global_node_page_state() (the LRU/file-page counters) around the
    per-node/per-zone stat split.
  - force_sig(sig, task) [[[two-arg form removed]]] -> force_sig(int) now
    only targets current; killing an arbitrary selected task is
    send_sig(sig, task, 1) (priv=1: kernel-generated, bypasses permission
    checks, matching what force_sig(sig, task) used to do).
  - Directly touching p->mm under read_lock(&tasklist_lock) is no longer
    the recommended-safe pattern; find_lock_task_mm() (RCU + task_lock)
    is the standard current idiom for "does this task have a live mm,
    give me a locked reference to it" and is what this port uses instead.
"""
from a3ds_paths import A3DS_ROOT

import os

DRV = f"{A3DS_ROOT}/third_party/linux/drivers/staging/android"

lowmemorykiller_c = """// SPDX-License-Identifier: GPL-2.0
/*
 * drivers/staging/android/lowmemorykiller.c
 *
 * Copyright (C) 2007-2008 Google, Inc.
 *
 * Ported from android-goldfish-2.6.29 (real Eclair-era source) onto the
 * 5.11 two-callback shrinker API and oom_score_adj OOM API. See the port
 * notes in port_lowmemorykiller_driver.py for what changed and why; the
 * selection policy (highest adj first, then largest RSS) is unchanged
 * from the original.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/mm.h>
#include <linux/oom.h>
#include <linux/sched.h>
#include <linux/sched/mm.h>
#include <linux/sched/signal.h>
#include <linux/rcupdate.h>
#include <linux/vmstat.h>
#include <linux/shrinker.h>

/*
 * fs/proc/base.c oom_adj_write(): oom_score_adj = oom_adj * OOM_SCORE_ADJ_MAX
 * / -OOM_DISABLE, i.e. oom_adj * 1000 / 17. Real Eclair values, converted
 * here with the exact same integer-truncating formula the kernel itself
 * uses for /proc/<pid>/oom_adj compat writes, so an unmodified Eclair
 * ActivityManager writing old-scale numbers lines up exactly with what
 * this driver compares against.
 */
#define OOM_ADJ_TO_SCORE_ADJ(adj)	(((adj) * OOM_SCORE_ADJ_MAX) / -OOM_DISABLE)

static uint32_t lowmem_debug_level = 2;
static short lowmem_adj[6] = {
	OOM_ADJ_TO_SCORE_ADJ(0),
	OOM_ADJ_TO_SCORE_ADJ(1),
	OOM_ADJ_TO_SCORE_ADJ(6),
	OOM_ADJ_TO_SCORE_ADJ(12),
};
static int lowmem_adj_size = 4;
static size_t lowmem_minfree[6] = {
	3 * 512,	/* 6MB */
	2 * 1024,	/* 8MB */
	4 * 1024,	/* 16MB */
	16 * 1024,	/* 64MB */
};
static int lowmem_minfree_size = 4;

#define lowmem_print(level, x...) \\
	do { if (lowmem_debug_level >= (level)) printk(x); } while (0)

static unsigned long lowmem_count(struct shrinker *s, struct shrink_control *sc)
{
	return global_node_page_state(NR_ACTIVE_ANON) +
		global_node_page_state(NR_ACTIVE_FILE) +
		global_node_page_state(NR_INACTIVE_ANON) +
		global_node_page_state(NR_INACTIVE_FILE);
}

static unsigned long lowmem_scan(struct shrinker *s, struct shrink_control *sc)
{
	struct task_struct *tsk;
	struct task_struct *selected = NULL;
	unsigned long rem = 0;
	int tasksize;
	int i;
	short min_score_adj = OOM_SCORE_ADJ_MAX + 1;
	int selected_tasksize = 0;
	short selected_oom_score_adj = 0;
	int array_size = ARRAY_SIZE(lowmem_adj);
	int other_free = global_zone_page_state(NR_FREE_PAGES);
	int other_file = global_node_page_state(NR_FILE_PAGES);

	if (lowmem_adj_size < array_size)
		array_size = lowmem_adj_size;
	if (lowmem_minfree_size < array_size)
		array_size = lowmem_minfree_size;
	for (i = 0; i < array_size; i++) {
		if (other_free < lowmem_minfree[i] &&
		    other_file < lowmem_minfree[i]) {
			min_score_adj = lowmem_adj[i];
			break;
		}
	}

	lowmem_print(3, "lowmem_scan %lu, %x, ofree %d %d, ma %hd\\n",
		     sc->nr_to_scan, sc->gfp_mask, other_free, other_file,
		     min_score_adj);

	if (min_score_adj == OOM_SCORE_ADJ_MAX + 1) {
		lowmem_print(5, "lowmem_scan %lu, %x, return 0\\n",
			     sc->nr_to_scan, sc->gfp_mask);
		return 0;
	}

	rcu_read_lock();
	for_each_process(tsk) {
		struct task_struct *p;
		short oom_score_adj;

		p = find_lock_task_mm(tsk);
		if (!p)
			continue;

		oom_score_adj = p->signal->oom_score_adj;
		if (oom_score_adj < min_score_adj) {
			task_unlock(p);
			continue;
		}
		tasksize = get_mm_rss(p->mm);
		task_unlock(p);
		if (tasksize <= 0)
			continue;
		if (selected) {
			if (oom_score_adj < selected_oom_score_adj)
				continue;
			if (oom_score_adj == selected_oom_score_adj &&
			    tasksize <= selected_tasksize)
				continue;
		}
		selected = p;
		selected_tasksize = tasksize;
		selected_oom_score_adj = oom_score_adj;
		lowmem_print(2, "select %d (%s), adj %hd, size %d, to kill\\n",
			     p->pid, p->comm, oom_score_adj, tasksize);
	}
	if (selected) {
		lowmem_print(1, "send sigkill to %d (%s), adj %hd, size %d\\n",
			     selected->pid, selected->comm,
			     selected_oom_score_adj, selected_tasksize);
		send_sig(SIGKILL, selected, 1);
		rem += selected_tasksize;
	}
	lowmem_print(4, "lowmem_scan %lu, %x, return %lu\\n",
		     sc->nr_to_scan, sc->gfp_mask, rem);
	rcu_read_unlock();
	return rem;
}

static struct shrinker lowmem_shrinker = {
	.count_objects = lowmem_count,
	.scan_objects = lowmem_scan,
	.seeks = DEFAULT_SEEKS * 16,
};

module_param_named(cost, lowmem_shrinker.seeks, int, S_IRUGO | S_IWUSR);
module_param_array_named(adj, lowmem_adj, short, &lowmem_adj_size, S_IRUGO | S_IWUSR);
module_param_array_named(minfree, lowmem_minfree, uint, &lowmem_minfree_size, S_IRUGO | S_IWUSR);
module_param_named(debug_level, lowmem_debug_level, uint, S_IRUGO | S_IWUSR);

static int __init lowmem_init(void)
{
	return register_shrinker(&lowmem_shrinker);
}

static void __exit lowmem_exit(void)
{
	unregister_shrinker(&lowmem_shrinker);
}

module_init(lowmem_init);
module_exit(lowmem_exit);

MODULE_LICENSE("GPL");
"""

with open(os.path.join(DRV, "lowmemorykiller.c"), "w") as f:
    f.write(lowmemorykiller_c)

# Kconfig
kconfig_path = os.path.join(DRV, "Kconfig")
with open(kconfig_path) as f:
    kconfig = f.read()

old = """config LOGGER
	bool "Android log driver"
	default y
	help
	  This adds support for system-wide logging using four log buffers:
	  main, events, radio, and system. Real AOSP liblog/logd open
	  /dev/log_{main,events,radio} directly and read/write/ioctl() them
	  in a fixed binary format (struct logger_entry) -- ported from the
	  Eclair-era android-goldfish-2.6.29 driver of the same name.

endif # if ANDROID"""

assert old in kconfig, "logger Kconfig block not found verbatim"

new = """config LOGGER
	bool "Android log driver"
	default y
	help
	  This adds support for system-wide logging using four log buffers:
	  main, events, radio, and system. Real AOSP liblog/logd open
	  /dev/log_{main,events,radio} directly and read/write/ioctl() them
	  in a fixed binary format (struct logger_entry) -- ported from the
	  Eclair-era android-goldfish-2.6.29 driver of the same name.

config ANDROID_LOW_MEMORY_KILLER
	bool "Android Low Memory Killer"
	default y
	help
	  Registers a shrinker that kills processes based on their
	  oom_adj (/proc/<pid>/oom_adj, real AOSP ActivityManager writes
	  this directly) once free memory drops below configurable
	  thresholds -- ported from the Eclair-era
	  android-goldfish-2.6.29 driver of the same name. See
	  Documentation/../lowmemorykiller.txt for the adj/minfree tuning
	  format.

endif # if ANDROID"""

kconfig = kconfig.replace(old, new)
with open(kconfig_path, "w") as f:
    f.write(kconfig)

# Makefile
makefile_path = os.path.join(DRV, "Makefile")
with open(makefile_path) as f:
    makefile = f.read()

old_mk = "obj-$(CONFIG_LOGGER)\t\t\t+= logger.o\n"
assert old_mk in makefile, "logger Makefile line not found verbatim"
makefile = makefile.replace(
    old_mk, old_mk + "obj-$(CONFIG_ANDROID_LOW_MEMORY_KILLER)\t+= lowmemorykiller.o\n"
)
with open(makefile_path, "w") as f:
    f.write(makefile)

print("OK")
