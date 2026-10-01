#!/usr/bin/env python3
"""Stop throwing away why mobiledata_apctl failed.

In the 2026-09-01 capture Mobile Data no longer times out: it fails in ~121 ms.

    [255.293] mobiledata: stage=interface_ready result=2s
    [255.414] mobiledata: stage=station_restore result=ok
    [255.779] mobiledata: stage=station_resume result=begin
    [255.956] mobiledata: stage=rollback result=restored
    [256.162] mobiledata: stage=error result=ap_controller_failed

There is no `mobiledata_apctl: stage=...` line anywhere in that window, even
though the window itself is captured and every failure path inside
`start_ap()` calls `fail_stage()` -> `report_failure()`, which writes
/dev/kmsg.  The binary is present, executable, and byte-identical to the one
just built, so it did run.

Two things hide the answer, and both are in this script:

  * `>/dev/null 2>&1` on the invocation.  `main()` returns 2 for a usage error
    without ever touching /dev/kmsg -- it writes stderr and exits.  That is the
    one failure class consistent with the evidence, and it is precisely the
    class this redirect erases.
  * the exit code is consumed by `||` and never recorded, so
    "controller returned 2" and "controller returned 1 after reporting a
    stage" are indistinguishable from the trace.

Keep both: route the controller's stderr to a file, publish its exit status and
the first few stderr lines to /dev/kmsg on failure, and announce the invocation
before it happens so a controller that dies without reporting anything is still
bracketed by two lines instead of one.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


MD = Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/"
          "rootfs_overlay/etc/mobiledata.sh")

MARKER = "N3DS_MOBILE_DATA_APCTL_DIAG"

HELPER_OLD = '''trace() {
'''

HELPER_NEW = '''# N3DS_MOBILE_DATA_APCTL_DIAG: the controller reports its own failures to
# /dev/kmsg from report_failure(), but a usage error (exit 2) writes stderr and
# exits without reporting a stage -- and stderr was going to /dev/null.  That is
# the only failure class consistent with the 2026-09-01 capture, which reached
# `error ap_controller_failed` 121 ms after `interface_ready` with no
# `mobiledata_apctl:` line at all.  Keep the exit status and the head of stderr.
APCTL_ERR=/tmp/mobiledata_apctl.err
APCTL_ERR_BYTES=400

kmsg() {
	echo "$1" > /dev/kmsg 2>/dev/null || true
}

run_apctl() {
	kmsg "mobiledata: apctl begin argv=$*"
	rm -f "$APCTL_ERR" 2>/dev/null || true
	"$APCTL" "$@" >/dev/null 2>"$APCTL_ERR"
	apctl_rc=$?
	kmsg "mobiledata: apctl rc=$apctl_rc argv=$1"
	if [ "$apctl_rc" -ne 0 ] && [ -s "$APCTL_ERR" ]; then
		head -c "$APCTL_ERR_BYTES" "$APCTL_ERR" 2>/dev/null |
		while IFS= read -r apctl_line; do
			kmsg "mobiledata: apctl err: $apctl_line"
		done
	fi
	return "$apctl_rc"
}

trace() {
'''

STOP_OLD = '''\t\t"$APCTL" --stop "$IFACE" >/dev/null 2>&1 || {
'''

STOP_NEW = '''\t\trun_apctl --stop "$IFACE" || {
'''

START_OLD = '''\tif [ "$security" = open ]; then
\t\t"$APCTL" --start "$IFACE" "$AP_SSID" open >/dev/null 2>&1 || {
\t\t\tFAIL_BOUNDARY=ap_controller_failed
\t\t\trollback_start ap_controller_failed
\t\t\treturn 1
\t\t}
\telse
\t\t"$APCTL" --start "$IFACE" "$AP_SSID" wpa2 "$SECRET_FILE" >/dev/null 2>&1 || {
\t\t\tFAIL_BOUNDARY=ap_controller_failed
\t\t\trollback_start ap_controller_failed
\t\t\treturn 1
\t\t}
\tfi
'''

START_NEW = '''\ttrace controller_start begin "$MODULE_MODE"
\tif [ "$security" = open ]; then
\t\trun_apctl --start "$IFACE" "$AP_SSID" open || {
\t\t\tFAIL_BOUNDARY=ap_controller_failed
\t\t\trollback_start ap_controller_failed
\t\t\treturn 1
\t\t}
\telse
\t\trun_apctl --start "$IFACE" "$AP_SSID" wpa2 "$SECRET_FILE" || {
\t\t\tFAIL_BOUNDARY=ap_controller_failed
\t\t\trollback_start ap_controller_failed
\t\t\treturn 1
\t\t}
\tfi
'''

HUNKS = (
    ("run_apctl helper", HELPER_OLD, HELPER_NEW),
    ("stop call site", STOP_OLD, STOP_NEW),
    ("start call sites", START_OLD, START_NEW),
)


def patch_text(text: str) -> str:
    """Capture mobiledata_apctl's exit status and stderr in mobiledata.sh.

    Idempotent: an already-patched tree is returned untouched.
    """
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, f"{name}: expected exactly one match"
        text = text.replace(old, new)
    return text


def main() -> None:
    original = MD.read_text(encoding="utf-8")
    patched = patch_text(original)
    if patched == original:
        print("mobiledata_apctl_diag: already applied")
        return
    MD.write_text(patched, encoding="utf-8")
    print(f"mobiledata_apctl_diag: patched {MD}")


if __name__ == "__main__":
    main()
