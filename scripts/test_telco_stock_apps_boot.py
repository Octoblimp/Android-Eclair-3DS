#!/usr/bin/env python3
"""Regression contract for Messages boot with optional stock providers absent."""

from pathlib import Path
import runpy
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PATCHER_PATH = ROOT / "scripts/patch_telco_stock_apps.py"
PATCHER = PATCHER_PATH.read_text(encoding="utf-8")

assert "MMS_OUTBOX_RECOVERY_OLD" in PATCHER
assert "MMS_OUTBOX_RECOVERY_NEW" in PATCHER
assert "N3DS_MMS_MISSING_SMS_PROVIDER_GUARD" in PATCHER
assert "SqliteWrapper.update(" in PATCHER
assert "catch (IllegalArgumentException e)" in PATCHER
assert 'resolveContentProvider("mms-sms", 0)' in PATCHER
assert 'resolveContentProvider("sms", 0)' in PATCHER
assert "MMS_QUEUED_SEND_NEW" in PATCHER
assert "MMS_NOTIFICATION_UPDATE_NEW" in PATCHER
assert "MMS_STATUS_UPDATE_NEW" in PATCHER
# The dialer guards (N3DS_DIALER_AUDIO_SERVICE_GUARD and friends) are no
# longer patched from here: the dialer source this patcher edited is not in
# the workspace and nothing rebuilds Contacts.apk, so they are checked
# against the shipped dex in test_telco_live_regressions.py instead.

# Exercise the same replacement helper used by the build patcher.  This keeps
# the guard fail-closed for an unexpected source layout and proves a second
# invocation leaves an already-patched source unchanged.
symbols = runpy.run_path(str(PATCHER_PATH), run_name="telco_stock_apps_test")
replace_exact = symbols["replace_exact"]
old = symbols["MMS_OUTBOX_RECOVERY_OLD"]
new = symbols["MMS_OUTBOX_RECOVERY_NEW"]

with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / "SmsReceiverService.java"
    source.write_text(old, encoding="utf-8")
    assert replace_exact(source, old, new)
    assert "N3DS_MMS_MISSING_SMS_PROVIDER_GUARD" in source.read_text(encoding="utf-8")
    assert not replace_exact(source, old, new)

print("telco_stock_apps_boot: PASS")
