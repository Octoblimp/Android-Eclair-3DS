#!/usr/bin/env python3
"""Focused source contract for durable 3DSTelco send/receive semantics."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHONE = ROOT / "content/stock-app-overlays/Phone/src/com/android/phone"
store = (PHONE / "TelcoMessageStore.java").read_text(encoding="utf-8")
provider = (PHONE / "TelcoProvider.java").read_text(encoding="utf-8")
service = (PHONE / "TelcoService.java").read_text(encoding="utf-8")

assert 'ROOT = "/sdcard/persistent/shared/messages"' in store
for child in ('"pending"', '"sent"', '"received"'):
    assert child in store
assert "output.getFD().sync()" in store
assert "temporary.renameTo(file)" in store
assert "MAX_RECORD_BYTES" in store and "MAX_RECORDS" in store
assert "static synchronized TelcoMessageStore get" in store
assert provider.index("messages.queue(") < provider.index('http.request("POST", "/v1/messages"')
assert provider.index('http.request("POST", "/v1/messages"') < provider.index("messages.beginSent(")
assert "UUID.randomUUID().toString()" in provider
assert "flushPendingMessages()" in service
assert service.index("messages.beginIncoming(") < service.index('"/delivered"')
assert 'firstNotification && !archived.flag("read")' in service
assert "messages.reconcileSmsRows()" in service
assert 'record.json.put("read", true)' in store
assert "Sms.Inbox.addMessage" in store and "Sms.Sent.addMessage" in store
# A torn record on the FAT card must not take the whole service down
# ("Invalid message journal record size: 1.json", 2026-09-30).
assert "N3DS_TELCO_JOURNAL_QUARANTINE" in store and '".corrupt"' in store
assert "N3DS_TELCO_JOURNAL_ATOMIC_RENAME" in store
# Web account numbers are ten digits; calls and texts must accept them.
voip = (PHONE / "VoipSession.java").read_text(encoding="utf-8")
assert "N3DS_TELCO_WEB_NUMBERS" in service and "[2-9][0-9]{9}" in service
assert "[2-9][0-9]{9}" in provider
assert "N3DS_TELCO_VOIP_HOST" in service and "N3DS_TELCO_T3E1" in voip
print("telco_message_persistence: PASS")
