#include <pthread.h>
#include <stdint.h>
#include <stdio.h>


extern void android_atomic_write(int32_t, volatile int32_t *);
extern int32_t android_atomic_inc(volatile int32_t *);
extern int32_t android_atomic_dec(volatile int32_t *);
extern int32_t android_atomic_add(int32_t, volatile int32_t *);
extern int32_t android_atomic_and(int32_t, volatile int32_t *);
extern int32_t android_atomic_or(int32_t, volatile int32_t *);
extern int32_t android_atomic_swap(int32_t, volatile int32_t *);
extern int android_atomic_cmpxchg(int32_t, int32_t, volatile int32_t *);

#define THREADS 4
#define ITERATIONS 100000
#define LOCK_FLAG ((int32_t)0x80000000)

static volatile int32_t counter;

static void *increment_worker(void *unused)
{
    int i;
    (void)unused;
    for (i = 0; i < ITERATIONS; ++i)
        android_atomic_inc(&counter);
    return NULL;
}

static int check_interface_cache_release(void)
{
    volatile int32_t version = 0;
    int i;

    for (i = 0; i < ITERATIONS; ++i) {
        int32_t first = version;
        if (android_atomic_cmpxchg(first, first | LOCK_FLAG, &version) != 0)
            return 20;
        version++;
        version++;
        if (android_atomic_cmpxchg((first + 2) | LOCK_FLAG,
                                   first + 2, &version) != 0)
            return 21;
    }
    return version == ITERATIONS * 2 ? 0 : 22;
}

int main(void)
{
    pthread_t threads[THREADS];
    volatile int32_t value = 0;
    int i;
    int rc;

    android_atomic_write(7, &value);
    if (value != 7 || android_atomic_swap(9, &value) != 7 || value != 9)
        return 1;
    if (android_atomic_add(3, &value) != 9 || value != 12)
        return 2;
    if (android_atomic_or(3, &value) != 12 || value != 15)
        return 3;
    if (android_atomic_and(7, &value) != 15 || value != 7)
        return 4;
    if (android_atomic_inc(&value) != 7 || value != 8)
        return 5;
    if (android_atomic_dec(&value) != 8 || value != 7)
        return 6;
    if (android_atomic_cmpxchg(7, 11, &value) != 0 || value != 11)
        return 7;
    if (android_atomic_cmpxchg(7, 13, &value) == 0 || value != 11)
        return 8;

    rc = check_interface_cache_release();
    if (rc != 0)
        return rc;

    android_atomic_write(0, &counter);
    for (i = 0; i < THREADS; ++i) {
        if (pthread_create(&threads[i], NULL, increment_worker, NULL) != 0)
            return 30;
    }
    for (i = 0; i < THREADS; ++i) {
        if (pthread_join(threads[i], NULL) != 0)
            return 31;
    }
    if (counter != THREADS * ITERATIONS)
        return 32;

    printf("PASS: ARMv6 atomic ABI, cache release, and 4-thread stress (%d)\n",
           counter);
    return 0;
}
