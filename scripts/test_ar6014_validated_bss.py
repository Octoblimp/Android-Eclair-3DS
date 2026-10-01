#!/usr/bin/env python3
"""Regression checks for the hardware-measured, validated BSS harvester."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path
import importlib.util


SOURCE = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c")


def valid_infrastructure_header(frame: bytes) -> bool:
    return (
        len(frame) >= 24
        and frame[0] in (0x50, 0x80)
        and (frame[1] & 0x03) == 0
        and frame[10:16] == frame[16:22]
        and not (frame[16] & 1)
        and any(frame[16:22])
        and (frame[0] != 0x80 or frame[4:10] == b"\xff" * 6)
    )


def valid_suite(suite: bytes, is_wpa: bool) -> bool:
    return suite[:3] == (b"\x00\x50\xf2" if is_wpa else b"\x00\x0f\xac")


def valid_security_ie(ie: bytes, is_wpa: bool) -> bool:
    pos = 0
    if is_wpa:
        if len(ie) < 4 or ie[:4] != b"\x00\x50\xf2\x01":
            return False
        pos = 4
    if len(ie) - pos < 8 or ie[pos : pos + 2] != b"\x01\x00":
        return False
    pos += 2
    if not valid_suite(ie[pos : pos + 4], is_wpa):
        return False
    pos += 4
    if pos + 2 > len(ie):
        return False
    count = int.from_bytes(ie[pos : pos + 2], "little")
    if not count or count > (len(ie) - pos - 2) // 4:
        return False
    pos += 2
    for _ in range(count):
        if not valid_suite(ie[pos : pos + 4], is_wpa):
            return False
        pos += 4
    if pos + 2 > len(ie):
        return False
    count = int.from_bytes(ie[pos : pos + 2], "little")
    if not count or count > (len(ie) - pos - 2) // 4:
        return False
    pos += 2
    for _ in range(count):
        if not valid_suite(ie[pos : pos + 4], is_wpa):
            return False
        pos += 4
    if is_wpa:
        return pos == len(ie)
    if pos == len(ie):
        return True
    if pos + 2 > len(ie):
        return False
    pos += 2
    if pos == len(ie):
        return True
    if pos + 2 > len(ie):
        return False
    count = int.from_bytes(ie[pos : pos + 2], "little")
    if count > (len(ie) - pos - 2) // 16:
        return False
    pos += 2 + count * 16
    return pos == len(ie) or (
        len(ie) - pos == 4 and valid_suite(ie[pos:], is_wpa)
    )


def fallback_security_status(capability: int, ies: list[tuple[int, bytes]]) -> str | None:
    privacy = bool(capability & 0x0010)
    has_security = False
    for element_id, body in ies:
        if element_id == 48:
            if not valid_security_ie(body, False):
                return None
            has_security = True
        elif element_id == 221 and body[:4] == b"\x00\x50\xf2\x01":
            if not valid_security_ie(body, True):
                return None
            has_security = True
    if not privacy and has_security:
        return None
    return "protected" if privacy else "open"


def fallback_frame_security_status(
    capability: int, ies: list[tuple[int, bytes, int]]
) -> str | None:
    """Model the fallback IE walk, including declared-vs-available length."""
    privacy = bool(capability & 0x0010)
    rates = False
    channel = False
    ssid = False
    has_security = False
    for element_id, body, declared_len in ies:
        if declared_len != len(body):
            # The remainder of the IE stream is untrusted; a hidden RSN/WPA
            # element after a truncated generic element cannot be ignored.
            return None
        if element_id == 0:
            ssid = 0 < len(body) <= 32
        elif element_id in (1, 50):
            rates = 1 <= len(body) <= 16
        elif element_id in (3, 61):
            channel = len(body) >= 1 and 1 <= body[0] <= 14
        elif element_id == 48:
            if not valid_security_ie(body, False):
                return None
            has_security = True
        elif element_id == 221 and body[:4] == b"\x00\x50\xf2\x01":
            if not valid_security_ie(body, True):
                return None
            has_security = True
    if not ssid or not rates or not channel:
        return None
    if not privacy and has_security:
        return None
    return "protected" if privacy else "open"


def queue_harvest_model(
    busy: int, owner: object, status: int, new_owner: object, new_status: int
) -> tuple[int, object, int, bool]:
    """Model acquire-before-publish ownership for one deferred worker."""
    if busy:
        return busy, owner, status, False
    return 1, new_owner, new_status, True


def test_previous_security_parser_migrates() -> None:
    """The old marker-bearing selective truncation parser must be replaced."""
    patch_path = Path(__file__).with_name("patch_ar6014_validated_bss_harvest.py")
    spec = importlib.util.spec_from_file_location("ar6014_harvest_patch", patch_path)
    assert spec and spec.loader
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    old = """static int
ar6014_security_suite_oui(const u8 *suite, int is_wpa)
{
    return suite[0] == 0;
}

static int
ar6014_valid_security_ie(const u8 *ie, int ie_len, int is_wpa)
{
    return ie_len > 0;
}

extern int wmi_n3ds_direct_bss_seen(struct wmi_t *wmip,
                                      const u8 *bssid);

static int
ar6014_parse_bss_frame(struct wmi_t *wmip, u8 *frame, int avail,
                       u32 target_offset, u32 *seen_lo, u32 *seen_hi)
{
    /* N3DS_AR6014_SECURITY_VALIDATION: old selective truncation behavior. */
    while (p + 2 <= end) {
        if (p + 2 + p[1] > end) {
            if (p[0] == IEEE80211_ELEMID_RSN)
                return 0;
            break;
        }
        p += 2 + p[1];
    }
}

static int
ar6002_nwm_write_blob(void)
{
    return 0;
}
"""
    migrated = patch.install_security_parser(old)
    assert "N3DS_AR6014_TRUNCATED_IE_FAIL_CLOSED" in migrated
    assert "N3DS_AR6014_SECURITY_VALIDATION" in migrated
    assert "not only elements whose ID is already security-like" in migrated
    assert migrated.count("static int\nar6014_security_suite_oui(") == 1
    assert migrated.count("static int\nar6014_valid_security_ie(") == 1

    helper_start = migrated.index("static int\nar6014_security_suite_oui(")
    helpers_end = migrated.index(
        "\nextern int wmi_n3ds_direct_bss_seen", helper_start
    )
    duplicate = (
        migrated[:helpers_end]
        + migrated[helper_start:helpers_end]
        + migrated[helpers_end:]
    )
    normalized = patch.install_security_parser(duplicate)
    assert normalized.count("static int\nar6014_security_suite_oui(") == 1
    assert normalized.count("static int\nar6014_valid_security_ie(") == 1


def main() -> None:
    test_previous_security_parser_migrates()
    text = SOURCE.read_text()
    assert "N3DS_AR6014_VALIDATED_TARGET_BSS" in text
    assert "N3DS_AR6014_BSS_CHANNEL_VALIDATION" in text
    assert "AR6014_HARVEST_BOOT_LO       0x00010000" in text
    assert "AR6014_HARVEST_BOOT_HI       0x0001fe00" in text
    assert "AR6014_LOCATOR_" not in text and "ar6014_locator_phase" not in text
    assert "memcmp(frame + 10, frame + 16, ETH_ALEN)" in text
    assert "AR6002 scan: validated swept=" in text
    assert "AR6002 scan: reject cached bssid=" in text
    assert "wmi_n3ds_direct_bss_seen(wmip, frame + 16)" in text
    assert "direct_skipped" in text
    assert "N3DS_AR6014_SECURITY_VALIDATION" in text
    assert "ar6014_security_suite_oui" in text
    assert "ar6014_valid_security_ie" in text
    assert "0x0010" in text
    assert "if (p + 2 + p[1] > end)" in text
    assert "N3DS_AR6014_TRUNCATED_IE_FAIL_CLOSED" in text
    assert "N3DS_AR6014_HARVEST_QUEUE_SERIALIZATION" in text
    assert "N3DS_AR6014_HARVEST_SNAPSHOT_SERIALIZATION" in text
    assert "static u32 ar6014_harvest_direct_bss;" in text
    assert "wmi_n3ds_discard_direct_bss_count" in text
    assert text.count("static int\nar6014_security_suite_oui(") == 1
    assert text.count("static int\nar6014_valid_security_ie(") == 1
    queue_start = text.index("static bool\nar6014_queue_harvest(")
    queue_end = text.index("\nstatic int\nar6014_harvest_bss_sync(", queue_start)
    queue = text[queue_start:queue_end]
    assert queue.index("atomic_cmpxchg(&ar6014_harvest_busy, 0, 1)") < queue.index(
        "ar6014_harvest_ar = ar;"
    )
    assert queue.index("ar6014_harvest_ar = ar;") < queue.index(
        "ar6014_harvest_status = status;"
    )
    assert queue.index("ar6014_harvest_status = status;") < queue.index(
        "wmi_n3ds_take_direct_bss_count(ar->arWmi)"
    )
    assert queue.index("wmi_n3ds_take_direct_bss_count(ar->arWmi)") < queue.index(
        "schedule_work(&ar6014_harvest_work)"
    )

    real = bytearray(24)
    real[0] = 0x80
    real[4:10] = b"\xff" * 6
    real[10:16] = bytes.fromhex("8cdd0b0053c8")
    real[16:22] = real[10:16]
    assert valid_infrastructure_header(real)

    false_positive = bytearray(real)
    false_positive[16:22] = bytes.fromhex("524500440000")
    assert not valid_infrastructure_header(false_positive)

    rsn = (
        b"\x01\x00" + b"\x00\x0f\xac\x04" + b"\x01\x00"
        + b"\x00\x0f\xac\x04" + b"\x01\x00"
        + b"\x00\x0f\xac\x02" + b"\x00\x00"
    )
    assert fallback_security_status(0, []) == "open"
    assert fallback_security_status(0x0010, []) == "protected"
    assert fallback_security_status(0x0010, [(48, rsn)]) == "protected"
    assert fallback_security_status(0, [(48, rsn)]) is None

    # Captured tlc6efe7 shape: privacy is set (caps=0x411), but the RSN
    # group selector is malformed and must never be downgraded to OPEN.
    malformed_tlc = (
        b"\x01\x00" + b"\x16\x0e\xac\x04" + b"\x01\x00"
        + b"\x00\x0f\xac\x04" + b"\x01\x00"
        + b"\x00\x0f\xac\x02" + b"\x00\x00"
    )
    assert fallback_security_status(0x0411, [(48, malformed_tlc)]) is None

    # A privacy-clear frame with valid SSID/rates/channel IEs is not proven
    # open when a generic IE declares bytes that are absent.  A later RSN IE
    # may be hidden behind that truncation, so the complete fallback result
    # must be rejected rather than downgraded to OPEN.
    valid_open_ies = [
        (0, b"Cafe", 4),
        (1, b"\x82", 1),
        (3, b"\x06", 1),
    ]
    assert fallback_frame_security_status(0, valid_open_ies) == "open"
    hidden_rsn = valid_open_ies + [
        (221, b"\x00", 8),  # generic truncated IE; RSN follows in hidden bytes
        (48, rsn, len(rsn)),
    ]
    assert fallback_frame_security_status(0, hidden_rsn) is None

    busy, owner, status, claimed = queue_harvest_model(
        0, None, 0, "first-scan", 0
    )
    assert claimed and (busy, owner, status) == (1, "first-scan", 0)
    busy, owner, status, claimed = queue_harvest_model(
        busy, owner, status, "overlapping-scan", -5
    )
    assert not claimed and (busy, owner, status) == (1, "first-scan", 0)
    print("ar6014_validated_bss: PASS")


if __name__ == "__main__":
    main()
