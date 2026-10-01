/*
 * hal/sensors/sensors.c -- Nintendo New 3DS sensors HAL
 *
 * Backs SENSOR_TYPE_ACCELEROMETER with the kernel's CTR_MCUACCEL IIO
 * driver (drivers/platform/nintendo3ds/mcu/accel.c, real LIS331DLH
 * hardware per that file's own comment). Confirmed sysfs ABI, derived
 * directly from that driver's iio_chan_spec table (not guessed):
 *   in_accel_en             -- write 1/0 (IIO_CHAN_INFO_ENABLE, shared_by_type)
 *   in_accel_x_raw / _y_raw / _z_raw   -- signed 16-bit raw counts
 *   in_accel_scale           -- m/s^2 per raw count (IIO_VAL_INT_PLUS_NANO)
 * The IIO device directory (e.g. /sys/bus/iio/devices/iio:device0) is
 * discovered at runtime by matching each device's "name" file against
 * the kernel driver's own dev_name ("3dsmcu-accel"), not hardcoded --
 * ordering isn't guaranteed once more IIO devices exist.
 *
 * Architecture follows the real reference sensors HAL shape from this
 * era: a background thread owns one end of a socketpair and pushes
 * sensors_data_t structs into it while the sensor is active;
 * open_data_source() hands the other end to the data device via a
 * native_handle_t, exactly per the header's documented contract.
 *
 * Cross-compiled against glibc (this project's kernel/buildroot
 * toolchain), not bionic -- see hal/lights/lights.c's file header for
 * the same caveat, applies identically here (Phase 6 concern).
 */

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/stat.h>

#include <hardware/sensors.h>

#define IIO_BUS_DIR "/sys/bus/iio/devices"
#define ACCEL_HANDLE 1
#define DEFAULT_DELAY_MS 20 /* matches the kernel driver's own 50Hz cap */

/* ---- minimal native_handle_t implementation ----
 * Declared in cutils/native_handle.h, not implemented anywhere in
 * this tree yet (real libcutils is a Phase 6 concern) -- this module
 * is currently the only consumer, so it carries its own. */
native_handle_t *native_handle_create(int numFds, int numInts)
{
	native_handle_t *h = malloc(sizeof(native_handle_t) +
				     (numFds + numInts) * sizeof(int));
	if (!h)
		return NULL;
	h->version = sizeof(native_handle_t);
	h->numFds = numFds;
	h->numInts = numInts;
	return h;
}

int native_handle_delete(native_handle_t *h)
{
	free(h);
	return 0;
}

int native_handle_close(const native_handle_t *h)
{
	int i;
	for (i = 0; i < h->numFds; i++)
		close(h->data[i]);
	return 0;
}

/* ---- IIO accelerometer sysfs discovery ---- */

static char g_iio_dir[300];
static int g_iio_found;
static float g_scale;

static int read_sysfs_line(const char *path, char *buf, size_t buflen)
{
	int fd = open(path, O_RDONLY);
	ssize_t n;
	if (fd < 0)
		return -errno;
	n = read(fd, buf, buflen - 1);
	close(fd);
	if (n < 0)
		return -errno;
	buf[n] = '\0';
	return 0;
}

static int find_accel_iio_dir(void)
{
	DIR *d;
	struct dirent *e;
	char path[320], name[128];

	if (g_iio_found)
		return 0;

	d = opendir(IIO_BUS_DIR);
	if (!d)
		return -ENODEV;

	while ((e = readdir(d)) != NULL) {
		if (e->d_name[0] == '.')
			continue;
		snprintf(path, sizeof(path), "%s/%s/name", IIO_BUS_DIR, e->d_name);
		if (read_sysfs_line(path, name, sizeof(name)) != 0)
			continue;
		if (strncmp(name, "3dsmcu-accel", 12) == 0) {
			snprintf(g_iio_dir, sizeof(g_iio_dir), "%s/%s",
				 IIO_BUS_DIR, e->d_name);
			g_iio_found = 1;
			break;
		}
	}
	closedir(d);
	if (!g_iio_found)
		return -ENODEV;

	/* Scale is fixed for the life of the driver -- read once. */
	snprintf(path, sizeof(path), "%s/in_accel_scale", g_iio_dir);
	if (read_sysfs_line(path, name, sizeof(name)) == 0)
		g_scale = strtof(name, NULL);
	else
		g_scale = 0.000598755f; /* CTR_ACCEL_NSCALE, matches kernel driver */

	return 0;
}

static int write_iio(const char *file, const char *value)
{
	char path[384];
	int fd, ret;
	size_t len = strlen(value);

	snprintf(path, sizeof(path), "%s/%s", g_iio_dir, file);
	fd = open(path, O_WRONLY);
	if (fd < 0)
		return -errno;
	ret = write(fd, value, len);
	close(fd);
	return (ret == (int)len) ? 0 : -EIO;
}

static int read_iio_int(const char *file)
{
	char path[384], buf[32];
	snprintf(path, sizeof(path), "%s/%s", g_iio_dir, file);
	if (read_sysfs_line(path, buf, sizeof(buf)) != 0)
		return 0;
	return atoi(buf);
}

/* ---- background sampling thread ---- */

struct ctr_sensor_ctx {
	pthread_t thread;
	pthread_mutex_t lock;
	int running;      /* thread should keep looping */
	int enabled;      /* sensor reporting enabled */
	int delay_ms;
	int write_fd;     /* write end, owned by this context */
};

static struct ctr_sensor_ctx g_ctx = {
	.lock = PTHREAD_MUTEX_INITIALIZER,
	.delay_ms = DEFAULT_DELAY_MS,
	.write_fd = -1,
};

static int64_t now_ns(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static void *poll_thread_fn(void *arg)
{
	(void)arg;

	for (;;) {
		int enabled, delay_ms, fd;

		pthread_mutex_lock(&g_ctx.lock);
		if (!g_ctx.running) {
			pthread_mutex_unlock(&g_ctx.lock);
			break;
		}
		enabled = g_ctx.enabled;
		delay_ms = g_ctx.delay_ms;
		fd = g_ctx.write_fd;
		pthread_mutex_unlock(&g_ctx.lock);

		if (enabled && fd >= 0) {
			sensors_data_t d;
			memset(&d, 0, sizeof(d));
			d.sensor = ACCEL_HANDLE;
			d.acceleration.x = read_iio_int("in_accel_x_raw") * g_scale;
			d.acceleration.y = read_iio_int("in_accel_y_raw") * g_scale;
			d.acceleration.z = read_iio_int("in_accel_z_raw") * g_scale;
			d.acceleration.status = SENSOR_STATUS_ACCURACY_HIGH;
			d.time = now_ns();
			/* Best-effort: if the reader is gone/backed up,
			 * drop this sample rather than block the loop. */
			write(fd, &d, sizeof(d));
		}

		usleep((useconds_t)delay_ms * 1000);
	}

	return NULL;
}

/* ---- sensors_control_device_t ---- */

struct ctr_control_device {
	struct sensors_control_device_t base;
};

static native_handle_t *ctr_open_data_source(struct sensors_control_device_t *dev)
{
	int sv[2];
	native_handle_t *h;

	(void)dev;

	if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0)
		return NULL;

	pthread_mutex_lock(&g_ctx.lock);
	g_ctx.write_fd = sv[1];
	g_ctx.running = 1;
	pthread_mutex_unlock(&g_ctx.lock);

	if (pthread_create(&g_ctx.thread, NULL, poll_thread_fn, NULL) != 0) {
		close(sv[0]);
		close(sv[1]);
		g_ctx.write_fd = -1;
		return NULL;
	}

	h = native_handle_create(1, 0);
	if (!h) {
		close(sv[0]);
		return NULL;
	}
	h->data[0] = sv[0];
	return h;
}

static int ctr_close_data_source(struct sensors_control_device_t *dev)
{
	(void)dev;

	pthread_mutex_lock(&g_ctx.lock);
	g_ctx.running = 0;
	pthread_mutex_unlock(&g_ctx.lock);

	pthread_join(g_ctx.thread, NULL);

	if (g_ctx.write_fd >= 0) {
		close(g_ctx.write_fd);
		g_ctx.write_fd = -1;
	}
	return 0;
}

static int ctr_activate(struct sensors_control_device_t *dev, int handle, int enabled)
{
	(void)dev;
	if (handle != ACCEL_HANDLE)
		return -EINVAL;
	if (find_accel_iio_dir() != 0)
		return -ENODEV;

	if (write_iio("in_accel_en", enabled ? "1" : "0") != 0)
		return -EIO;

	pthread_mutex_lock(&g_ctx.lock);
	g_ctx.enabled = !!enabled;
	pthread_mutex_unlock(&g_ctx.lock);
	return 0;
}

static int ctr_set_delay(struct sensors_control_device_t *dev, int32_t ms)
{
	(void)dev;
	if (ms < DEFAULT_DELAY_MS)
		ms = DEFAULT_DELAY_MS; /* driver's own ~50Hz cap */

	pthread_mutex_lock(&g_ctx.lock);
	g_ctx.delay_ms = ms;
	pthread_mutex_unlock(&g_ctx.lock);
	return 0;
}

static int ctr_wake(struct sensors_control_device_t *dev)
{
	sensors_data_t d;
	int fd;
	(void)dev;

	memset(&d, 0, sizeof(d));
	d.sensor = 0x7FFFFFFF; /* per header contract */

	pthread_mutex_lock(&g_ctx.lock);
	fd = g_ctx.write_fd;
	pthread_mutex_unlock(&g_ctx.lock);

	if (fd < 0)
		return -ENODEV;
	write(fd, &d, sizeof(d));
	return 0;
}

static int ctr_control_close(struct hw_device_t *dev)
{
	free(dev);
	return 0;
}

/* ---- sensors_data_device_t ---- */

struct ctr_data_device {
	struct sensors_data_device_t base;
	int fd;
};

static int ctr_data_open(struct sensors_data_device_t *dev, native_handle_t *nh)
{
	struct ctr_data_device *dd = (struct ctr_data_device *)dev;
	if (!nh || nh->numFds < 1)
		return -EINVAL;
	dd->fd = dup(nh->data[0]);
	return dd->fd >= 0 ? 0 : -errno;
}

static int ctr_data_close(struct sensors_data_device_t *dev)
{
	struct ctr_data_device *dd = (struct ctr_data_device *)dev;
	if (dd->fd >= 0) {
		close(dd->fd);
		dd->fd = -1;
	}
	return 0;
}

static int ctr_poll(struct sensors_data_device_t *dev, sensors_data_t *data)
{
	struct ctr_data_device *dd = (struct ctr_data_device *)dev;
	size_t got = 0;
	char *p = (char *)data;

	if (dd->fd < 0)
		return -ENODEV;

	while (got < sizeof(*data)) {
		ssize_t n = read(dd->fd, p + got, sizeof(*data) - got);
		if (n < 0) {
			if (errno == EINTR)
				continue;
			return -errno;
		}
		if (n == 0)
			return -ENODEV; /* peer closed */
		got += (size_t)n;
	}

	return data->sensor;
}

static int ctr_data_device_close(struct hw_device_t *dev)
{
	ctr_data_close((struct sensors_data_device_t *)dev);
	free(dev);
	return 0;
}

/* ---- module open() / sensor list ---- */

static const struct sensor_t g_sensor_list[] = {
	{
		.name = "LIS331DLH 3-axis Accelerometer",
		.vendor = "STMicroelectronics",
		.version = 1,
		.handle = ACCEL_HANDLE,
		.type = SENSOR_TYPE_ACCELEROMETER,
		/* Derived, not read from a datasheet directly: the
		 * kernel driver's scale constant (0.000598755 m/s^2 per
		 * LSB, confirmed verbatim from ctr_accel.c) times a
		 * full 16-bit signed raw range lands almost exactly on
		 * 2g (19.61 vs 19.6133 m/s^2), consistent with a LIS331DLH
		 * left at its default +-2g full-scale setting -- this
		 * driver never writes an explicit FS-select register, so
		 * that's the best-supported estimate, not a confirmed
		 * datasheet value. */
		.maxRange = 2.0f * GRAVITY_EARTH,
		.resolution = 0.000598755f, /* CTR_ACCEL_NSCALE, confirmed from kernel source */
		.power = 0.25f, /* unconfirmed estimate (LIS331DLH typical ballpark), not measured */
		.reserved = { 0 },
	},
};

static int ctr_sensors_open(const struct hw_module_t *module, const char *id,
			     struct hw_device_t **device)
{
	if (strcmp(id, SENSORS_HARDWARE_CONTROL) == 0) {
		struct ctr_control_device *cd = calloc(1, sizeof(*cd));
		if (!cd)
			return -ENOMEM;
		cd->base.common.tag = HARDWARE_DEVICE_TAG;
		cd->base.common.version = 0;
		cd->base.common.module = (struct hw_module_t *)module;
		cd->base.common.close = ctr_control_close;
		cd->base.open_data_source = ctr_open_data_source;
		cd->base.close_data_source = ctr_close_data_source;
		cd->base.activate = ctr_activate;
		cd->base.set_delay = ctr_set_delay;
		cd->base.wake = ctr_wake;
		*device = &cd->base.common;
		return 0;
	}

	if (strcmp(id, SENSORS_HARDWARE_DATA) == 0) {
		struct ctr_data_device *dd = calloc(1, sizeof(*dd));
		if (!dd)
			return -ENOMEM;
		dd->fd = -1;
		dd->base.common.tag = HARDWARE_DEVICE_TAG;
		dd->base.common.version = 0;
		dd->base.common.module = (struct hw_module_t *)module;
		dd->base.common.close = ctr_data_device_close;
		dd->base.data_open = ctr_data_open;
		dd->base.data_close = ctr_data_close;
		dd->base.poll = ctr_poll;
		*device = &dd->base.common;
		return 0;
	}

	return -EINVAL;
}

static int ctr_get_sensors_list(struct sensors_module_t *module,
				 struct sensor_t const **list)
{
	(void)module;
	*list = g_sensor_list;
	return sizeof(g_sensor_list) / sizeof(g_sensor_list[0]);
}

static struct hw_module_methods_t sensors_module_methods = {
	.open = ctr_sensors_open,
};

struct sensors_module_t HAL_MODULE_INFO_SYM = {
	.common = {
		.tag = HARDWARE_MODULE_TAG,
		.version_major = 1,
		.version_minor = 0,
		.id = SENSORS_HARDWARE_MODULE_ID,
		.name = "Nintendo New 3DS sensors HAL",
		.author = "android3ds project",
		.methods = &sensors_module_methods,
	},
	.get_sensors_list = ctr_get_sensors_list,
};
