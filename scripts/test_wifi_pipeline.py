#!/usr/bin/env python3
"""Guard the clean rebuild's Wi-Fi/FAT safety patch ordering.

The release verifier checks the patched kernel and WPA sources, but cannot
detect a rebuild script that silently stopped applying those patchers.  Keep
the dependency order executable as a small host-side regression test.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


_file_path = Path(__file__).resolve()
ROOT = _file_path.parents[1]
if "/mnt/c/" in str(_file_path):
    ROOT = Path(A3DS_ROOT)
BUILD = (ROOT / "scripts/rebuild_everything.sh").read_text()
VERIFY = (ROOT / "scripts/verify_release_artifacts.sh").read_text()

EXPECTED = (
    "patch_update_safe_prefs.py",
    "patch_arm9_sd_recovery.py",
    "patch_arm9_pxi_fairness.py",
    "patch_ctr_sdhc_trace_control.py",
    "patch_wifi_scan_ie_capability.py",
    "patch_wifi_bss_channel_guard.py",
    "patch_wifi_irq_panic_recovery.py",
    "patch_ar6014_2ghz_scan.py",
    "patch_ar6014_remove_ram_harvest.py",
    "patch_ar6014_association.py",
    "patch_ar6014_direct_reconnect.py",
    "patch_ar6014_nwm_keepalive.py",
    "patch_ar6014_connect_ctrl_flags_sweep.py",
    "patch_ar6014_nwm_host_wpa.py",
    "patch_ar6014_nwm_wmi_header.py",
    "patch_ar6014_nwm_data_header.py",
    "patch_ar6014_nwm_ready_layout.py",
    "patch_ar6014_nwm_channel_table.py",
    "patch_ar6014_nwm_connection_scan.py",
    "patch_ar6014_discovery_connect_split.py",
    "patch_wpa_remove_scan_harvest_timeout.py",
    "patch_wpa_remembered_ranking.py",
    "patch_wpa_remembered_discovery.py",
    "patch_wpa_scan_security_integrity.py",
    "patch_settings_wifi_resilience.py",
    "patch_settings_wifi_security.py",
    "patch_settings_wifi_remembered_profile.py",
)


def run_position(script: str) -> int:
    line = f"run {script}"
    assert BUILD.count(line) == 1, f"expected one build hook for {script}"
    return BUILD.index(line)


positions = {script: run_position(script) for script in EXPECTED}
assert list(sorted(positions, key=positions.get)) == list(EXPECTED)

for patcher, regression in (
    ("patch_ctr_sdhc_trace_control.py", "test_ctr_sdhc_trace_control.py"),
    ("patch_ar6014_nwm_channel_table.py", "test_ar6014_nwm_channel_table.py"),
    ("patch_ar6014_nwm_connection_scan.py", "test_ar6014_nwm_connection_scan.py"),
    ("patch_ar6014_discovery_connect_split.py", "test_ar6014_discovery_connect_split.py"),
    ("patch_ar6014_nwm_data_header.py", "test_ar6014_nwm_data_header.py"),
):
    assert BUILD.count(f"run {regression}") == 1
    assert BUILD.index(f"run {regression}") > positions[patcher]
    assert patcher in VERIFY
    assert regression in VERIFY

# The generated WPA package patches must be consumed by a clean Buildroot
# package rebuild before build_libhardware reads wpa_ctrl.c and before the
# minimal initramfs snapshots usr/sbin/wpa_supplicant.  Source/patch greps
# alone cannot detect a stale extracted package or stale staged binary.
wifi_rebuild = "rebuild_buildroot_wifi.sh"
assert BUILD.count(f"run {wifi_rebuild}") == 1
wifi_rebuild_pos = BUILD.index(f"run {wifi_rebuild}")
assert wifi_rebuild_pos > positions["patch_wpa_scan_security_integrity.py"]
assert wifi_rebuild_pos < BUILD.index("run rebuild_native_stack.sh")
assert wifi_rebuild_pos < BUILD.index("run build_minimal_initramfs.sh")

# The legacy AR6014 driver owns the netdev ioctl callback.  The retired
# StreetPass probe patch must stay out of the clean pipeline, and the focused
# source contract must run after all AR6014 patchers have completed.
assert "run patch_ar6014_streetpass_probe.py" not in BUILD
repair_script = "repair_ar6014_streetpass_ioctl.py"
assert BUILD.count(f"run {repair_script}") == 1
repair_pos = BUILD.index(f"run {repair_script}")
assert repair_pos > positions["patch_ar6014_nwm_ready_layout.py"]
ioctl_test = "test_ar6014_ioctl_contract.py"
assert BUILD.count(f"run {ioctl_test}") == 1
ioctl_test_pos = BUILD.index(f"run {ioctl_test}")
assert ioctl_test_pos > repair_pos
assert ioctl_test_pos < wifi_rebuild_pos
ioctl_test_source = (ROOT / "scripts" / ioctl_test).read_text()
for marker in ("ndo_do_ioctl", "STREETPASS_PROBE_ABI"):
    assert marker in ioctl_test_source

# Station scan ownership must be part of every clean rebuild.  The framework
# guard runs after the existing scan-policy patch and its focused contract
# runs after the source patch, so a stale framework/JNI control path cannot
# silently return to AP_SCAN=2 during association.
station_guard = "patch_wifi_station_scan_guard.py"
station_guard_test = "test_wifi_station_scan_guard.py"
deferred_guard = "patch_wifi_deferred_disconnect.py"
deferred_guard_test = "test_wifi_deferred_disconnect.py"
assert BUILD.count(f"run {station_guard}") == 1
assert BUILD.count(f"run {station_guard_test}") == 1
assert BUILD.count(f"run {deferred_guard}") == 1
assert BUILD.count(f"run {deferred_guard_test}") == 1
station_guard_pos = BUILD.index(f"run {station_guard}")
station_guard_test_pos = BUILD.index(f"run {station_guard_test}")
deferred_guard_pos = BUILD.index(f"run {deferred_guard}")
deferred_guard_test_pos = BUILD.index(f"run {deferred_guard_test}")
assert station_guard_pos > positions["patch_settings_wifi_security.py"]
assert deferred_guard_pos > positions["patch_settings_wifi_security.py"]
remembered_profile_test = "test_settings_wifi_remembered_profile.py"
assert BUILD.count(f"run {remembered_profile_test}") == 1
remembered_profile_test_pos = BUILD.index(f"run {remembered_profile_test}")
assert remembered_profile_test_pos > positions["patch_settings_wifi_remembered_profile.py"]
assert deferred_guard_pos < station_guard_pos
assert deferred_guard_test_pos > deferred_guard_pos
assert station_guard_test_pos > station_guard_pos
assert deferred_guard_test_pos < BUILD.index("run rebuild_native_stack.sh")
assert station_guard_test_pos < BUILD.index("run rebuild_native_stack.sh")

wifi_script = (ROOT / "scripts" / wifi_rebuild).read_text()
assert "wpa_supplicant-dirclean" in wifi_script
assert 'make -C "$BUILDROOT" wpa_supplicant' in wifi_script
for marker in (
    "N3DS-PRIVACY",
    "N3DS-WPA-RAW",
    "N3DS-RSN-RAW",
    "N3DS-SECURITY-UNKNOWN",
):
    assert marker in wifi_script

assert "cpio -i --to-stdout usr/sbin/wpa_supplicant" in VERIFY
for marker in (
    "N3DS-PRIVACY",
    "N3DS-WPA-RAW",
    "N3DS-RSN-RAW",
    "N3DS-SECURITY-UNKNOWN",
):
    assert marker in VERIFY

for obsolete in (
    "patch_ar6014_targeted_harvest.py",
    "patch_ar6014_validated_bss_harvest.py",
    "patch_ar6014_direct_bss_preference.py",
    "patch_wpa_scan_harvest_timeout.py",
):
    assert f"run {obsolete}" not in BUILD

print("wifi_pipeline: PASS")
