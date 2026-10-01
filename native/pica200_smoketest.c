/* SPDX-License-Identifier: MIT
 * Non-destructive PICA200 bring-up test: submit only GPUREG_FINALIZE and
 * verify that Linux receives the P3D completion IRQ before enabling EGL. */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#include <linux/ctr_pica.h>

int main(int argc, char **argv)
{
    struct ctr_pica_info info;
    struct ctr_pica_alloc alloc;
    struct ctr_pica_alloc output;
    struct ctr_pica_submit submit;
    struct ctr_pica_transfer transfer;
    struct ctr_pica_free release;
    uint32_t *commands;
    int qualify = argc == 2 && strcmp(argv[1], "--qualify") == 0;
    int fd;

    fd = open("/dev/pica200", O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        fprintf(stderr, "PICA200_PROBE open failed: %s\n", strerror(errno));
        return 1;
    }
    memset(&info, 0, sizeof(info));
    if (ioctl(fd, CTR_PICA_IOC_INFO, &info) < 0) {
        fprintf(stderr, "PICA200_PROBE info failed: %s\n", strerror(errno));
        close(fd);
        return 2;
    }
    printf("PICA200_STATUS abi=%u id=%08x seq=%llu ppf_seq=%llu quarantines=%u last=%d qualified=%u stage=%u wedged=%u irq=%u watchdog=%u\n",
           info.abi_version, info.hardware_id,
           (unsigned long long)info.completed_sequence,
           (unsigned long long)info.ppf_completed_sequence,
           info.reset_count, (int)info.last_error, info.qualified,
           info.stage, info.wedged, info.irq_seen, info.watchdog_armed);

    if (!qualify) {
        printf("PICA200_SAFE read-only status; pass --qualify explicitly after Android boots\n");
        close(fd);
        return 0;
    }

    if (ioctl(fd, CTR_PICA_IOC_QUALIFY) < 0) {
        int qualify_errno = errno;

        memset(&info, 0, sizeof(info));
        if (ioctl(fd, CTR_PICA_IOC_INFO, &info) < 0)
            memset(&info, 0, sizeof(info));
        fprintf(stderr, "PICA200_PROBE qualification failed at stage=%u: %s\n",
                info.stage, strerror(qualify_errno));
        fprintf(stderr, "PICA200_PROBE quarantined=%u irq=%u last=%d; reboot before retry\n",
                info.wedged, info.irq_seen, (int)info.last_error);
        close(fd);
        return 2;
    }
    memset(&info, 0, sizeof(info));
    if (ioctl(fd, CTR_PICA_IOC_INFO, &info) < 0) {
        fprintf(stderr, "PICA200_PROBE post-qualification info failed: %s\n",
                strerror(errno));
        close(fd);
        return 2;
    }

    if (!info.qualified) {
        fprintf(stderr, "PICA200_PROBE hardware path not qualified; software fallback active\n");
        close(fd);
        return 2;
    }

    memset(&alloc, 0, sizeof(alloc));
    alloc.size = 4096;
    if (ioctl(fd, CTR_PICA_IOC_ALLOC, &alloc) < 0) {
        fprintf(stderr, "PICA200_PROBE alloc failed: %s\n", strerror(errno));
        close(fd);
        return 3;
    }
    commands = mmap(NULL, alloc.size, PROT_READ | PROT_WRITE, MAP_SHARED,
                    fd, (off_t)alloc.handle * 4096);
    if (commands == MAP_FAILED) {
        fprintf(stderr, "PICA200_PROBE mmap failed: %s\n", strerror(errno));
        close(fd);
        return 4;
    }
    /* Two normal single-write commands make the hardware-required 16 bytes.
     * The validator permits the second FINALIZE solely as alignment padding,
     * matching libctru's GPUCMD_Split behavior. */
    commands[0] = 0x12345678;
    commands[1] = 0x000f0010;
    commands[2] = 0x12345678;
    commands[3] = 0x000f0010;

    memset(&submit, 0, sizeof(submit));
    submit.handle = alloc.handle;
    submit.length = 16;
    submit.timeout_ms = 500;
    if (ioctl(fd, CTR_PICA_IOC_SUBMIT, &submit) < 0) {
        fprintf(stderr, "PICA200_PROBE submit failed: %s\n", strerror(errno));
        munmap(commands, alloc.size);
        close(fd);
        return 5;
    }
    printf("PICA200_PROBE PASS p3d_sequence=%llu gpu_address=%08x\n",
           (unsigned long long)submit.sequence, alloc.gpu_address);

    /* ABI v3 also qualifies a minimal owned-buffer PPF transfer.  RGBA8 to
     * RGBA8 at 64x16 is inside the documented alignment/conversion envelope;
     * neither allocation can alias LCD scanout or arbitrary physical RAM. */
    memset(&output, 0, sizeof(output));
    output.size = 4096;
    if (ioctl(fd, CTR_PICA_IOC_ALLOC, &output) < 0) {
        fprintf(stderr, "PICA200_PROBE PPF output alloc failed: %s\n",
                strerror(errno));
        munmap(commands, alloc.size);
        close(fd);
        return 6;
    }
    memset(&transfer, 0, sizeof(transfer));
    transfer.src_handle = alloc.handle;
    transfer.dst_handle = output.handle;
    transfer.src_width = transfer.dst_width = 64;
    transfer.src_height = transfer.dst_height = 16;
    transfer.src_format = transfer.dst_format = CTR_PICA_FORMAT_RGBA8;
    transfer.timeout_ms = 500;
    if (ioctl(fd, CTR_PICA_IOC_TRANSFER, &transfer) < 0) {
        fprintf(stderr, "PICA200_PROBE PPF transfer failed: %s\n",
                strerror(errno));
        memset(&release, 0, sizeof(release));
        release.handle = output.handle;
        ioctl(fd, CTR_PICA_IOC_FREE, &release);
        munmap(commands, alloc.size);
        close(fd);
        return 7;
    }
    printf("PICA200_PPF PASS sequence=%llu owned-copy=64x16-rgba8\n",
           (unsigned long long)transfer.sequence);
    memset(&release, 0, sizeof(release));
    release.handle = output.handle;
    ioctl(fd, CTR_PICA_IOC_FREE, &release);
    munmap(commands, alloc.size);
    memset(&release, 0, sizeof(release));
    release.handle = alloc.handle;
    ioctl(fd, CTR_PICA_IOC_FREE, &release);
    close(fd);
    return 0;
}
