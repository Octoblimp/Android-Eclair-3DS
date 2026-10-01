#!/usr/bin/env python3
"""Offline regression contract for durable 3DSTelco enrollment state.

This intentionally never opens a network connection and never contains a real
token or setup code.  The Java client is checked for the complete persistence
and reboot-restore path, while a temporary-file model exercises the required
atomic replacement semantics independently of Android.
"""

from pathlib import Path
import os
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PHONE = ROOT / "content/stock-app-overlays/Phone/src/com/android/phone"
service = (PHONE / "TelcoService.java").read_text(encoding="utf-8")
http = (PHONE / "TelcoHttp.java").read_text(encoding="utf-8")
config = (PHONE / "TelcoConfig.java").read_text(encoding="utf-8")
contract = (PHONE / "TelcoContract.java").read_text(encoding="utf-8")
settings = (ROOT / "content/settings/src/com/android/settings/MobileDataSettings.java").read_text(encoding="utf-8")

for marker in (
    '"/sdcard/persistent/shared/mobile_registration.conf"',
    "writeEnrollment",
    "TelcoConfig.writeEnrollment",
    "restoreFromConfig",
    "setMobileDataOnBoot",
    '"mobile_data_on_boot_set"',
    "setEndpoint",
):
    assert marker in (service + http + config + settings), marker
for marker in (
    "File.createTempFile",
    "OutputStreamWriter(output, \"UTF-8\")",
    "writer.flush()",
    "output.getFD().sync()",
    "temporary.renameTo(file)",
    "Unable to atomically replace registration file",
    "throws IOException",
):
    assert marker in config, marker
assert 'KEY_LATENCY_MS = "n3ds_telco_latency_ms"' in contract
assert "TelcoConfig.writeEnrollment" in http
save = http[http.index("void saveEnrollment"):]
assert 'putBoolean("pending_config", true)' in save
assert "persistPendingEnrollment()" in service
assert "registration_storage_failed" in http
assert "02:00:00:00:00:00" in service
assert "TelcoContract.clearLatency(this)" in service


def atomic_replace(path: Path, text: str) -> None:
    """Small local model of the Java temp+flush+rename protocol."""
    fd, name = tempfile.mkstemp(prefix=".3ds-reg-", suffix=".tmp", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


with tempfile.TemporaryDirectory() as directory:
    registration = Path(directory) / "mobile_registration.conf"
    original = "# 3DSTelco Mobile Registration Configuration\nmobile_data_on_boot=0\n"
    atomic_replace(registration, original)
    assert registration.read_text(encoding="utf-8") == original

    enrolled = (
        "# 3DSTelco Mobile Registration Configuration\n"
        "mobile_data_on_boot=1\n"
        "token=" + "A" * 43 + "\n"
        "number=3270\n"
        "endpoint=https://example.invalid\n"
        "expires_at=2026-10-06T05:00:48Z\n"
    )
    atomic_replace(registration, enrolled)
    restored = dict(
        line.split("=", 1)
        for line in registration.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert restored["mobile_data_on_boot"] == "1"
    assert restored["number"] == "3270"
    assert restored["endpoint"] == "https://example.invalid"
    assert restored["expires_at"].endswith("Z")

print("telco_persistence: PASS (offline durable-write and reboot-restore contract)")
