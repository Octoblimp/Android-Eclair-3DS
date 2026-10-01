#!/usr/bin/env python3
"""Static/idempotence contract for adaptive ARM9 SD recovery telemetry."""
from a3ds_paths import A3DS_ROOT

from hashlib import sha256
from pathlib import Path
import subprocess
import sys


ROOT = Path(A3DS_ROOT)
SCRIPT_DIR = Path(__file__).resolve().parent
PATCHER = SCRIPT_DIR / "patch_arm9_sd_adaptive_recovery.py"
SDMMC = ROOT / "third_party/arm9linuxfw/source/hw/sdmmc.c"
SDMMC_H = ROOT / "third_party/arm9linuxfw/include/hw/sdmmc.h"
SDCARD = ROOT / "third_party/arm9linuxfw/source/vdev/sdcard.c"
PXI = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_pxi.c"
PXI_H = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_pxi.h"
BOOT = ROOT / ("third_party/buildroot/board/nintendo3ds/"
               "rootfs_overlay/etc/boot_progress.sh")
REBUILD = SCRIPT_DIR / "rebuild_everything.sh"
VERIFY = SCRIPT_DIR / "verify_release_artifacts.sh"
FILES = (SDMMC, SDMMC_H, SDCARD, PXI, PXI_H)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


before = {path: digest(path) for path in FILES}
subprocess.run([sys.executable, str(PATCHER)], check=True)
after = {path: digest(path) for path in FILES}
if before != after:
    changed = [str(path) for path in FILES if before[path] != after[path]]
    raise SystemExit(f"patch is not idempotent; second pass changed {changed}")

sdmmc = SDMMC.read_text()
header = SDMMC_H.read_text()
sdcard = SDCARD.read_text()
pxi = PXI.read_text()
pxi_h = PXI_H.read_text()
boot = BOOT.read_text()
rebuild = REBUILD.read_text()
verify = VERIFY.read_text()

required_sdmmc = (
    "N3DS_SD_ADAPTIVE_SLOW_CLOCK",
    "ctx->stat0 = sdmmc_read16(REG_SDSTATUS0);",
    "ctx->stat1 = sdmmc_read16(REG_SDSTATUS1);",
    "handleSD.clk = 0x202;",
    "handleSD.clk |= 0x200;",
    "sdmmc_sdcard_recover_slow",
    "sdmmc_sdcard_is_slow",
)
for marker in required_sdmmc:
    assert marker in sdmmc, marker
assert "sdmmc_sdcard_recover_slow" in header

assert sdcard.count("N3DS_SD_ADAPTIVE_RECOVERY") == 1
assert sdcard.count("N3DS_SD_DIAG_CONFIG") == 1
assert sdcard.count("N3DS_SD_SECTOR_READ_FALLBACK") == 1
assert "struct n3ds_sd_diag" in sdcard
assert "u32 seq;" in sdcard and "u32 counts;" in sdcard
assert "max_discard_sectors" not in sdcard
assert "vman_notify_host(vdev, VIRQ_CONFIG);" in sdcard
assert sdcard.index("diag->counts =") < sdcard.index("diag->seq = seq;")

transfer = sdcard[sdcard.index("static int sdmc_transfer("):
                  sdcard.index("/* N3DS_SD_ONE_REQUEST_PER_PASS")]
write_gate = transfer.index("if (write) {")
single_gate = transfer.index("if (sectors <= 1) {")
sector_loop = transfer.index("for (i = 0; i < sectors; i++)")
assert write_gate < single_gate < sector_loop
assert transfer.count("sdmc_recover_slow()") >= 4
assert "N3DS_SD_DIAG_FINAL_IOERR" in transfer
assert "return -1;" in transfer
assert "N3DS_SD_DIAG_SECTOR_READ_RECOVERED" in transfer

assert pxi.count("N3DS_SD_RECOVERY_TELEMETRY") == 1
assert "N3DS_SD_DIAG_CONFIG_OFFSET\t36" in pxi
assert "VIRTIO_ID_BLOCK" in pxi
assert "N3DS_SD_RECOVERY seq=%u sector=%u" in pxi
assert "n3ds_sd_diag_seq" in pxi_h

assert "N3DS_SD_FAILURE_CAPTURE" in boot
for marker in ("N3DS_SD_RECOVERY", "blk_update_request", "FAT-fs"):
    assert marker in boot, marker

patch_pos = rebuild.index("run patch_arm9_sd_adaptive_recovery.py")
fallback_pos = rebuild.index("run patch_arm9_sd_read_fallback.py")
test_pos = rebuild.index("run test_arm9_sd_adaptive_recovery.py")
kernel_pos = rebuild.index("run build_kernel.sh")
arm9_pos = rebuild.index("run build_arm9linuxfw.sh")
assert fallback_pos < patch_pos < test_pos < kernel_pos
assert patch_pos < arm9_pos
for marker in (
    "N3DS_SD_ADAPTIVE_SLOW_CLOCK",
    "N3DS_SD_ADAPTIVE_RECOVERY",
    "N3DS_SD_RECOVERY_TELEMETRY",
    "test_arm9_sd_adaptive_recovery.py",
):
    assert marker in verify, marker

print("PASS: adaptive SD fallback is bounded, observable, and idempotent")
