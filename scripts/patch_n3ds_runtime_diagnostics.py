#!/usr/bin/env python3
"""Keep useful late-boot evidence without continuously stressing FAT/PXI."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(A3DS_ROOT)
PROGRESS = ROOT / ("third_party/buildroot/board/nintendo3ds/"
                   "rootfs_overlay/etc/boot_progress.sh")

text = PROGRESS.read_text()
if "N3DS_PICA_AND_BOUNDED_DIAGNOSTICS" not in text:
    text = text.replace(
        "INTERVAL=15\n",
        "# N3DS_PICA_AND_BOUNDED_DIAGNOSTICS: the latest hardware run began\n"
        "# returning virtio/FAT write errors after 183 seconds while the old\n"
        "# logger rewrote this file forever. Thirty-second snapshots for ten\n"
        "# minutes preserve evidence without permanent SD traffic.\n"
        "INTERVAL=30\nMAX_SNAPSHOTS=20\n", 1)
    text = text.replace(
        "while true; do\n",
        "snapshot_count=0\nwhile [ $snapshot_count -lt $MAX_SNAPSHOTS ]; do\n", 1)
    text = text.replace(
        "\t\techo \"=== ps ===\"; ps\n",
        "\t\techo \"=== ps ===\"; ps\n"
        "\t\techo \"=== PICA200 ===\"\n"
        "\t\techo \"device: $(ls -l /dev/pica200 2>&1)\"\n"
        "\t\tgrep -iE 'pica|P3D|PPF|PSC' /proc/interrupts 2>/dev/null\n"
        "\t\techo \"$snap\" | grep -iE 'ctr-pica|PICA200_PROBE'\n", 1)
    text = text.replace(
        "\tsleep \"$INTERVAL\"\ndone\n",
        "\tsnapshot_count=$((snapshot_count + 1))\n"
        "\tsleep \"$INTERVAL\"\n"
        "done\n"
        "kmsg \"bounded diagnostics complete after $snapshot_count snapshots\"\n", 1)
if "N3DS_SD_FAILURE_CAPTURE" not in text:
    old = ('echo "$snap" | grep -E "N3DS_DALVIK_ABORT|surfaceflinger|'
           'Unhandled fault|Code:|r10:|PC is at|LR is at|pc :|lr :|Unable to '
           "handle|Internal error|unhandled fatal signal|Comm:|process '.*' "
           '(exited|killing)" \\\n')
    new = ('# N3DS_SD_FAILURE_CAPTURE: keep the narrow transport evidence in the '
           'small crash file too.\n'
           'echo "$snap" | grep -E "N3DS_SD_RECOVERY|blk_update_request|I/O '
           'error, dev vda|FAT-fs|N3DS_DALVIK_ABORT|surfaceflinger|Unhandled '
           'fault|Code:|r10:|PC is at|LR is at|pc :|lr :|Unable to handle|'
           "Internal error|unhandled fatal signal|Comm:|process '.*' "
           '(exited|killing)" \\\n')
    if text.count(old) != 1:
        raise SystemExit("SD failure capture anchor missing or duplicated")
    text = text.replace(old, new, 1)
if text.count("N3DS_PICA_AND_BOUNDED_DIAGNOSTICS") != 1:
    raise SystemExit("runtime diagnostics marker missing or duplicated")
if text.count("N3DS_SD_FAILURE_CAPTURE") != 1:
    raise SystemExit("SD failure capture marker missing or duplicated")
PROGRESS.write_text(text)
print("patch_n3ds_runtime_diagnostics: PICA status + bounded FAT/SD evidence")
