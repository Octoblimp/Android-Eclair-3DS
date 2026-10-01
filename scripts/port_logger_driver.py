"""Phase 3: port drivers/staging/android/logger.c from android-goldfish-2.6.29
onto this 5.11 tree. Source: $ANDROID3DS_ROOT/scratch/android2629/.

Wire ABI (struct logger_entry, ioctl numbers, LOGGER_LOG_* device names) is
copied verbatim -- this is exactly what real Eclair liblog/logd expects to
open and ioctl(), so it cannot drift even slightly.

Kernel-internal API changes needed for 5.11, all mechanical:
  - .aio_write(iocb, iov, nr_segs, ppos) -> .write_iter(iocb, iov_iter)
    (old AIO read/write methods were removed; write_iter is now the single
    path plain write()/writev()/io_submit() all funnel through)
  - current_kernel_time() [removed] -> ktime_get_real_ts64() + timespec64
  - static __MUTEX_INITIALIZER / __WAIT_QUEUE_HEAD_INITIALIZER struct-literal
    init -> mutex_init()/init_waitqueue_head() at registration time (safer
    against lockdep/init-macro churn across kernel versions than reproducing
    the exact initializer macro expansion)
  - poll() return type/flags -> __poll_t / EPOLLIN etc (POLL* still exist as
    compat aliases, but EPOLL* is the idiomatic 5.11 spelling)
Everything else (ring buffer math, reader list, ioctl set, misc_register)
is unchanged from the original -- this is a mechanical API port, not a
rewrite.
"""
from a3ds_paths import A3DS_ROOT

import os

DRV = f"{A3DS_ROOT}/third_party/linux/drivers/staging/android"

uapi_logger_h = """/* SPDX-License-Identifier: GPL-2.0 */
/* drivers/staging/android/uapi/logger.h
 *
 * Copyright (C) 2007-2008 Google, Inc.
 * Author: Robert Love <rlove@android.com>
 *
 * Ported from android-goldfish-2.6.29 (Eclair-era). This is the wire ABI
 * real Eclair liblog/logd opens /dev/log_{main,events,radio} and ioctl()s
 * against -- struct layout and ioctl numbers must not change.
 */
#ifndef _UAPI_LOGGER_H
#define _UAPI_LOGGER_H

#include <linux/types.h>
#include <linux/ioctl.h>

struct logger_entry {
	__u16		len;	/* length of the payload */
	__u16		__pad;	/* no matter what, we get 2 bytes of padding */
	__s32		pid;	/* generating process's pid */
	__s32		tid;	/* generating process's tid */
	__s32		sec;	/* seconds since Epoch */
	__s32		nsec;	/* nanoseconds */
	char		msg[0];	/* the entry's payload */
};

#define LOGGER_LOG_RADIO	"log_radio"	/* radio-related messages */
#define LOGGER_LOG_EVENTS	"log_events"	/* system/hardware events */
#define LOGGER_LOG_MAIN		"log_main"	/* everything else */

#define LOGGER_ENTRY_MAX_LEN		(4*1024)
#define LOGGER_ENTRY_MAX_PAYLOAD	\\
	(LOGGER_ENTRY_MAX_LEN - sizeof(struct logger_entry))

#define __LOGGERIO	0xAE

#define LOGGER_GET_LOG_BUF_SIZE		_IO(__LOGGERIO, 1) /* size of log */
#define LOGGER_GET_LOG_LEN		_IO(__LOGGERIO, 2) /* used log len */
#define LOGGER_GET_NEXT_ENTRY_LEN	_IO(__LOGGERIO, 3) /* next entry len */
#define LOGGER_FLUSH_LOG		_IO(__LOGGERIO, 4) /* flush log */

#endif /* _UAPI_LOGGER_H */
"""

logger_h = """/* SPDX-License-Identifier: GPL-2.0 */
/* drivers/staging/android/logger.h
 *
 * Copyright (C) 2007-2008 Google, Inc.
 * Author: Robert Love <rlove@android.com>
 */
#ifndef _LINUX_LOGGER_H
#define _LINUX_LOGGER_H

#include "uapi/logger.h"

#endif /* _LINUX_LOGGER_H */
"""

logger_c = """// SPDX-License-Identifier: GPL-2.0
/*
 * drivers/staging/android/logger.c
 *
 * A Logging Subsystem
 *
 * Copyright (C) 2007-2008 Google, Inc.
 *
 * Robert Love <rlove@google.com>
 *
 * Ported from android-goldfish-2.6.29 (real Eclair-era source, not
 * emulator-specific -- this file is hardware agnostic) onto the 5.11 VFS
 * API. See the port notes in port_logger_driver.py for what changed and
 * why; the ring-buffer logic, reader bookkeeping, and ioctl set are
 * unmodified from the original.
 */

#include <linux/sched.h>
#include <linux/module.h>
#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/uaccess.h>
#include <linux/poll.h>
#include <linux/time.h>
#include <linux/uio.h>
#include "logger.h"

#include <asm/ioctls.h>

/*
 * struct logger_log - represents a specific log, such as 'main' or 'radio'
 *
 * This structure lives from early_initcall until the kernel shuts down, so
 * it does not need additional reference counting. The structure is
 * protected by the mutex 'mutex'.
 */
struct logger_log {
	unsigned char		*buffer;/* the ring buffer itself */
	struct miscdevice	misc;	/* misc device representing the log */
	wait_queue_head_t	wq;	/* wait queue for readers */
	struct list_head	readers; /* this log's readers */
	struct mutex		mutex;	/* mutex protecting buffer */
	size_t			w_off;	/* current write head offset */
	size_t			head;	/* new readers start here */
	size_t			size;	/* size of the log */
};

/*
 * struct logger_reader - a logging device open for reading
 *
 * This object lives from open to release, so we don't need additional
 * reference counting. The structure is protected by log->mutex.
 */
struct logger_reader {
	struct logger_log	*log;	/* associated log */
	struct list_head	list;	/* entry in logger_log's list */
	size_t			r_off;	/* current read head offset */
};

/* logger_offset - returns index 'n' into the log via (optimized) modulus */
#define logger_offset(n)	((n) & (log->size - 1))

/*
 * file_get_log - Given a file structure, return the associated log
 *
 * This isn't aesthetic. We have several goals:
 *
 *	1) Need to quickly obtain the associated log during an I/O operation
 *	2) Readers need to maintain state (logger_reader)
 *	3) Writers need to be very fast (open() should be a near no-op)
 *
 * In the reader case, we can trivially go file->logger_reader->logger_log.
 * For a writer, we don't want to maintain a logger_reader, so we just go
 * file->logger_log. Thus what file->private_data points at depends on
 * whether or not the file was opened for reading. This function hides
 * that dirtiness.
 */
static inline struct logger_log *file_get_log(struct file *file)
{
	if (file->f_mode & FMODE_READ) {
		struct logger_reader *reader = file->private_data;
		return reader->log;
	}
	return file->private_data;
}

/*
 * get_entry_len - Grabs the length of the payload of the next entry
 * starting from 'off'.
 *
 * Caller needs to hold log->mutex.
 */
static __u32 get_entry_len(struct logger_log *log, size_t off)
{
	__u16 val;

	switch (log->size - off) {
	case 1:
		memcpy(&val, log->buffer + off, 1);
		memcpy(((char *)&val) + 1, log->buffer, 1);
		break;
	default:
		memcpy(&val, log->buffer + off, 2);
	}

	return sizeof(struct logger_entry) + val;
}

/*
 * do_read_log_to_user - reads exactly 'count' bytes from 'log' into the
 * user-space buffer 'buf'. Returns 'count' on success.
 *
 * Caller must hold log->mutex.
 */
static ssize_t do_read_log_to_user(struct logger_log *log,
				   struct logger_reader *reader,
				   char __user *buf,
				   size_t count)
{
	size_t len;

	/*
	 * We read from the log in two disjoint operations. First, we read
	 * from the current read head offset up to 'count' bytes or to the
	 * end of the log, whichever comes first.
	 */
	len = min(count, log->size - reader->r_off);
	if (copy_to_user(buf, log->buffer + reader->r_off, len))
		return -EFAULT;

	/*
	 * Second, we read any remaining bytes, starting back at the head
	 * of the log.
	 */
	if (count != len)
		if (copy_to_user(buf + len, log->buffer, count - len))
			return -EFAULT;

	reader->r_off = logger_offset(reader->r_off + count);

	return count;
}

/*
 * logger_read - our log's read() method
 *
 * Behavior:
 *
 *	- O_NONBLOCK works
 *	- If there are no log entries to read, blocks until log is written to
 *	- Atomically reads exactly one log entry
 *
 * Optimal read size is LOGGER_ENTRY_MAX_LEN. Will set errno to EINVAL if
 * read buffer is insufficient to hold next entry.
 */
static ssize_t logger_read(struct file *file, char __user *buf,
			   size_t count, loff_t *pos)
{
	struct logger_reader *reader = file->private_data;
	struct logger_log *log = reader->log;
	ssize_t ret;
	DEFINE_WAIT(wait);

start:
	while (1) {
		prepare_to_wait(&log->wq, &wait, TASK_INTERRUPTIBLE);

		mutex_lock(&log->mutex);
		ret = (log->w_off == reader->r_off);
		mutex_unlock(&log->mutex);
		if (!ret)
			break;

		if (file->f_flags & O_NONBLOCK) {
			ret = -EAGAIN;
			break;
		}

		if (signal_pending(current)) {
			ret = -EINTR;
			break;
		}

		schedule();
	}

	finish_wait(&log->wq, &wait);
	if (ret)
		return ret;

	mutex_lock(&log->mutex);

	/* is there still something to read or did we race? */
	if (unlikely(log->w_off == reader->r_off)) {
		mutex_unlock(&log->mutex);
		goto start;
	}

	/* get the size of the next entry */
	ret = get_entry_len(log, reader->r_off);
	if (count < ret) {
		ret = -EINVAL;
		goto out;
	}

	/* get exactly one entry from the log */
	ret = do_read_log_to_user(log, reader, buf, ret);

out:
	mutex_unlock(&log->mutex);

	return ret;
}

/*
 * get_next_entry - return the offset of the first valid entry at least
 * 'len' bytes after 'off'.
 *
 * Caller must hold log->mutex.
 */
static size_t get_next_entry(struct logger_log *log, size_t off, size_t len)
{
	size_t count = 0;

	do {
		size_t nr = get_entry_len(log, off);
		off = logger_offset(off + nr);
		count += nr;
	} while (count < len);

	return off;
}

/*
 * clock_interval - is a < c < b in mod-space? Put another way, does the
 * line from a to b cross c?
 */
static inline int clock_interval(size_t a, size_t b, size_t c)
{
	if (b < a) {
		if (a < c || b >= c)
			return 1;
	} else {
		if (a < c && b >= c)
			return 1;
	}

	return 0;
}

/*
 * fix_up_readers - walk the list of all readers and "fix up" any who were
 * lapped by the writer; also do the same for the default "start head".
 * We do this by "pulling forward" the readers and start head to the first
 * entry after the new write head.
 *
 * The caller needs to hold log->mutex.
 */
static void fix_up_readers(struct logger_log *log, size_t len)
{
	size_t old = log->w_off;
	size_t new = logger_offset(old + len);
	struct logger_reader *reader;

	if (clock_interval(old, new, log->head))
		log->head = get_next_entry(log, log->head, len);

	list_for_each_entry(reader, &log->readers, list)
		if (clock_interval(old, new, reader->r_off))
			reader->r_off = get_next_entry(log, reader->r_off, len);
}

/*
 * do_write_log - writes 'len' bytes from 'buf' to 'log'
 *
 * The caller needs to hold log->mutex.
 */
static void do_write_log(struct logger_log *log, const void *buf, size_t count)
{
	size_t len;

	len = min(count, log->size - log->w_off);
	memcpy(log->buffer + log->w_off, buf, len);

	if (count != len)
		memcpy(log->buffer, buf + len, count - len);

	log->w_off = logger_offset(log->w_off + count);
}

/*
 * do_write_log_from_iter - writes 'count' bytes from the iov_iter 'from'
 * to 'log', wrapping at the end of the ring buffer exactly like
 * do_write_log/do_read_log_to_user do.
 *
 * The caller needs to hold log->mutex.
 *
 * Returns 'count' on success, negative error code on failure. This
 * replaces the original do_write_log_from_user(): copy_from_iter() works
 * against both user- and kernel-space iov_iters, and a single iov_iter
 * already flattens whatever iovec/UIO segments the caller passed, so the
 * original's explicit "while (nr_segs-- > 0)" loop in logger_aio_write()
 * is no longer needed -- iov_iter_count()/copy_from_iter() do that
 * bookkeeping internally.
 */
static ssize_t do_write_log_from_iter(struct logger_log *log,
				      struct iov_iter *from, size_t count)
{
	size_t len;

	len = min(count, log->size - log->w_off);
	if (len && copy_from_iter(log->buffer + log->w_off, len, from) != len)
		return -EFAULT;

	if (count != len)
		if (copy_from_iter(log->buffer, count - len, from) != count - len)
			return -EFAULT;

	log->w_off = logger_offset(log->w_off + count);

	return count;
}

/*
 * logger_write_iter - our write method, implementing support for write(),
 * writev(), pwritev(), and io_submit(). Writes are our fast path, and we
 * try to optimize them above all else.
 *
 * This is the 5.11 equivalent of the original logger_aio_write(): the old
 * .aio_write(iocb, iov, nr_segs, ppos) file_operations member was removed
 * when the kernel unified all write paths onto iov_iter; plain write()
 * still reaches this via the generic new_sync_write() path, so leaving
 * .write NULL and providing only .write_iter is the correct 1:1 port.
 */
static ssize_t logger_write_iter(struct kiocb *iocb, struct iov_iter *from)
{
	struct logger_log *log = file_get_log(iocb->ki_filp);
	size_t orig = log->w_off;
	struct logger_entry header;
	struct timespec64 now;
	ssize_t ret;

	ktime_get_real_ts64(&now);

	header.pid = current->tgid;
	header.tid = current->pid;
	header.sec = (__s32)now.tv_sec;
	header.nsec = (__s32)now.tv_nsec;
	header.len = min_t(size_t, iov_iter_count(from), LOGGER_ENTRY_MAX_PAYLOAD);

	/* null writes succeed, return zero */
	if (unlikely(!header.len))
		return 0;

	mutex_lock(&log->mutex);

	/*
	 * Fix up any readers, pulling them forward to the first readable
	 * entry after (what will be) the new write offset. We do this now
	 * because if we partially fail, we can end up with clobbered log
	 * entries that encroach on readable buffer.
	 */
	fix_up_readers(log, sizeof(struct logger_entry) + header.len);

	do_write_log(log, &header, sizeof(struct logger_entry));

	ret = do_write_log_from_iter(log, from, header.len);
	if (unlikely(ret < 0)) {
		log->w_off = orig;
		mutex_unlock(&log->mutex);
		return ret;
	}

	mutex_unlock(&log->mutex);

	/* wake up any blocked readers */
	wake_up_interruptible(&log->wq);

	return ret;
}

static struct logger_log *get_log_from_minor(int minor);

/*
 * logger_open - the log's open() file operation
 *
 * Note how near a no-op this is in the write-only case. Keep it that way!
 */
static int logger_open(struct inode *inode, struct file *file)
{
	struct logger_log *log;
	int ret;

	ret = nonseekable_open(inode, file);
	if (ret)
		return ret;

	log = get_log_from_minor(MINOR(inode->i_rdev));
	if (!log)
		return -ENODEV;

	if (file->f_mode & FMODE_READ) {
		struct logger_reader *reader;

		reader = kmalloc(sizeof(struct logger_reader), GFP_KERNEL);
		if (!reader)
			return -ENOMEM;

		reader->log = log;
		INIT_LIST_HEAD(&reader->list);

		mutex_lock(&log->mutex);
		reader->r_off = log->head;
		list_add_tail(&reader->list, &log->readers);
		mutex_unlock(&log->mutex);

		file->private_data = reader;
	} else {
		file->private_data = log;
	}

	return 0;
}

/*
 * logger_release - the log's release file operation
 *
 * Note this is a total no-op in the write-only case. Keep it that way!
 */
static int logger_release(struct inode *ignored, struct file *file)
{
	if (file->f_mode & FMODE_READ) {
		struct logger_reader *reader = file->private_data;

		list_del(&reader->list);
		kfree(reader);
	}

	return 0;
}

/*
 * logger_poll - the log's poll file operation, for poll/select/epoll
 *
 * Note we always return EPOLLOUT, because you can always write() to the
 * log. Note also that, strictly speaking, a return value of EPOLLIN does
 * not guarantee that the log is readable without blocking, as there is a
 * small chance that the writer can lap the reader in the interim between
 * poll() returning and the read() request.
 */
static __poll_t logger_poll(struct file *file, poll_table *wait)
{
	struct logger_reader *reader;
	struct logger_log *log;
	__poll_t ret = EPOLLOUT | EPOLLWRNORM;

	if (!(file->f_mode & FMODE_READ))
		return ret;

	reader = file->private_data;
	log = reader->log;

	poll_wait(file, &log->wq, wait);

	mutex_lock(&log->mutex);
	if (log->w_off != reader->r_off)
		ret |= EPOLLIN | EPOLLRDNORM;
	mutex_unlock(&log->mutex);

	return ret;
}

static long logger_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct logger_log *log = file_get_log(file);
	struct logger_reader *reader;
	long ret = -ENOTTY;

	mutex_lock(&log->mutex);

	switch (cmd) {
	case LOGGER_GET_LOG_BUF_SIZE:
		ret = log->size;
		break;
	case LOGGER_GET_LOG_LEN:
		if (!(file->f_mode & FMODE_READ)) {
			ret = -EBADF;
			break;
		}
		reader = file->private_data;
		if (log->w_off >= reader->r_off)
			ret = log->w_off - reader->r_off;
		else
			ret = (log->size - reader->r_off) + log->w_off;
		break;
	case LOGGER_GET_NEXT_ENTRY_LEN:
		if (!(file->f_mode & FMODE_READ)) {
			ret = -EBADF;
			break;
		}
		reader = file->private_data;
		if (log->w_off != reader->r_off)
			ret = get_entry_len(log, reader->r_off);
		else
			ret = 0;
		break;
	case LOGGER_FLUSH_LOG:
		if (!(file->f_mode & FMODE_WRITE)) {
			ret = -EBADF;
			break;
		}
		list_for_each_entry(reader, &log->readers, list)
			reader->r_off = log->w_off;
		log->head = log->w_off;
		ret = 0;
		break;
	}

	mutex_unlock(&log->mutex);

	return ret;
}

static const struct file_operations logger_fops = {
	.owner = THIS_MODULE,
	.read = logger_read,
	.write_iter = logger_write_iter,
	.poll = logger_poll,
	.unlocked_ioctl = logger_ioctl,
	.compat_ioctl = logger_ioctl,
	.open = logger_open,
	.release = logger_release,
	.llseek = noop_llseek,
};

/*
 * Defines a log structure with name 'NAME' and a size of 'SIZE' bytes,
 * which must be a power of two, greater than LOGGER_ENTRY_MAX_LEN, and
 * less than LONG_MAX minus LOGGER_ENTRY_MAX_LEN.
 *
 * wq/readers/mutex are no longer initialized in this static struct literal
 * (the raw __WAIT_QUEUE_HEAD_INITIALIZER/__MUTEX_INITIALIZER expansions
 * have shifted across kernel versions, most recently for lockdep's
 * per-instance class-key handling) -- init_log() below calls
 * init_waitqueue_head()/mutex_init() instead, which is equivalent and
 * doesn't depend on reproducing those macros' exact current expansion.
 */
#define DEFINE_LOGGER_DEVICE(VAR, NAME, SIZE) \\
static unsigned char _buf_ ## VAR[SIZE]; \\
static struct logger_log VAR = { \\
	.buffer = _buf_ ## VAR, \\
	.misc = { \\
		.minor = MISC_DYNAMIC_MINOR, \\
		.name = NAME, \\
		.fops = &logger_fops, \\
		.parent = NULL, \\
	}, \\
	.readers = LIST_HEAD_INIT(VAR .readers), \\
	.w_off = 0, \\
	.head = 0, \\
	.size = SIZE, \\
}

DEFINE_LOGGER_DEVICE(log_main, LOGGER_LOG_MAIN, 64*1024);
DEFINE_LOGGER_DEVICE(log_events, LOGGER_LOG_EVENTS, 256*1024);
DEFINE_LOGGER_DEVICE(log_radio, LOGGER_LOG_RADIO, 64*1024);

static struct logger_log *get_log_from_minor(int minor)
{
	if (log_main.misc.minor == minor)
		return &log_main;
	if (log_events.misc.minor == minor)
		return &log_events;
	if (log_radio.misc.minor == minor)
		return &log_radio;
	return NULL;
}

static int __init init_log(struct logger_log *log)
{
	int ret;

	init_waitqueue_head(&log->wq);
	mutex_init(&log->mutex);

	ret = misc_register(&log->misc);
	if (unlikely(ret)) {
		printk(KERN_ERR "logger: failed to register misc "
		       "device for log '%s'!\\n", log->misc.name);
		return ret;
	}

	printk(KERN_INFO "logger: created %luK log '%s'\\n",
	       (unsigned long)log->size >> 10, log->misc.name);

	return 0;
}

static int __init logger_init(void)
{
	int ret;

	ret = init_log(&log_main);
	if (unlikely(ret))
		goto out;

	ret = init_log(&log_events);
	if (unlikely(ret))
		goto out;

	ret = init_log(&log_radio);
	if (unlikely(ret))
		goto out;

out:
	return ret;
}
device_initcall(logger_init);
"""

with open(os.path.join(DRV, "uapi", "logger.h"), "w") as f:
    f.write(uapi_logger_h)
with open(os.path.join(DRV, "logger.h"), "w") as f:
    f.write(logger_h)
with open(os.path.join(DRV, "logger.c"), "w") as f:
    f.write(logger_c)

# Kconfig: add LOGGER option
kconfig_path = os.path.join(DRV, "Kconfig")
with open(kconfig_path) as f:
    kconfig = f.read()

old_kconfig = """config ASHMEM
	bool "Enable the Anonymous Shared Memory Subsystem"
	depends on SHMEM
	help
	  The ashmem subsystem is a new shared memory allocator, similar to
	  POSIX SHM but with different behavior and sporting a simpler
	  file-based API.

	  It is, in theory, a good memory allocator for low-memory devices,
	  because it can discard shared memory units when under memory pressure.

endif # if ANDROID"""

assert old_kconfig in kconfig, "ashmem Kconfig block not found verbatim"

new_kconfig = """config ASHMEM
	bool "Enable the Anonymous Shared Memory Subsystem"
	depends on SHMEM
	help
	  The ashmem subsystem is a new shared memory allocator, similar to
	  POSIX SHM but with different behavior and sporting a simpler
	  file-based API.

	  It is, in theory, a good memory allocator for low-memory devices,
	  because it can discard shared memory units when under memory pressure.

config LOGGER
	bool "Android log driver"
	default y
	help
	  This adds support for system-wide logging using four log buffers:
	  main, events, radio, and system. Real AOSP liblog/logd open
	  /dev/log_{main,events,radio} directly and read/write/ioctl() them
	  in a fixed binary format (struct logger_entry) -- ported from the
	  Eclair-era android-goldfish-2.6.29 driver of the same name.

endif # if ANDROID"""

kconfig = kconfig.replace(old_kconfig, new_kconfig)
with open(kconfig_path, "w") as f:
    f.write(kconfig)

# Makefile: add logger.o
makefile_path = os.path.join(DRV, "Makefile")
with open(makefile_path) as f:
    makefile = f.read()

old_makefile = "obj-$(CONFIG_ASHMEM)			+= ashmem.o\n"
assert old_makefile in makefile, "ashmem Makefile line not found verbatim"
makefile = makefile.replace(old_makefile, old_makefile + "obj-$(CONFIG_LOGGER)			+= logger.o\n")
with open(makefile_path, "w") as f:
    f.write(makefile)

print("OK")
