"""Phase 3: port kernel/power/{wakelock,earlysuspend}.c from
android-goldfish-2.6.29 onto 5.11.

wakelock.c is NOT a mechanical API port like logger/lowmemorykiller -- the
old wake_lock C API (wake_lock_init/wake_lock/wake_lock_timeout/
wake_unlock/wake_lock_active/has_wake_lock, driving Android's own
"opportunistic suspend" scheduler) was never itself mainlined. What WAS
mainlined, replacing it, is the wakeup_source model (wakeup_source_
register/__pm_stay_awake/__pm_wakeup_event/__pm_relax + CONFIG_PM_AUTOSLEEP)
-- this is implemented here as a compat shim translating the old C API onto
wakeup_source, which is exactly the approach real historical kernel trees
used during the multi-year transition period before old Android drivers
were themselves rewritten to call wakeup_source directly. struct wake_lock
now just wraps a struct wakeup_source *.

One deliberate authenticity gap: WAKE_LOCK_IDLE vs WAKE_LOCK_SUSPEND was a
real distinction in the original (idle-only locks block deep idle states
without blocking full suspend); wakeup_source's model doesn't preserve
that distinction, so both types are treated as "prevent suspend" here.
Documented in wakelock.h; nothing in this project currently depends on
the IDLE/SUSPEND distinction (alarm.c only ever uses WAKE_LOCK_SUSPEND).

has_wake_lock()'s original semantics (exact per-type active/timeout
introspection) aren't reproducible from outside the wakeup_source core
without re-deriving that bookkeeping; it's approximated via
pm_wakeup_pending() here and documented as such. Nothing ported so far
calls it (alarm.c only calls wake_lock_active()).

/sys/power/wake_lock and /sys/power/wake_unlock (Eclair's userwakelock.c,
the userspace-facing sysfs interface) are NOT ported -- CONFIG_PM_WAKELOCKS
already provides an equivalent, already-mainlined sysfs interface with the
same two files in this exact tree (kernel/power/wakelock.c, a DIFFERENT
file of the same name doing the same job) -- enabling it is a Kconfig
change, not a port.

earlysuspend.c: the level-ordered register_early_suspend/
unregister_early_suspend notifier chain and its early_suspend/late_resume
workqueue callbacks are ported close to verbatim -- that mechanism itself
was never mainlined either and real Eclair-era drivers (framebuffer
blanking, touch power gating) call it directly. request_suspend_state()/
get_suspend_state() are kept, but main_wake_lock/suspend_work_queue are
now defined locally in this file instead of shared with kernel/power/
main.c's /sys/power/state sysfs handler (that file is extensively
different in 5.11 and wiring a legacy trigger path through it is out of
scope for a kernel-driver port with no userspace yet to trigger it from --
nothing stops a later phase from calling request_suspend_state() once
PowerManagerService exists).
"""
from a3ds_paths import A3DS_ROOT

import os

# NOT kernel/power/ -- kernel/power/wakelock.c already exists in this tree
# (the real mainline /sys/power/wake_lock sysfs implementation, CONFIG_
# PM_WAKELOCKS). Placed in drivers/staging/android/ instead, alongside the
# other ported drivers, under android_-prefixed names so there's no
# collision with either that file or a future real earlysuspend.c.
DRV = f"{A3DS_ROOT}/third_party/linux/drivers/staging/android"
INC = f"{A3DS_ROOT}/third_party/linux/include/linux"

wakelock_h = """/* SPDX-License-Identifier: GPL-2.0 */
/* include/linux/wakelock.h
 *
 * Copyright (C) 2007-2008 Google, Inc.
 *
 * Ported from android-goldfish-2.6.29 as a compat shim over the mainline
 * wakeup_source API (struct wake_lock now just wraps a
 * struct wakeup_source *) -- see port_wakelock_earlysuspend.py for the
 * full rationale. The old WAKE_LOCK_IDLE/WAKE_LOCK_SUSPEND distinction is
 * NOT preserved; both types prevent suspend the same way here.
 */
#ifndef _LINUX_WAKELOCK_H
#define _LINUX_WAKELOCK_H

#include <linux/pm_wakeup.h>

enum {
	WAKE_LOCK_SUSPEND, /* Prevent suspend */
	WAKE_LOCK_IDLE,    /* Historically: prevent low power idle only.
			    * Not distinguished from WAKE_LOCK_SUSPEND by
			    * this shim -- see port notes. */
	WAKE_LOCK_TYPE_COUNT
};

struct wake_lock {
	struct wakeup_source	*ws;
};

void wake_lock_init(struct wake_lock *lock, int type, const char *name);
void wake_lock_destroy(struct wake_lock *lock);
void wake_lock(struct wake_lock *lock);
void wake_lock_timeout(struct wake_lock *lock, long timeout);
void wake_unlock(struct wake_lock *lock);

/* Non-zero if currently held (unexpired). */
int wake_lock_active(struct wake_lock *lock);

/* Approximated via pm_wakeup_pending() -- see port notes. Original
 * semantics (exact per-type active/timeout introspection across every
 * wake_lock in the system) aren't reproducible from outside the
 * wakeup_source core. */
long has_wake_lock(int type);

#endif
"""

wakelock_c = """// SPDX-License-Identifier: GPL-2.0
/*
 * drivers/staging/android/android_wakelock.c
 *
 * Copyright (C) 2007-2008 Google, Inc.
 *
 * Compat shim: the Eclair-era wake_lock C API implemented over the
 * mainline wakeup_source API. See wakelock.h and
 * port_wakelock_earlysuspend.py for what changed and why.
 */

#include <linux/wakelock.h>
#include <linux/jiffies.h>
#include <linux/module.h>
#include <linux/slab.h>

void wake_lock_init(struct wake_lock *lock, int type, const char *name)
{
	lock->ws = wakeup_source_register(NULL, name);
}
EXPORT_SYMBOL(wake_lock_init);

void wake_lock_destroy(struct wake_lock *lock)
{
	wakeup_source_unregister(lock->ws);
	lock->ws = NULL;
}
EXPORT_SYMBOL(wake_lock_destroy);

void wake_lock(struct wake_lock *lock)
{
	__pm_stay_awake(lock->ws);
}
EXPORT_SYMBOL(wake_lock);

void wake_lock_timeout(struct wake_lock *lock, long timeout)
{
	__pm_wakeup_event(lock->ws, jiffies_to_msecs(timeout));
}
EXPORT_SYMBOL(wake_lock_timeout);

void wake_unlock(struct wake_lock *lock)
{
	__pm_relax(lock->ws);
}
EXPORT_SYMBOL(wake_unlock);

int wake_lock_active(struct wake_lock *lock)
{
	return lock->ws->active;
}
EXPORT_SYMBOL(wake_lock_active);

long has_wake_lock(int type)
{
	return pm_wakeup_pending() ? -1 : 0;
}
EXPORT_SYMBOL(has_wake_lock);
"""

earlysuspend_h = """/* SPDX-License-Identifier: GPL-2.0 */
/* include/linux/earlysuspend.h
 *
 * Copyright (C) 2007-2008 Google, Inc.
 *
 * Ported from android-goldfish-2.6.29 -- the level-ordered
 * register_early_suspend()/unregister_early_suspend() notifier chain
 * itself was never mainlined; real Eclair-era drivers (framebuffer
 * blanking, touch power gating) call it directly, so it's ported close
 * to verbatim rather than shimmed onto something else.
 */
#ifndef _LINUX_EARLYSUSPEND_H
#define _LINUX_EARLYSUSPEND_H

#include <linux/list.h>
#include <linux/suspend.h>

/* Levels are ordered from higher to lower priority for suspend, and
 * lower to higher priority for resume. Most drivers should use level 0. */
#define EARLY_SUSPEND_LEVEL_BLANK_SCREEN 50
#define EARLY_SUSPEND_LEVEL_STOP_DRAWING 100
#define EARLY_SUSPEND_LEVEL_DISABLE_FB 150

struct early_suspend {
	struct list_head link;
	int level;
	void (*suspend)(struct early_suspend *h);
	void (*resume)(struct early_suspend *h);
};

void register_early_suspend(struct early_suspend *handler);
void unregister_early_suspend(struct early_suspend *handler);

void request_suspend_state(suspend_state_t state);
suspend_state_t get_suspend_state(void);

#endif
"""

earlysuspend_c = """// SPDX-License-Identifier: GPL-2.0
/*
 * drivers/staging/android/android_earlysuspend.c
 *
 * Copyright (C) 2005-2008 Google, Inc.
 *
 * Ported from android-goldfish-2.6.29. The notifier-chain mechanism
 * (register_early_suspend/unregister_early_suspend, the level-ordered
 * handler list, the early_suspend/late_resume workqueue pair) is
 * unchanged from the original.
 *
 * main_wake_lock/suspend_work_queue are now local to this file instead
 * of shared with kernel/power/main.c's /sys/power/state handler (that
 * file differs substantially in 5.11, and there's no userspace yet --
 * Phase 6 -- to drive /sys/power/state in the first place). Nothing
 * stops wiring request_suspend_state() through main.c later once
 * PowerManagerService exists to call it.
 */

#include <linux/earlysuspend.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/rtc.h>
#include <linux/wakelock.h>
#include <linux/workqueue.h>

enum {
	DEBUG_USER_STATE = 1U << 0,
	DEBUG_SUSPEND = 1U << 2,
};
static int debug_mask = DEBUG_USER_STATE;
module_param_named(debug_mask, debug_mask, int, 0644);

static DEFINE_MUTEX(early_suspend_lock);
static LIST_HEAD(early_suspend_handlers);
static void early_suspend(struct work_struct *work);
static void late_resume(struct work_struct *work);
static DECLARE_WORK(early_suspend_work, early_suspend);
static DECLARE_WORK(late_resume_work, late_resume);
static DEFINE_SPINLOCK(state_lock);
enum {
	SUSPEND_REQUESTED = 0x1,
	SUSPENDED = 0x2,
	SUSPEND_REQUESTED_AND_SUSPENDED = SUSPEND_REQUESTED | SUSPENDED,
};
static int state;
static suspend_state_t requested_suspend_state = PM_SUSPEND_ON;
static struct wake_lock main_wake_lock;
static struct workqueue_struct *suspend_work_queue;

void register_early_suspend(struct early_suspend *handler)
{
	struct list_head *pos;

	mutex_lock(&early_suspend_lock);
	list_for_each(pos, &early_suspend_handlers) {
		struct early_suspend *e;

		e = list_entry(pos, struct early_suspend, link);
		if (e->level > handler->level)
			break;
	}
	list_add_tail(&handler->link, pos);
	if ((state & SUSPENDED) && handler->suspend)
		handler->suspend(handler);
	mutex_unlock(&early_suspend_lock);
}
EXPORT_SYMBOL(register_early_suspend);

void unregister_early_suspend(struct early_suspend *handler)
{
	mutex_lock(&early_suspend_lock);
	list_del(&handler->link);
	mutex_unlock(&early_suspend_lock);
}
EXPORT_SYMBOL(unregister_early_suspend);

static void early_suspend(struct work_struct *work)
{
	struct early_suspend *pos;
	unsigned long irqflags;
	int abort = 0;

	mutex_lock(&early_suspend_lock);
	spin_lock_irqsave(&state_lock, irqflags);
	if (state == SUSPEND_REQUESTED)
		state |= SUSPENDED;
	else
		abort = 1;
	spin_unlock_irqrestore(&state_lock, irqflags);

	if (abort) {
		if (debug_mask & DEBUG_SUSPEND)
			pr_info("early_suspend: abort, state %d\\n", state);
		mutex_unlock(&early_suspend_lock);
		goto abort;
	}

	if (debug_mask & DEBUG_SUSPEND)
		pr_info("early_suspend: call handlers\\n");
	list_for_each_entry(pos, &early_suspend_handlers, link) {
		if (pos->suspend)
			pos->suspend(pos);
	}
	mutex_unlock(&early_suspend_lock);

	if (debug_mask & DEBUG_SUSPEND)
		pr_info("early_suspend: sync\\n");

	ksys_sync();
abort:
	spin_lock_irqsave(&state_lock, irqflags);
	if (state == SUSPEND_REQUESTED_AND_SUSPENDED)
		wake_unlock(&main_wake_lock);
	spin_unlock_irqrestore(&state_lock, irqflags);
}

static void late_resume(struct work_struct *work)
{
	struct early_suspend *pos;
	unsigned long irqflags;
	int abort = 0;

	mutex_lock(&early_suspend_lock);
	spin_lock_irqsave(&state_lock, irqflags);
	if (state == SUSPENDED)
		state &= ~SUSPENDED;
	else
		abort = 1;
	spin_unlock_irqrestore(&state_lock, irqflags);

	if (abort) {
		if (debug_mask & DEBUG_SUSPEND)
			pr_info("late_resume: abort, state %d\\n", state);
		goto abort;
	}
	if (debug_mask & DEBUG_SUSPEND)
		pr_info("late_resume: call handlers\\n");
	list_for_each_entry_reverse(pos, &early_suspend_handlers, link)
		if (pos->resume)
			pos->resume(pos);
	if (debug_mask & DEBUG_SUSPEND)
		pr_info("late_resume: done\\n");
abort:
	mutex_unlock(&early_suspend_lock);
}

void request_suspend_state(suspend_state_t new_state)
{
	unsigned long irqflags;
	int old_sleep;

	spin_lock_irqsave(&state_lock, irqflags);
	old_sleep = state & SUSPEND_REQUESTED;
	if (debug_mask & DEBUG_USER_STATE) {
		struct timespec64 ts;
		struct rtc_time tm;

		ktime_get_real_ts64(&ts);
		rtc_time64_to_tm(ts.tv_sec, &tm);
		pr_info("request_suspend_state: %s (%d->%d) at %lld "
			"(%d-%02d-%02d %02d:%02d:%02d.%09lu UTC)\\n",
			new_state != PM_SUSPEND_ON ? "sleep" : "wakeup",
			requested_suspend_state, new_state,
			ktime_to_ns(ktime_get()),
			tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
			tm.tm_hour, tm.tm_min, tm.tm_sec, ts.tv_nsec);
	}
	if (!old_sleep && new_state != PM_SUSPEND_ON) {
		state |= SUSPEND_REQUESTED;
		queue_work(suspend_work_queue, &early_suspend_work);
	} else if (old_sleep && new_state == PM_SUSPEND_ON) {
		state &= ~SUSPEND_REQUESTED;
		wake_lock(&main_wake_lock);
		queue_work(suspend_work_queue, &late_resume_work);
	}
	requested_suspend_state = new_state;
	spin_unlock_irqrestore(&state_lock, irqflags);
}
EXPORT_SYMBOL(request_suspend_state);

suspend_state_t get_suspend_state(void)
{
	return requested_suspend_state;
}
EXPORT_SYMBOL(get_suspend_state);

static int __init earlysuspend_init(void)
{
	suspend_work_queue = create_singlethread_workqueue("suspend");
	if (!suspend_work_queue)
		return -ENOMEM;
	wake_lock_init(&main_wake_lock, WAKE_LOCK_SUSPEND, "main");
	wake_lock(&main_wake_lock);
	return 0;
}

static void __exit earlysuspend_exit(void)
{
	wake_lock_destroy(&main_wake_lock);
	destroy_workqueue(suspend_work_queue);
}

core_initcall(earlysuspend_init);
module_exit(earlysuspend_exit);
"""

with open(os.path.join(INC, "wakelock.h"), "w") as f:
    f.write(wakelock_h)
with open(os.path.join(DRV, "android_wakelock.c"), "w") as f:
    f.write(wakelock_c)
with open(os.path.join(INC, "earlysuspend.h"), "w") as f:
    f.write(earlysuspend_h)
with open(os.path.join(DRV, "android_earlysuspend.c"), "w") as f:
    f.write(earlysuspend_c)

print("OK")
