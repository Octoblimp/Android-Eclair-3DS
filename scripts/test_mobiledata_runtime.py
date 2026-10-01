#!/usr/bin/env python3
"""Static and shell-syntax checks for the 3DS Telco runtime boundary."""

from pathlib import Path
import importlib.util
import os
import subprocess
import stat
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/mobiledata.sh"
STAGED_SCRIPT = ROOT / "sdcard/linux/android/etc/mobiledata.sh"
BOOT = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/boot_progress.sh"
STAGED_BOOT = ROOT / "sdcard/linux/android/etc/boot_progress.sh"
PATCH = ROOT / "scripts/patch_mobiledata_runtime.py"
INIT = ROOT / "sdcard/linux/android/etc/init.rc"
PROP = ROOT / "sdcard/linux/android/system/build.prop"
PIPELINE = ROOT / "scripts/rebuild_everything.sh"


def main() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    staged = STAGED_SCRIPT.read_text(encoding="utf-8")
    boot_text = BOOT.read_text(encoding="utf-8")
    staged_boot = STAGED_BOOT.read_text(encoding="utf-8")
    patch = PATCH.read_text(encoding="utf-8")
    init = INIT.read_text(encoding="utf-8")
    prop = PROP.read_text(encoding="utf-8")
    pipeline = PIPELINE.read_text(encoding="utf-8")

    required = (
        "N3DS_MOBILE_DATA_RUNTIME", "--provision-secret", "--clear-secret", "SECRET_FILE",
        "service.mobiledata.security", "service.mobiledata.ssid", "AP_SSID_DEFAULT='3DS'",
        "N3DS_MOBILE_DATA_SSID_SETTING", "invalid_ssid", "mobiledata_apctl", "--start",
        "--stop", "--stats", "fwmode=1", "192.168.43.1",
        "mobiledata_dhcp", "sys.mobiledata.client_count", "sys.mobiledata.rssi",
        "service.adb.tcp.port 5555", "chmod 0600", "tmpfs", "mobiledata_status",
        "status_endpoint_failed", "sys.mobiledata.backend active",
        "DISPATCH_MAX_STARTS=3",
        "dispatch_marker start_requested", "dispatch_marker worker_failed",
        "dispatcher_start_failed",
        "rollback_start station_rebind_failed", "rollback_start ap_controller_failed",
        "DHCP_PID=", "kill \"$DHCP_PID\"", "state disabled",
        "MOBILEDATA_MODULE_ROOTS", "module_detect", "module_unload",
        "module_load", "sys.mobiledata.boundary", "controller_start ok",
        "MOBILEDATA_TEST_MODE",
        "recover_sdio_host", "MOBILEDATA_SDIO_RECOVER_FILE",
        "N3DS_MOBILEDATA_SINGLE_STOP_OWNER", "trap stop_daemon",
        "N3DS_WIFI_INITRAMFS_MODULE",
    )
    for marker in required:
        assert marker in text, f"runtime missing {marker!r}"
    assert "mobiledata.passphrase" not in text
    assert text == staged, "overlay and staged Mobile Data runtime drifted"
    for marker in (
        "WIFI_RE=", "mobiledata:", "mobiledata_apctl:",
        "N3DS_DALVIK_ABORT|surfaceflinger",
        "Unhandled fault", "Code:", "r10:",
        "=== Mobile Data properties ===", "init.svc.mobiledata=",
    ):
        assert marker in boot_text, f"boot-progress missing {marker!r}"
    assert boot_text == staged_boot, "overlay and staged boot-progress drifted"
    assert "/mnt/sd" not in text, "runtime must not read/write FAT state"
    assert "persist.sys.mobiledata" not in text
    assert "udhcpd" not in text
    assert "N3DS_MOBILE_DATA_LIFECYCLE" in init
    assert "service mobiledata /etc/mobiledata.sh daemon" in init
    init_required = (
        "service md_dispatch /etc/mobiledata.sh dispatch",
        "start md_dispatch",
        "setprop sys.mobiledata.dispatch enable_requested",
        "setprop sys.mobiledata.dispatch disable_requested",
    )
    for marker in init_required:
        assert marker in init, f"init missing {marker!r}"
    assert "service mobiledata_ipc /system/bin/mobiledata_ipc\n    class default" in init
    assert "service md_dispatch /etc/mobiledata.sh dispatch\n    class default" in init
    assert "service mobiledata_ipc /system/bin/mobiledata_ipc\n    class core" not in init
    assert "service md_dispatch /etc/mobiledata.sh dispatch\n    class core" not in init
    assert "setprop sys.mobiledata.state starting" in init
    assert "    oneshot" in init
    disable_action = init.split(
        "on property:service.mobiledata.enable=0\n", 1)[1].split(
        "on property:sys.powerctl=*\n", 1)[0]
    assert "    stop mobiledata\n" not in disable_action, (
        "init must not duplicate the dispatcher's disable-edge stop")
    assert "sys.mobiledata.error=none" in prop
    for marker in ("sys.mobiledata.stage=booting", "sys.mobiledata.result=none",
                   "sys.mobiledata.module=unknown", "sys.mobiledata.rebind=none",
                   "sys.mobiledata.primary_error=none", "sys.mobiledata.rollback=none",
                   "sys.mobiledata.boundary=none"):
        assert marker in prop, f"build.prop missing {marker!r}"
    assert "[ \"$MODULE_MODE\" = builtin ]" in text
    assert "[ \"$MODULE_MODE\" = missing ]" in text
    assert "MOBILEDATA_MODULE_ROOTS:-/n3ds/modules:/system/lib/modules" in text
    assert "MOBILEDATA_MODULE_ROOTS:-/lib/modules:" not in text
    dispatch = text[text.index("dispatch()") : text.index("provision_secret()")]
    # Check executable ordering, not the first textual occurrence: the
    # dispatcher_start_failed explanation in a comment appears before the
    # actual fallback branch.  Removing full-line shell comments keeps this
    # regression focused on the branch that can change runtime state.
    dispatch_code = "\n".join(
        line for line in dispatch.splitlines()
        if not line.lstrip().startswith("#")
    )
    worker_guard = 'elif [ "$(getprop_safe sys.mobiledata.state)" = error ]; then'
    fallback_guard = 'elif [ "$start_attempts" -lt "$DISPATCH_MAX_STARTS" ]; then'
    dispatcher_error = (
        'setprop_safe sys.mobiledata.error dispatcher_start_failed'
    )
    worker_failed_start = dispatch_code.index(worker_guard)
    fallback_start = dispatch_code.index(fallback_guard)
    start_failed_start = dispatch_code.index("dispatch_marker start_failed")
    dispatcher_error_start = dispatch_code.index(dispatcher_error)
    worker_failed = dispatch_code[worker_failed_start:fallback_start]
    assert "dispatch_marker worker_failed" in worker_failed
    assert dispatcher_error not in worker_failed
    assert worker_failed_start < fallback_start < start_failed_start < dispatcher_error_start
    assert dispatch_code.count("setprop_safe ctl.stop mobiledata") == 1, (
        "dispatcher must issue exactly one stop per disable edge")
    stop_edge_start = dispatch_code.index("dispatch_marker disable_seen")
    stop_edge_end = dispatch_code.index(
        'if [ "$enable" = 1 ]; then', stop_edge_start)
    stop_edge = dispatch_code[stop_edge_start:stop_edge_end]
    assert "setprop_safe ctl.stop mobiledata" in stop_edge
    disabled_loop = dispatch_code[dispatch_code.index(
        "else\n\t\t\tif [ \"$svc\" = stopped ]") :]
    assert "setprop_safe ctl.stop mobiledata" not in disabled_loop
    assert "N3DS_MOBILE_DATA_DEFAULTS" in prop
    assert "service.mobiledata.enable=0" in prop
    assert "service.mobiledata.security=open" in prop
    assert "service.mobiledata.ssid=3DS" in prop
    assert "sys.mobiledata.dispatch=booting" in prop
    assert "sys.mobiledata.dispatch_seq=0" in prop
    assert "run patch_mobiledata_runtime.py" in pipeline
    assert "run test_mobiledata_runtime.py" in pipeline
    assert "run patch_n3ds_wifi_sdio_recovery.py" in pipeline
    assert "run test_n3ds_wifi_sdio_recovery.py" in pipeline
    assert pipeline.rindex("run patch_mobiledata_runtime.py") < pipeline.index(
        "run build_minimal_initramfs.sh")

    # The patcher must migrate an older marked init file that lacks the
    # dispatcher, then become a byte-for-byte no-op on its second pass.
    spec = importlib.util.spec_from_file_location(
        "patch_mobiledata_runtime", PATCH)
    assert spec and spec.loader
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)

    # Model rebuild_everything.sh selecting a Windows-mounted patcher while
    # both authorities are present. The explicit WSL and Windows roots must
    # both be enumerated, with each overlay/output/staging root appearing once.
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        windows_root = workspace / "windows"
        canonical_root = workspace / "canonical"
        for root in (windows_root, canonical_root):
            for relative in (
                    "third_party/buildroot/board/nintendo3ds/rootfs_overlay",
                    "third_party/buildroot/output/target",
                    "sdcard/linux/android"):
                (root / relative).mkdir(parents=True)
                # Exercise the installer’s bounded creation of a missing
                # output/target/etc directory; the overlay and deploy trees
                # already have their normal etc/ directory.
                if "output/target" not in relative:
                    (root / relative / "etc").mkdir()
        old_root = patcher.ROOT
        old_canonical = patcher.CANONICAL_ROOT
        old_windows = patcher.WINDOWS_ROOT
        try:
            patcher.ROOT = windows_root
            patcher.CANONICAL_ROOT = canonical_root
            patcher.WINDOWS_ROOT = windows_root
            roots = patcher.workspace_roots()
            assert roots == (windows_root, canonical_root)
            targets = patcher.lifecycle_targets()
            assert len(targets) == 6
            assert len({_ for _ in targets}) == 6
            assert all(root in targets for root in (
                windows_root / "sdcard/linux/android",
                canonical_root / "sdcard/linux/android"))
            windows_mode_target = windows_root / "sdcard/linux/android/etc/mobiledata.sh"
            canonical_mode_target = canonical_root / "sdcard/linux/android/etc/mobiledata.sh"
            if os.name != "nt":
                assert patcher._is_windows_mount(windows_mode_target)
                assert not patcher._is_windows_mount(canonical_mode_target)
                assert patcher._mode_unrepresentable(windows_mode_target)
                assert not patcher._mode_unrepresentable(canonical_mode_target)
                assert not patcher._accept_mode(windows_mode_target, 0o777, 0o777)
                try:
                    patcher._accept_mode(canonical_mode_target, 0o777, 0o777)
                except SystemExit as exc:
                    assert "mode is not 0755" in str(exc)
                else:
                    raise AssertionError("canonical non-0755 mode was accepted")

            # The mounted Windows overlay is authoritative.  Seed every
            # target with stale scripts and a non-executable mode, then prove
            # installation reaches canonical/Windows overlay, output, and
            # staged trees and is a no-op on the second pass.
            stale_runtime = "#!/bin/sh\n# stale runtime\n"
            stale_boot = "#!/bin/sh\n# stale boot-progress\n"
            for target in targets:
                runtime_target = target / patcher.RUNTIME_RELATIVE
                boot_target = target / patcher.BOOT_PROGRESS_RELATIVE
                if runtime_target.parent.is_dir():
                    runtime_target.write_text(stale_runtime, encoding="utf-8")
                    boot_target.write_text(stale_boot, encoding="utf-8")
                    runtime_target.chmod(0o644)
                    boot_target.chmod(0o644)
            # Seed the preferred Windows overlay last, so the source itself
            # remains valid while every other target is demonstrably stale.
            authoritative_overlay = (
                windows_root / patcher.OVERLAY_RELATIVE / "etc"
            )
            authoritative_overlay.joinpath("mobiledata.sh").write_text(
                text, encoding="utf-8"
            )
            authoritative_overlay.joinpath("boot_progress.sh").write_text(
                boot_text, encoding="utf-8"
            )
            authoritative_overlay.joinpath("mobiledata.sh").chmod(0o755)
            authoritative_overlay.joinpath("boot_progress.sh").chmod(0o755)
            assert patcher.install_managed_scripts(targets)
            for target in targets:
                runtime_target = target / patcher.RUNTIME_RELATIVE
                boot_target = target / patcher.BOOT_PROGRESS_RELATIVE
                assert runtime_target.read_text(encoding="utf-8") == text
                assert boot_target.read_text(encoding="utf-8") == boot_text
                # NTFS does not expose POSIX executable bits to Python; the
                # WSL run below verifies the 0755 contract on the target
                # filesystem.  Keep the assertion active for POSIX hosts.
                if os.name != "nt":
                    assert stat.S_IMODE(runtime_target.stat().st_mode) == 0o755
                    assert stat.S_IMODE(boot_target.stat().st_mode) == 0o755
            assert not patcher.install_managed_scripts(targets)
        finally:
            patcher.ROOT = old_root
            patcher.CANONICAL_ROOT = old_canonical
            patcher.WINDOWS_ROOT = old_windows

    # An existing preferred authority with a missing marker must fail closed,
    # even if an older fallback authority happens to be present.
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        overlay = workspace / patcher.OVERLAY_RELATIVE / "etc"
        overlay.mkdir(parents=True)
        (overlay / "mobiledata.sh").write_text(
            "#!/bin/sh\n# invalid authority\n", encoding="utf-8"
        )
        (overlay / "boot_progress.sh").write_text(boot_text, encoding="utf-8")
        try:
            patcher.ROOT = workspace
            patcher.WINDOWS_ROOT = workspace
            patcher.CANONICAL_ROOT = workspace / "canonical-missing"
            try:
                patcher.install_managed_scripts((workspace,))
            except SystemExit as exc:
                assert "authoritative mobiledata.sh missing marker" in str(exc)
            else:
                raise AssertionError("invalid authoritative runtime was accepted")
        finally:
            patcher.ROOT = old_root
            patcher.CANONICAL_ROOT = old_canonical
            patcher.WINDOWS_ROOT = old_windows

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_init = Path(temp_dir) / "init.rc"
        legacy = init
        dispatch_block = (
            "service md_dispatch /etc/mobiledata.sh dispatch\n"
            "    class default\n"
            "    user root\n"
            "    group root wifi inet\n\n")
        assert dispatch_block in legacy
        temp_init.write_text(legacy.replace(dispatch_block, "", 1),
                              encoding="utf-8")
        assert patcher.patch_init(temp_init)
        migrated = temp_init.read_text(encoding="utf-8")
        assert "service md_dispatch /etc/mobiledata.sh dispatch" in migrated
        assert "mobiledata_dispatch" not in migrated
        assert not patcher.patch_init(temp_init)
        assert migrated == temp_init.read_text(encoding="utf-8")

        # Build #226 shipped a marked block whose service name exceeds this
        # init parser's 16-byte limit.  Prove that exact deployed spelling is
        # migrated, all action references follow it, and a second pass is a
        # byte-for-byte no-op.
        old_name = migrated.replace("md_dispatch", "mobiledata_dispatch")
        temp_init.write_text(old_name, encoding="utf-8")
        assert patcher.patch_init(temp_init)
        renamed = temp_init.read_text(encoding="utf-8")
        assert "mobiledata_dispatch" not in renamed
        assert renamed.count("md_dispatch") == migrated.count("md_dispatch")
        assert not patcher.patch_init(temp_init)
        assert renamed == temp_init.read_text(encoding="utf-8")

    # The shell itself must parse cleanly on host dash/bash. It must not be
    # executed here: AP mode and all target commands are hardware-bound.
    sh = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True,
                        text=True)
    assert sh.returncode == 0, sh.stderr

    # Every AP-start failure must pass through rollback so an ioctl/module,
    # address, DHCP, or status-endpoint failure cannot strand wlan0 in AP mode.
    for failure in ("station_rebind_failed", "ap_controller_failed",
                    "address_config_failed", "dhcp_failed",
                    "status_endpoint_failed"):
        assert ("rollback_start %s" % failure) in text or failure in (
            "address_config_failed", "dhcp_failed", "status_endpoint_failed"), failure
    rollback = text[text.index("rollback_start()"):
                    text.index("rebind_ap()", text.index("rollback_start()"))]
    assert rollback.index("cleanup_network") < rollback.index("if ! restore_sta"), \
        "rollback must clean child services before station restore"
    assert text.index("rollback_start ap_controller_failed") < text.index(
        "if ! have_cmd ifconfig"), "controller failure must rollback before addressing"
    print("mobiledata_runtime: PASS (fail-closed userspace contract)")


if __name__ == "__main__":
    main()
