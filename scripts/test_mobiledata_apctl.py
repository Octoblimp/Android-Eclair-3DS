#!/usr/bin/env python3
"""Static contract checks for the bounded 3DS Telco AP controller."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native/mobiledata/mobiledata_apctl.c"
BUILD = ROOT / "scripts/build_mobiledata_apctl.sh"
RUNTIME = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/mobiledata.sh"
PIPELINE = ROOT / "scripts/rebuild_everything.sh"


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")
    pipeline = PIPELINE.read_text(encoding="utf-8")

    for marker in (
        "AR6000_IOCTL_EXTENDED",
        "N3DS_MOBILE_DATA_IOCTL",
        "SIOCDEVPRIVATE + 15",
        "MOBILEDATA_XIOCTL 162",
        "MOBILEDATA_START_OPEN",
        "MOBILEDATA_START_WPA2",
        "MOBILEDATA_STOP",
        "SIOCSIWMODE",
        "IW_MODE_MASTER",
        "SIOCSIWESSID",
        "SIOCSIWAUTH",
        "IW_AUTH_WPA_VERSION_WPA2",
        "IW_AUTH_CIPHER_CCMP",
        "IW_ENCODE_ALG_PMK",
        "derive_pmk",
        "PBKDF2",
        "O_NOFOLLOW",
        "carrier_is_up",
        "rssi unknown",
        "report_failure",
        "mobiledata_apctl: stage=%s errno=%d",
        "/dev/kmsg",
        'fail_stage("private_start")',
        'fail_stage("private_start_open")',
        'fail_stage("set_mode_protected")',
        'fail_stage("ready_timeout")',
    ):
        assert marker in source, f"controller missing {marker!r}"
    open_boundary = source.index("if (!protected) {")
    private_open = source.index("MOBILEDATA_START_OPEN", open_boundary)
    protected_mode = source.index("IW_MODE_MASTER", private_open)
    assert open_boundary < private_open < protected_mode
    wait_ready = source[source.index("wait_ready:"):source.index("rollback:")]
    assert "SIOCGIWMODE" not in wait_ready
    assert "carrier_is_up(iface)" in wait_ready

    # N3DS_MOBILEDATA_STOP_MODE_BEST_EFFORT: a flaky/unsupported generic
    # SIOCSIWMODE(IW_MODE_INFRA) must never override a successful private
    # MOBILEDATA_STOP result, or restore_sta() in mobiledata.sh bails before
    # ever reloading the station module and the radio is stuck in AP mode.
    stop_ap_block = source[source.index("static int stop_ap("):
                           source.index("static int print_stats(")]
    assert 'result = private_control(fd, &request, MOBILEDATA_STOP' in stop_ap_block
    assert "(void)set_mode(fd, &request, IW_MODE_INFRA);" in stop_ap_block, \
        "stop_ap() must treat SIOCSIWMODE as best-effort, matching its own rollback path"
    assert "if (set_mode(fd, &request, IW_MODE_INFRA) != 0)" not in stop_ap_block, \
        "stop_ap() must not let SIOCSIWMODE clobber a successful MOBILEDATA_STOP result"
    assert source.count("ioctl(fd, N3DS_MOBILE_DATA_IOCTL") == 2
    assert "#define MOBILEDATA_WAIT_MS 10000u" in source
    assert "printf(\"%s" not in source
    assert "secret" in runtime and "mobiledata_apctl" in runtime
    assert "build_mobiledata_apctl.sh" in pipeline
    assert "test_mobiledata_apctl.py" in pipeline
    shell = subprocess.run(["bash", "-n", str(BUILD)], capture_output=True,
                           text=True)
    assert shell.returncode == 0, shell.stderr
    print("mobiledata_apctl: PASS (bounded direct/private AP controller)")


if __name__ == "__main__":
    main()
