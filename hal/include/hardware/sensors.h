/*
 * Copyright (C) 2008 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/* Vendored verbatim from
 * android.googlesource.com/platform/hardware/libhardware, tag
 * eclair-release, include/hardware/sensors.h -- do not hand-edit,
 * this is the real Eclair HAL ABI. */

#ifndef ANDROID_SENSORS_INTERFACE_H
#define ANDROID_SENSORS_INTERFACE_H

#include <stdint.h>
#include <sys/cdefs.h>
#include <sys/types.h>

#include <hardware/hardware.h>
#include <cutils/native_handle.h>

__BEGIN_DECLS

/**
 * The id of this module
 */
#define SENSORS_HARDWARE_MODULE_ID "sensors"

/**
 * Name of the sensors device to open
 */
#define SENSORS_HARDWARE_CONTROL    "control"
#define SENSORS_HARDWARE_DATA       "data"

/**
 * Handles must be higher than SENSORS_HANDLE_BASE and must be unique.
 * A Handle identifies a given sensors. The handle is used to activate
 * and/or deactivate sensors.
 * In this version of the API there can only be 256 handles.
 */
#define SENSORS_HANDLE_BASE         0
#define SENSORS_HANDLE_BITS         8
#define SENSORS_HANDLE_COUNT        (1<<SENSORS_HANDLE_BITS)


/**
 * Sensor types
 */
#define SENSOR_TYPE_ACCELEROMETER       1
#define SENSOR_TYPE_MAGNETIC_FIELD      2
#define SENSOR_TYPE_ORIENTATION         3
#define SENSOR_TYPE_GYROSCOPE           4
#define SENSOR_TYPE_LIGHT               5
#define SENSOR_TYPE_PRESSURE            6
#define SENSOR_TYPE_TEMPERATURE         7
#define SENSOR_TYPE_PROXIMITY           8

/**
 * Values returned by the accelerometer in various locations in the universe.
 * all values are in SI units (m/s^2)
 */

#define GRAVITY_SUN                (275.0f)
#define GRAVITY_MERCURY            (3.70f)
#define GRAVITY_VENUS              (8.87f)
#define GRAVITY_EARTH              (9.80665f)
#define GRAVITY_MOON               (1.6f)
#define GRAVITY_MARS               (3.71f)
#define GRAVITY_JUPITER            (23.12f)
#define GRAVITY_SATURN             (8.96f)
#define GRAVITY_URANUS             (8.69f)
#define GRAVITY_NEPTUNE            (11.0f)
#define GRAVITY_PLUTO              (0.6f)
#define GRAVITY_DEATH_STAR_I        (0.000000353036145f)
#define GRAVITY_THE_ISLAND          (4.815162342f)

/** Maximum magnetic field on Earth's surface */
#define MAGNETIC_FIELD_EARTH_MAX    (60.0f)

/** Minimum magnetic field on Earth's surface */
#define MAGNETIC_FIELD_EARTH_MIN    (30.0f)


/**
 * status of each sensor
 */

#define SENSOR_STATUS_UNRELIABLE        0
#define SENSOR_STATUS_ACCURACY_LOW      1
#define SENSOR_STATUS_ACCURACY_MEDIUM   2
#define SENSOR_STATUS_ACCURACY_HIGH     3

typedef struct {
    union {
        float v[3];
        struct {
            float x;
            float y;
            float z;
        };
        struct {
            float azimuth;
            float pitch;
            float roll;
        };
    };
    int8_t status;
    uint8_t reserved[3];
} sensors_vec_t;

/**
 * Union of the various types of sensor data
 * that can be returned.
 */
typedef struct {
    /* sensor identifier */
    int   sensor;

    union {
        /* x,y,z values of the given sensor */
        sensors_vec_t  vector;

        /* orientation values are in degrees */
        sensors_vec_t  orientation;

        /* acceleration values are in meter per second per second (m/s^2) */
        sensors_vec_t  acceleration;

        /* magnetic vector values are in micro-Tesla (uT) */
        sensors_vec_t  magnetic;

        /* temperature is in degrees centigrade (Celsius) */
        float          temperature;

        /* distance in centimeters */
        float          distance;

        /* light in SI lux units */
        float          light;
    };

    /* time is in nanosecond */
    int64_t  time;

    uint32_t  reserved;
} sensors_data_t;


struct sensor_t;

/**
 * Every hardware module must have a data structure named HAL_MODULE_INFO_SYM
 * and the fields of this data structure must begin with hw_module_t
 * followed by module specific information.
 */
struct sensors_module_t {
    struct hw_module_t common;

    /**
     * Enumerate all available sensors. The list is returned in "list".
     * @return number of sensors in the list
     */
    int (*get_sensors_list)(struct sensors_module_t* module,
            struct sensor_t const** list);
};

struct sensor_t {
    /* name of this sensors */
    const char*    name;
    /* vendor of the hardware part */
    const char*    vendor;
    /* version of the hardware part + driver. The value of this field is
     * left to the implementation and doesn't have to be monotonically
     * increasing.
     */
    int            version;
    /* handle that identifies this sensors. This handle is used to activate
     * and deactivate this sensor. The value of the handle must be 8 bits
     * in this version of the API.
     */
    int            handle;
    /* this sensor's type. */
    int            type;
    /* maximum range of this sensor's value in SI units */
    float          maxRange;
    /* smallest difference between two values reported by this sensor */
    float          resolution;
    /* rough estimate of this sensor's power consumption in mA */
    float          power;
    /* reserved fields, must be zero */
    void*          reserved[9];
};


/**
 * Every device data structure must begin with hw_device_t
 * followed by module specific public methods and attributes.
 */
struct sensors_control_device_t {
    struct hw_device_t common;

    /**
     * Returns a native_handle_t, which will be the parameter to
     * sensors_data_device_t::open_data().
     * The caller takes ownership of this handle. This is intended to be
     * passed cross processes.
     *
     * @return a native_handle_t if successful, NULL on error
     */
    native_handle_t* (*open_data_source)(struct sensors_control_device_t *dev);

    /**
     * Releases any resources that were created by open_data_source.
     * This call is optional and can be NULL if not implemented
     * by the sensor HAL.
     *
     * @return 0 if successful, < 0 on error
     */
    int (*close_data_source)(struct sensors_control_device_t *dev);

    /** Activate/deactivate one sensor.
     *
     * @param handle is the handle of the sensor to change.
     * @param enabled set to 1 to enable, or 0 to disable the sensor.
     *
     * @return 0 on success, negative errno code otherwise
     */
    int (*activate)(struct sensors_control_device_t *dev,
            int handle, int enabled);

    /**
     * Set the delay between sensor events in ms
     *
     * @return 0 if successful, < 0 on error
     */
    int (*set_delay)(struct sensors_control_device_t *dev, int32_t ms);

    /**
     * Causes sensors_data_device_t.poll() to return -EWOULDBLOCK immediately.
     */
    int (*wake)(struct sensors_control_device_t *dev);
};

struct sensors_data_device_t {
    struct hw_device_t common;

    /**
     * Prepare to read sensor data.
     *
     * This routine does NOT take ownership of the handle
     * and must not close it. Typically this routine would
     * use a duplicate of the nh parameter.
     *
     * @param nh from sensors_control_open.
     *
     * @return 0 if successful, < 0 on error
     */
    int (*data_open)(struct sensors_data_device_t *dev, native_handle_t* nh);

    /**
     * Caller has completed using the sensor data.
     * The caller will not be blocked in sensors_data_poll
     * when this routine is called.
     *
     * @return 0 if successful, < 0 on error
     */
    int (*data_close)(struct sensors_data_device_t *dev);

    /**
     * Return sensor data for one of the enabled sensors.
     *
     * @return sensor handle for the returned data, 0x7FFFFFFF when
     * sensors_control_device_t.wake() is called and -errno on error
     *
     */
    int (*poll)(struct sensors_data_device_t *dev,
            sensors_data_t* data);
};

/** convenience API for opening and closing a device */

static inline int sensors_control_open(const struct hw_module_t* module,
        struct sensors_control_device_t** device) {
    return module->methods->open(module,
            SENSORS_HARDWARE_CONTROL, (struct hw_device_t**)device);
}

static inline int sensors_control_close(struct sensors_control_device_t* device) {
    return device->common.close(&device->common);
}

static inline int sensors_data_open(const struct hw_module_t* module,
        struct sensors_data_device_t** device) {
    return module->methods->open(module,
            SENSORS_HARDWARE_DATA, (struct hw_device_t**)device);
}

static inline int sensors_data_close(struct sensors_data_device_t* device) {
    return device->common.close(&device->common);
}


__END_DECLS

#endif  // ANDROID_SENSORS_INTERFACE_H
