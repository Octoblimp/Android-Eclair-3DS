"""Phase 3: port drivers/rtc/alarm.c from android-goldfish-2.6.29 onto 5.11.

Kernel-internal API changes needed, all mechanical:
  - struct timespec [[[removed from kernel-internal use]]] -> struct
    timespec64 for all internal state/hrtimer/ktime computation; struct
    old_timespec32 (include/linux/time32.h, same 8-byte {s32,s32} layout
    on this 32-bit ARM target) for the userspace-facing ioctl wire format,
    which must stay byte-identical to what real Eclair userspace sends --
    the ioctl command NUMBERS themselves encode sizeof(the wire struct)
    via the _IOW macro, so as long as old_timespec32 is also 8 bytes here
    the numbers come out identical to the original's, whether or not the
    type is literally named "struct timespec".
  - getnstimeofday()/ktime_get_ts() -> ktime_get_real_ts64()/ktime_get_ts64()
  - timespec_to_ktime/set_normalized_timespec/timespec_sub/timespec_compare
    -> the _64 equivalents
  - do_settimeofday(timespec*) -> do_settimeofday64(timespec64*)
  - rtc_time_to_tm(sec, tm)/rtc_tm_to_time(tm, &sec) [[[unsigned-long-based,
    removed]]] -> rtc_time64_to_tm(time64_t, tm)/rtc_tm_to_time64(tm)
    (time64_t based)
  - <linux/sysdev.h> [[[removed entirely, unused in the actual code body]]]
    -> dropped

One real functionality gap, not just a rename: alarm_rtc_task/
rtc_irq_register()/rtc_irq_unregister()/alarm_triggered_func() are DROPPED.
That mechanism (register a raw kernel callback for "the RTC alarm IRQ just
fired") doesn't exist in any form in mainline anymore -- the whole
rtc_task/rtc_irq_register API was purged when the RTC framework moved to
rtc_class_ops-based alarm handling. Its only job was holding a brief
wake_lock the instant the RTC hardware alarm fires, purely to close a race
during a REAL system suspend/resume cycle (RTC IRQ fires before userspace
has a chance to re-acquire a wakelock in response). It is not required for
any of /dev/alarm's core ioctls (SET/WAIT/GET_TIME/CLEAR/SET_RTC) to work.
Given this project has no working suspend/resume cycle yet to race against,
this gap is low-stakes now and worth revisiting once real suspend exists.
"""
from a3ds_paths import A3DS_ROOT

import os

DRV_RTC = f"{A3DS_ROOT}/third_party/linux/drivers/rtc"
UAPI_DIR = f"{DRV_RTC}/uapi"

uapi_h = """/* SPDX-License-Identifier: GPL-2.0 */
/* drivers/rtc/uapi/android_alarm.h
 *
 * Copyright (C) 2006-2007 Google, Inc.
 *
 * Ported from android-goldfish-2.6.29. Wire ABI real Eclair code opens
 * /dev/alarm and ioctl()s against -- ioctl numbers and the timespec wire
 * size (8 bytes on this 32-bit target, struct old_timespec32 here vs.
 * struct timespec originally, but _IOW() only cares about sizeof()) must
 * not change. See port_alarm_driver.py for the full rationale.
 */
#ifndef _UAPI_ANDROID_ALARM_H
#define _UAPI_ANDROID_ALARM_H

#include <linux/ioctl.h>
#include <linux/time32.h>

enum android_alarm_type {
	/* return code bit numbers or set alarm arg */
	ANDROID_ALARM_RTC_WAKEUP,
	ANDROID_ALARM_RTC,
	ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP,
	ANDROID_ALARM_ELAPSED_REALTIME,
	ANDROID_ALARM_SYSTEMTIME,

	ANDROID_ALARM_TYPE_COUNT,

	/* return code bit numbers */
	/* ANDROID_ALARM_TIME_CHANGE = 16 */
};

enum android_alarm_return_flags {
	ANDROID_ALARM_RTC_WAKEUP_MASK = 1U << ANDROID_ALARM_RTC_WAKEUP,
	ANDROID_ALARM_RTC_MASK = 1U << ANDROID_ALARM_RTC,
	ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP_MASK =
				1U << ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP,
	ANDROID_ALARM_ELAPSED_REALTIME_MASK =
				1U << ANDROID_ALARM_ELAPSED_REALTIME,
	ANDROID_ALARM_SYSTEMTIME_MASK = 1U << ANDROID_ALARM_SYSTEMTIME,
	ANDROID_ALARM_TIME_CHANGE_MASK = 1U << 16
};

/* Disable alarm */
#define ANDROID_ALARM_CLEAR(type)           _IO('a', 0 | ((type) << 4))

/* Ack last alarm and wait for next */
#define ANDROID_ALARM_WAIT                  _IO('a', 1)

#define ALARM_IOW(c, type, size)            _IOW('a', (c) | ((type) << 4), size)
/* Set alarm */
#define ANDROID_ALARM_SET(type)             ALARM_IOW(2, type, struct old_timespec32)
#define ANDROID_ALARM_SET_AND_WAIT(type)    ALARM_IOW(3, type, struct old_timespec32)
#define ANDROID_ALARM_GET_TIME(type)        ALARM_IOW(4, type, struct old_timespec32)
#define ANDROID_ALARM_SET_RTC               _IOW('a', 5, struct old_timespec32)
#define ANDROID_ALARM_BASE_CMD(cmd)         (cmd & ~(_IOC(0, 0, 0xf0, 0)))
#define ANDROID_ALARM_IOCTL_TO_TYPE(cmd)    (_IOC_NR(cmd) >> 4)

#endif
"""

alarm_h = """/* SPDX-License-Identifier: GPL-2.0 */
/* include/linux/android_alarm.h
 *
 * Copyright (C) 2006-2007 Google, Inc.
 */
#ifndef _LINUX_ANDROID_ALARM_H
#define _LINUX_ANDROID_ALARM_H

#include "uapi/android_alarm.h"

#endif
"""

alarm_c = """// SPDX-License-Identifier: GPL-2.0
/*
 * drivers/rtc/alarm.c
 *
 * Copyright (C) 2007 Google, Inc.
 *
 * Ported from android-goldfish-2.6.29 (real Eclair-era source) onto
 * 5.11's timespec64/time64_t RTC and timekeeping API. See the port notes
 * in port_alarm_driver.py for what changed, why, and the one real
 * functionality gap (the RTC-IRQ-fired wakelock, whose kernel hook no
 * longer exists in any form). Everything else -- the ioctl set, the
 * hrtimer-per-alarm-type model, elapsed-realtime delta tracking, suspend/
 * resume RTC alarm programming -- is unchanged from the original.
 */

#include <asm/mach/time.h>
#include <linux/module.h>
#include <linux/android_alarm.h>
#include <linux/device.h>
#include <linux/miscdevice.h>
#include <linux/platform_device.h>
#include <linux/rtc.h>
#include <linux/spinlock.h>
#include <linux/wakelock.h>
#include <linux/uaccess.h>

#define ANDROID_ALARM_PRINT_ERRORS (1U << 0)
#define ANDROID_ALARM_PRINT_INIT_STATUS (1U << 1)
#define ANDROID_ALARM_PRINT_INFO (1U << 2)
#define ANDROID_ALARM_PRINT_IO (1U << 3)
#define ANDROID_ALARM_PRINT_INT (1U << 4)
#define ANDROID_ALARM_PRINT_FLOW (1U << 5)

#define ANDROID_ALARM_DPRINTF(args...)

#define ANDROID_ALARM_WAKEUP_MASK ( \\
	ANDROID_ALARM_RTC_WAKEUP_MASK | \\
	ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP_MASK)

/* support old userspace code */
#define ANDROID_ALARM_SET_OLD               _IOW('a', 2, old_time32_t) /* set alarm */
#define ANDROID_ALARM_SET_AND_WAIT_OLD      _IOW('a', 3, old_time32_t)

static struct rtc_device *alarm_rtc_dev;
static int alarm_opened;
static DEFINE_SPINLOCK(alarm_slock);
static DEFINE_MUTEX(alarm_setrtc_mutex);
static struct wake_lock alarm_wake_lock;
static struct wake_lock alarm_rtc_wake_lock;
static DECLARE_WAIT_QUEUE_HEAD(alarm_wait_queue);
static uint32_t alarm_pending;
static uint32_t alarm_enabled;
static uint32_t wait_pending;
static struct platform_device *alarm_platform_dev;
static struct hrtimer alarm_timer[ANDROID_ALARM_TYPE_COUNT];
static struct timespec64 alarm_time[ANDROID_ALARM_TYPE_COUNT];
static struct timespec64 elapsed_rtc_delta;

static void alarm_start_hrtimer(enum android_alarm_type alarm_type)
{
	struct timespec64 hr_alarm_time;

	if (!(alarm_enabled & (1U << alarm_type)))
		return;
	hr_alarm_time = alarm_time[alarm_type];
	if (alarm_type == ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP ||
	    alarm_type == ANDROID_ALARM_ELAPSED_REALTIME)
		set_normalized_timespec64(&hr_alarm_time,
			hr_alarm_time.tv_sec + elapsed_rtc_delta.tv_sec,
			hr_alarm_time.tv_nsec + elapsed_rtc_delta.tv_nsec);
	ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_FLOW,
		"alarm start hrtimer %d at %lld.%09ld\\n",
		alarm_type, hr_alarm_time.tv_sec, hr_alarm_time.tv_nsec);
	hrtimer_start(&alarm_timer[alarm_type],
		      timespec64_to_ktime(hr_alarm_time), HRTIMER_MODE_ABS);
}

static long alarm_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	int rv = 0;
	unsigned long flags;
	int i;
	struct old_timespec32 new_alarm_time32;
	struct timespec64 new_alarm_time;
	struct old_timespec32 new_rtc_time32;
	struct timespec64 new_rtc_time;
	struct timespec64 tmp_time;
	struct old_timespec32 tmp_time32;
	struct rtc_time rtc_new_rtc_time;
	enum android_alarm_type alarm_type = ANDROID_ALARM_IOCTL_TO_TYPE(cmd);
	uint32_t alarm_type_mask = 1U << alarm_type;

	if (alarm_type >= ANDROID_ALARM_TYPE_COUNT)
		return -EINVAL;

	if (ANDROID_ALARM_BASE_CMD(cmd) != ANDROID_ALARM_GET_TIME(0)) {
		if ((file->f_flags & O_ACCMODE) == O_RDONLY)
			return -EPERM;
		if (!file->private_data && cmd != ANDROID_ALARM_SET_RTC) {
			spin_lock_irqsave(&alarm_slock, flags);
			if (alarm_opened) {
				spin_unlock_irqrestore(&alarm_slock, flags);
				return -EBUSY;
			}
			alarm_opened = 1;
			file->private_data = (void *)1;
			spin_unlock_irqrestore(&alarm_slock, flags);
		}
	}

	switch (ANDROID_ALARM_BASE_CMD(cmd)) {
	case ANDROID_ALARM_CLEAR(0):
		spin_lock_irqsave(&alarm_slock, flags);
		ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_IO,
				      "alarm %d clear\\n", alarm_type);
		hrtimer_try_to_cancel(&alarm_timer[alarm_type]);
		if (alarm_pending) {
			alarm_pending &= ~alarm_type_mask;
			if (!alarm_pending && !wait_pending)
				wake_unlock(&alarm_wake_lock);
		}
		alarm_enabled &= ~alarm_type_mask;
		spin_unlock_irqrestore(&alarm_slock, flags);
		break;

	case ANDROID_ALARM_SET_OLD:
	case ANDROID_ALARM_SET_AND_WAIT_OLD:
		if (get_user(new_alarm_time.tv_sec, (int __user *)arg)) {
			rv = -EFAULT;
			goto err1;
		}
		new_alarm_time.tv_nsec = 0;
		goto from_old_alarm_set;

	case ANDROID_ALARM_SET_AND_WAIT(0):
	case ANDROID_ALARM_SET(0):
		if (copy_from_user(&new_alarm_time32, (void __user *)arg,
		    sizeof(new_alarm_time32))) {
			rv = -EFAULT;
			goto err1;
		}
		new_alarm_time.tv_sec = new_alarm_time32.tv_sec;
		new_alarm_time.tv_nsec = new_alarm_time32.tv_nsec;
from_old_alarm_set:
		spin_lock_irqsave(&alarm_slock, flags);
		ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_IO,
			"alarm %d set %lld.%09ld\\n", alarm_type,
			new_alarm_time.tv_sec, new_alarm_time.tv_nsec);
		alarm_time[alarm_type] = new_alarm_time;
		alarm_enabled |= alarm_type_mask;
		alarm_start_hrtimer(alarm_type);
		spin_unlock_irqrestore(&alarm_slock, flags);
		if (ANDROID_ALARM_BASE_CMD(cmd) != ANDROID_ALARM_SET_AND_WAIT(0)
		    && cmd != ANDROID_ALARM_SET_AND_WAIT_OLD)
			break;
		/* fall through */
	case ANDROID_ALARM_WAIT:
		spin_lock_irqsave(&alarm_slock, flags);
		ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_IO, "alarm wait\\n");
		if (!alarm_pending && wait_pending) {
			wake_unlock(&alarm_wake_lock);
			wait_pending = 0;
		}
		spin_unlock_irqrestore(&alarm_slock, flags);
		rv = wait_event_interruptible(alarm_wait_queue, alarm_pending);
		if (rv)
			goto err1;
		spin_lock_irqsave(&alarm_slock, flags);
		rv = alarm_pending;
		wait_pending = 1;
		alarm_pending = 0;
		if (rv & ANDROID_ALARM_WAKEUP_MASK)
			wake_unlock(&alarm_rtc_wake_lock);
		spin_unlock_irqrestore(&alarm_slock, flags);
		break;
	case ANDROID_ALARM_SET_RTC:
		if (copy_from_user(&new_rtc_time32, (void __user *)arg,
		    sizeof(new_rtc_time32))) {
			rv = -EFAULT;
			goto err1;
		}
		new_rtc_time.tv_sec = new_rtc_time32.tv_sec;
		new_rtc_time.tv_nsec = new_rtc_time32.tv_nsec;
		rtc_time64_to_tm(new_rtc_time.tv_sec, &rtc_new_rtc_time);

		ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_IO,
			"set rtc %lld %ld - rtc %02d:%02d:%02d %02d/%02d/%04d\\n",
			new_rtc_time.tv_sec, new_rtc_time.tv_nsec,
			rtc_new_rtc_time.tm_hour, rtc_new_rtc_time.tm_min,
			rtc_new_rtc_time.tm_sec, rtc_new_rtc_time.tm_mon + 1,
			rtc_new_rtc_time.tm_mday,
			rtc_new_rtc_time.tm_year + 1900);

		mutex_lock(&alarm_setrtc_mutex);
		spin_lock_irqsave(&alarm_slock, flags);
		for (i = 0; i < ANDROID_ALARM_SYSTEMTIME; i++)
			hrtimer_try_to_cancel(&alarm_timer[i]);
		ktime_get_real_ts64(&tmp_time);
		elapsed_rtc_delta = timespec64_sub(elapsed_rtc_delta,
					timespec64_sub(tmp_time, new_rtc_time));
		spin_unlock_irqrestore(&alarm_slock, flags);
		rv = do_settimeofday64(&new_rtc_time);
		spin_lock_irqsave(&alarm_slock, flags);
		for (i = 0; i < ANDROID_ALARM_SYSTEMTIME; i++)
			alarm_start_hrtimer(i);
		spin_unlock_irqrestore(&alarm_slock, flags);
		if (rv < 0) {
			ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_ERRORS,
					      "Failed to set time\\n");
			mutex_unlock(&alarm_setrtc_mutex);
			goto err1;
		}
		rv = rtc_set_time(alarm_rtc_dev, &rtc_new_rtc_time);
		spin_lock_irqsave(&alarm_slock, flags);
		alarm_pending |= ANDROID_ALARM_TIME_CHANGE_MASK;
		wake_up(&alarm_wait_queue);
		spin_unlock_irqrestore(&alarm_slock, flags);
		mutex_unlock(&alarm_setrtc_mutex);
		if (rv < 0) {
			ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_ERRORS,
			    "Failed to set RTC, time will be lost on reboot\\n");
			goto err1;
		}
		break;
	case ANDROID_ALARM_GET_TIME(0):
		mutex_lock(&alarm_setrtc_mutex);
		spin_lock_irqsave(&alarm_slock, flags);
		if (alarm_type != ANDROID_ALARM_SYSTEMTIME) {
			ktime_get_real_ts64(&tmp_time);
			if (alarm_type >= ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP)
				tmp_time = timespec64_sub(tmp_time,
							elapsed_rtc_delta);
		} else {
			ktime_get_ts64(&tmp_time);
		}
		spin_unlock_irqrestore(&alarm_slock, flags);
		mutex_unlock(&alarm_setrtc_mutex);
		tmp_time32.tv_sec = (old_time32_t)tmp_time.tv_sec;
		tmp_time32.tv_nsec = tmp_time.tv_nsec;
		if (copy_to_user((void __user *)arg, &tmp_time32,
		    sizeof(tmp_time32))) {
			rv = -EFAULT;
			goto err1;
		}
		break;

	default:
		rv = -EINVAL;
		goto err1;
	}
err1:
	return rv;
}

static int alarm_open(struct inode *inode, struct file *file)
{
	file->private_data = NULL;
	return 0;
}

static int alarm_release(struct inode *inode, struct file *file)
{
	int i;
	unsigned long flags;

	spin_lock_irqsave(&alarm_slock, flags);
	if (file->private_data) {
		for (i = 0; i < ANDROID_ALARM_TYPE_COUNT; i++) {
			uint32_t alarm_type_mask = 1U << i;

			if (alarm_enabled & alarm_type_mask) {
				ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_INFO,
					"alarm_release: clear alarm, "
					"pending %d\\n",
					!!(alarm_pending & alarm_type_mask));
				alarm_enabled &= ~alarm_type_mask;
			}
			spin_unlock_irqrestore(&alarm_slock, flags);
			hrtimer_cancel(&alarm_timer[i]);
			spin_lock_irqsave(&alarm_slock, flags);
		}
		if (alarm_pending | wait_pending) {
			if (alarm_pending)
				ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_INFO,
					"alarm_release: clear pending alarms "
					"%x\\n", alarm_pending);
			wake_unlock(&alarm_wake_lock);
			wait_pending = 0;
			alarm_pending = 0;
		}
		alarm_opened = 0;
	}
	spin_unlock_irqrestore(&alarm_slock, flags);
	return 0;
}

static enum hrtimer_restart alarm_timer_triggered(struct hrtimer *timer)
{
	unsigned long flags;
	enum android_alarm_type alarm_type = (timer - alarm_timer);
	uint32_t alarm_type_mask = 1U << alarm_type;

	ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_INT,
			      "alarm_timer_triggered type %d\\n", alarm_type);
	spin_lock_irqsave(&alarm_slock, flags);
	if (alarm_enabled & alarm_type_mask) {
		wake_lock_timeout(&alarm_wake_lock, 5 * HZ);
		alarm_enabled &= ~alarm_type_mask;
		alarm_pending |= alarm_type_mask;
		wake_up(&alarm_wait_queue);
	}
	spin_unlock_irqrestore(&alarm_slock, flags);
	return HRTIMER_NORESTART;
}

int alarm_suspend(struct platform_device *pdev, pm_message_t state)
{
	int                 err = 0;
	unsigned long       flags;
	struct rtc_wkalrm   rtc_alarm;
	struct rtc_time     rtc_current_rtc_time;
	time64_t            rtc_current_time;
	time64_t            rtc_alarm_time;
	struct timespec64   rtc_current_timespec;
	struct timespec64   rtc_delta;
	struct timespec64   now;
	struct timespec64   elapsed_realtime_alarm_time;

	ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_FLOW,
			      "alarm_suspend(%p, %d)\\n", pdev, state.event);
	spin_lock_irqsave(&alarm_slock, flags);
	if (alarm_pending && !wake_lock_active(&alarm_wake_lock)) {
		ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_INFO,
				      "alarm pending\\n");
		err = -EBUSY;
		spin_unlock_irqrestore(&alarm_slock, flags);
		return err;
	}
	if (alarm_enabled & ANDROID_ALARM_WAKEUP_MASK) {
		spin_unlock_irqrestore(&alarm_slock, flags);
		if (alarm_enabled & ANDROID_ALARM_RTC_WAKEUP_MASK)
			hrtimer_cancel(&alarm_timer[ANDROID_ALARM_RTC_WAKEUP]);
		if (alarm_enabled & ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP_MASK)
			hrtimer_cancel(&alarm_timer[
					ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP]);

		rtc_read_time(alarm_rtc_dev, &rtc_current_rtc_time);
		rtc_current_timespec.tv_nsec = 0;
		rtc_current_timespec.tv_sec =
			rtc_tm_to_time64(&rtc_current_rtc_time);
		/* save_time_delta(&rtc_delta, &rtc_current_timespec) doesn't
		 * exist in mainline anymore -- it was just
		 * "delta = now - rtc", inlined here with a fresh read of
		 * system time instead of depending on the removed helper. */
		ktime_get_real_ts64(&now);
		rtc_delta = timespec64_sub(now, rtc_current_timespec);
		set_normalized_timespec64(&elapsed_realtime_alarm_time,
			alarm_time[ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP]
			.tv_sec + elapsed_rtc_delta.tv_sec,
			alarm_time[ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP]
			.tv_nsec + elapsed_rtc_delta.tv_nsec);
		if ((alarm_enabled & ANDROID_ALARM_RTC_WAKEUP_MASK) &&
		    (!(alarm_enabled &
		       ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP_MASK) ||
		     timespec64_compare(&alarm_time[ANDROID_ALARM_RTC_WAKEUP],
				      &elapsed_realtime_alarm_time) < 0))
			rtc_alarm_time = timespec64_sub(
					alarm_time[ANDROID_ALARM_RTC_WAKEUP],
					rtc_delta).tv_sec;
		else
			rtc_alarm_time = timespec64_sub(
				elapsed_realtime_alarm_time, rtc_delta).tv_sec;
		rtc_time64_to_tm(rtc_alarm_time, &rtc_alarm.time);
		rtc_alarm.enabled = 1;
		rtc_set_alarm(alarm_rtc_dev, &rtc_alarm);
		rtc_read_time(alarm_rtc_dev, &rtc_current_rtc_time);
		rtc_current_time = rtc_tm_to_time64(&rtc_current_rtc_time);
		ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_INFO,
			"rtc alarm set at %lld, now %lld, rtc delta %lld.%09ld\\n",
			rtc_alarm_time, rtc_current_time,
			rtc_delta.tv_sec, rtc_delta.tv_nsec);
		if (rtc_current_time + 1 >= rtc_alarm_time) {
			ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_INFO,
					      "alarm about to go off\\n");
			memset(&rtc_alarm, 0, sizeof(rtc_alarm));
			rtc_alarm.enabled = 0;
			rtc_set_alarm(alarm_rtc_dev, &rtc_alarm);

			spin_lock_irqsave(&alarm_slock, flags);
			wake_lock_timeout(&alarm_rtc_wake_lock, 2 * HZ);
			alarm_start_hrtimer(ANDROID_ALARM_RTC_WAKEUP);
			alarm_start_hrtimer(
				ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP);
			err = -EBUSY;
			spin_unlock_irqrestore(&alarm_slock, flags);
		}
	} else {
		spin_unlock_irqrestore(&alarm_slock, flags);
	}
	return err;
}

int alarm_resume(struct platform_device *pdev)
{
	struct rtc_wkalrm alarm;

	ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_FLOW,
			      "alarm_resume(%p)\\n", pdev);
	if (alarm_enabled & ANDROID_ALARM_WAKEUP_MASK) {
		memset(&alarm, 0, sizeof(alarm));
		alarm.enabled = 0;
		rtc_set_alarm(alarm_rtc_dev, &alarm);
		alarm_start_hrtimer(ANDROID_ALARM_RTC_WAKEUP);
		alarm_start_hrtimer(ANDROID_ALARM_ELAPSED_REALTIME_WAKEUP);
	}
	return 0;
}

static const struct file_operations alarm_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = alarm_ioctl,
	.open = alarm_open,
	.release = alarm_release,
};

static struct miscdevice alarm_device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "alarm",
	.fops = &alarm_fops,
};

static int rtc_alarm_add_device(struct device *dev,
				struct class_interface *class_intf)
{
	int err;
	struct rtc_device *rtc = to_rtc_device(dev);

	mutex_lock(&alarm_setrtc_mutex);

	if (alarm_rtc_dev) {
		err = -EBUSY;
		goto err1;
	}

	err = misc_register(&alarm_device);
	if (err)
		goto err1;
	alarm_platform_dev =
		platform_device_register_simple("alarm", -1, NULL, 0);
	if (IS_ERR(alarm_platform_dev)) {
		err = PTR_ERR(alarm_platform_dev);
		goto err2;
	}
	/* No rtc_irq_register() equivalent in mainline anymore -- see the
	 * port notes at the top of this file. alarm_rtc_dev is set without
	 * it; only the "RTC IRQ just fired, hold a brief wakelock" hardening
	 * is missing, not core alarm functionality. */
	alarm_rtc_dev = rtc;
	mutex_unlock(&alarm_setrtc_mutex);

	ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_INFO, "alarm: parent %p\\n",
			      alarm_platform_dev->dev.power.pm_parent);
	return 0;

err2:
	misc_deregister(&alarm_device);
err1:
	mutex_unlock(&alarm_setrtc_mutex);
	return err;
}

static void rtc_alarm_remove_device(struct device *dev,
				    struct class_interface *class_intf)
{
	if (dev == &alarm_rtc_dev->dev) {
		platform_device_unregister(alarm_platform_dev);
		misc_deregister(&alarm_device);
		alarm_rtc_dev = NULL;
	}
}

static struct class_interface rtc_alarm_interface = {
	.add_dev = &rtc_alarm_add_device,
	.remove_dev = &rtc_alarm_remove_device,
};

static struct platform_driver alarm_driver = {
	.suspend = alarm_suspend,
	.resume = alarm_resume,
	.driver = {
		.name = "alarm"
	}
};

static int __init alarm_late_init(void)
{
	unsigned long   flags;
	struct timespec64 system_time;

	/* this needs to run after the rtc is read at boot */
	spin_lock_irqsave(&alarm_slock, flags);
	/* We read the current rtc and system time so we can later calculate
	 * elapsed realtime to be (boot_systemtime + rtc - boot_rtc) ==
	 * (rtc - (boot_rtc - boot_systemtime))
	 */
	ktime_get_real_ts64(&elapsed_rtc_delta);
	ktime_get_ts64(&system_time);
	elapsed_rtc_delta = timespec64_sub(elapsed_rtc_delta, system_time);
	spin_unlock_irqrestore(&alarm_slock, flags);

	ANDROID_ALARM_DPRINTF(ANDROID_ALARM_PRINT_INFO,
		"alarm_late_init: rtc to elapsed realtime delta %lld.%09ld\\n",
		elapsed_rtc_delta.tv_sec, elapsed_rtc_delta.tv_nsec);
	return 0;
}

static int __init alarm_init(void)
{
	int err;
	int i;

	for (i = 0; i < ANDROID_ALARM_SYSTEMTIME; i++) {
		hrtimer_init(&alarm_timer[i], CLOCK_REALTIME, HRTIMER_MODE_ABS);
		alarm_timer[i].function = alarm_timer_triggered;
	}
	hrtimer_init(&alarm_timer[ANDROID_ALARM_SYSTEMTIME],
		     CLOCK_MONOTONIC, HRTIMER_MODE_ABS);
	alarm_timer[ANDROID_ALARM_SYSTEMTIME].function = alarm_timer_triggered;
	err = platform_driver_register(&alarm_driver);
	if (err < 0)
		goto err1;
	wake_lock_init(&alarm_wake_lock, WAKE_LOCK_SUSPEND, "alarm");
	wake_lock_init(&alarm_rtc_wake_lock, WAKE_LOCK_SUSPEND, "alarm_rtc");
	rtc_alarm_interface.class = rtc_class;
	err = class_interface_register(&rtc_alarm_interface);
	if (err < 0)
		goto err2;

	return 0;

err2:
	wake_lock_destroy(&alarm_rtc_wake_lock);
	wake_lock_destroy(&alarm_wake_lock);
	platform_driver_unregister(&alarm_driver);
err1:
	return err;
}

static void __exit alarm_exit(void)
{
	class_interface_unregister(&rtc_alarm_interface);
	wake_lock_destroy(&alarm_rtc_wake_lock);
	wake_lock_destroy(&alarm_wake_lock);
	platform_driver_unregister(&alarm_driver);
}

late_initcall(alarm_late_init);
module_init(alarm_init);
module_exit(alarm_exit);
"""

os.makedirs(UAPI_DIR, exist_ok=True)
with open(os.path.join(UAPI_DIR, "android_alarm.h"), "w") as f:
    f.write(uapi_h)
with open(f"{A3DS_ROOT}/third_party/linux/include/linux/android_alarm.h", "w") as f:
    f.write(alarm_h)
with open(os.path.join(DRV_RTC, "alarm.c"), "w") as f:
    f.write(alarm_c)

print("OK")
