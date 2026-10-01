#!/usr/bin/env python3
"""Focused regression for the AR6014 NWM two-byte data framing boundary.

This test is intentionally host-side.  It parses the sanitized #258 packet
prefixes preserved in a dated fixture and applies the same bounds
rules as the CTR RX guard.  It never stores or prints Wi-Fi credentials.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from a3ds_paths import A3DS_WIN


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_data_header.py")
TRACE = ROOT / "scripts/fixtures/nwm-data-header-20260902.txt"
DECOMP = ROOT / "scratch" / "nwm-full-corpus" / "functions"
if not DECOMP.is_dir():
    DECOMP = Path(A3DS_WIN) / "scratch" / "nwm-full-corpus" / "functions"

LOCAL_MAC = bytes.fromhex("5c 52 1e 00 53 62")
AP_MAC = bytes.fromhex("8c dd 0b 00 53 c8")
LLC_PREFIX = bytes.fromhex("aa aa 03")
EAPOL = bytes.fromhex("88 8e")
MAX_RX = 3840 + 2 + 14 + 8


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location("nwm_data_header_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_capture() -> list[tuple[int, bytes]]:
    assert TRACE.is_file(), f"missing #258 capture: {TRACE}"
    rows: list[tuple[int, bytes]] = []
    pattern = re.compile(
        r"rxpkt data len=(\d+) ((?:[0-9a-f]{2} ?)+)$", re.IGNORECASE
    )
    for line in TRACE.read_text(encoding="utf-8").splitlines():
        match = pattern.search(line)
        if match:
            rows.append((int(match.group(1)), bytes.fromhex(match.group(2))))
    assert len(rows) == 29, f"expected all 29 #258 packet dumps, found {len(rows)}"
    assert {length for length, _ in rows} == {123}
    assert {len(packet) for _, packet in rows} == {32}
    return rows


def validate_ctr_8023(raw: bytes, actual_len: int) -> bool:
    """Model the bounded validator required before conversion/aggregation."""

    header_len = 2
    mac_len = 14
    llc_len = 8
    if (len(raw) < header_len or actual_len < header_len + mac_len + llc_len or
            actual_len > MAX_RX):
        return False
    if ((raw[1] >> 6) & 0x3) != 0:
        return False
    frame = raw[header_len:]
    # The check above is on the full target packet; the dump may be truncated.
    if len(frame) < mac_len + 3:
        return False
    declared = (frame[12] << 8) | frame[13]
    if declared < llc_len or declared > actual_len - header_len - mac_len:
        return False
    return frame[14:17] == LLC_PREFIX


def validate_ctr_rx_path(raw: bytes, actual_len: int, *, dot11: bool = False,
                         ap_null: bool = False) -> bool:
    """Model the caller's path gate around the 802.3-only validator."""

    if len(raw) < 2 or actual_len < 2:
        return False
    if (raw[1] >> 6) != int(dot11):
        return False
    if ap_null and not dot11 and actual_len == 2 + 14:
        # AP NULL data is the exact 2-byte NWM prefix plus 14-byte MAC form;
        # it has no LLC bytes to inspect.
        return True
    if actual_len < 2 + (24 if dot11 else 14) + 8 or actual_len > MAX_RX:
        return False
    if dot11:
        # Dot11 frames have a different header grammar and must not be fed to
        # the 802.3 LLC/length checker.
        return True
    return validate_ctr_8023(raw, actual_len)


def make_packet(*, declared: int = 8, llc: bytes = bytes.fromhex("aa aa 03 00 00 00 88 8e"),
                padding: bytes = b"") -> tuple[bytes, int]:
    frame = LOCAL_MAC + AP_MAC + declared.to_bytes(2, "big") + llc + b"x" + padding
    raw = bytes((0x40, 0x18)) + frame
    return raw, len(raw)


def assert_capture_layout() -> None:
    rows = parse_capture()
    for actual_len, packet in rows:
        assert packet[:2] == bytes((packet[0], 0x18))
        frame = packet[2:]
        assert frame[:6] == LOCAL_MAC
        assert frame[6:12] == AP_MAC
        assert frame[14:17] == LLC_PREFIX
        assert frame[20:22] == EAPOL
        declared = int.from_bytes(frame[12:14], "big")
        assert declared == 0x006B
        assert declared >= 8 and declared <= actual_len - 16
        assert validate_ctr_8023(packet, actual_len)

        # Stock six-byte parsing consumes destination-address bytes as info2.
        legacy_info2 = int.from_bytes(packet[2:4], "little")
        assert legacy_info2 == 0x525C
        assert legacy_info2 & 0x1000  # false A-MSDU indication
        assert (legacy_info2 >> 13) & 0x7  # false metadata version
        assert packet[6:12] != LOCAL_MAC  # misaligned legacy destination


def assert_validator_edges() -> None:
    valid, valid_len = make_packet()
    padded, padded_len = make_packet(padding=b"\x00\x00\x00\x00")
    assert validate_ctr_8023(valid, valid_len)
    assert validate_ctr_8023(padded, padded_len)

    # 802.3 data must carry at least the two-byte prefix, 14-byte MAC pair,
    # and eight-byte LLC/SNAP.  Exercise every short total from 17 through 23.
    for actual_len in range(17, 24):
        assert not validate_ctr_rx_path(valid, actual_len)
        assert not validate_ctr_rx_path(valid, actual_len, dot11=True)

    assert not validate_ctr_rx_path(valid, MAX_RX + 1, dot11=True)

    non_8023 = bytearray(valid)
    non_8023[1] = 0x58  # WMI_DATA_HDR_DATA_TYPE_802_11, not 802.3.
    non_8023 = bytes(non_8023)
    assert not validate_ctr_rx_path(non_8023, len(non_8023))
    assert not validate_ctr_rx_path(non_8023, len(non_8023), dot11=True)
    non_8023 += b"\0" * 16
    assert validate_ctr_rx_path(non_8023, len(non_8023), dot11=True)
    ap_null = b"\x00" * (2 + 14)
    assert validate_ctr_rx_path(ap_null, len(ap_null), ap_null=True)
    assert not validate_ctr_rx_path(ap_null, len(ap_null))

    truncated, _ = make_packet()
    assert not validate_ctr_8023(truncated[:23], 23)
    too_small, too_small_len = make_packet(declared=7)
    assert not validate_ctr_8023(too_small, too_small_len)
    # The packet has exactly nine bytes available after the 802.3 length
    # field (eight-byte LLC/SNAP plus the one-byte payload).  Ten is the
    # first genuinely oversized declaration.
    too_large, too_large_len = make_packet(declared=10)
    assert not validate_ctr_8023(too_large, too_large_len)
    bad_llc, bad_llc_len = make_packet(llc=bytes.fromhex("aa ab 03 00 00 00 88 8e"))
    assert not validate_ctr_8023(bad_llc, bad_llc_len)


def assert_decompilation_evidence() -> None:
    """Pin the independent NWM binary evidence behind the source patch."""

    tx = (DECOMP / "00135a0a_FUN_00135a0a.c").read_text(encoding="utf-8")
    rx = (DECOMP / "00135a50_FUN_00135a50.c").read_text(encoding="utf-8")
    htc_rx = (DECOMP / "001332bc_FUN_001332bc.c").read_text(encoding="utf-8")
    htc_lookahead = (DECOMP / "0011c090_FUN_0011c090.c").read_text(encoding="utf-8")

    # Local NWM TX allocates/pushes exactly two bytes, writes info at byte 1,
    # and clears byte 0 (RSSI) before the frame leaves the target.
    assert "FUN_0011ffea(param_2,2,param_3,param_4,param_4)" in tx
    assert "puVar2[1] = (char)param_3;" in tx
    assert "*puVar2 = 0;" in tx

    # NWM RX removes the same two-byte prefix.
    assert "FUN_0011f6c0(param_2,2);" in rx

    # HTC framing is independent and remains six bytes in both the callback
    # path and the look-ahead/error path; this must happen before WMI data
    # framing is interpreted.
    assert "FUN_001205b8(local_30,*(int *)(param_2 + 0x18) + 6);" in htc_rx
    assert "FUN_0011f6c0(local_30,6);" in htc_rx
    assert "*(int *)(param_2 + 0x18) = *(int *)(param_2 + 0x18) + -6;" in htc_lookahead
    assert "*(int *)(param_2 + 0x10) = *(int *)(param_2 + 0x10) + 6;" in htc_lookahead


def transform_sources(patcher):
    # The canonical source lives in WSL and may not be mounted on a host-only
    # test runner.  Build a fixture from the patcher's exact, fail-closed
    # anchors so this test still proves every replacement and its idempotence;
    # the release verifier separately greps the real canonical WSL files.
    h = patcher.OLD_INFO_FIELDS + "\n" + patcher.OLD_STRUCT
    c = (
        patcher.OLD_DATA_ADD_DECL
        + "\n    if (A_NETBUF_PUSH(osbuf, sizeof(WMI_DATA_HDR)) != A_OK) {}\n"
        + "    if (A_NETBUF_PUSH(osbuf, sizeof(WMI_DATA_HDR)) != A_OK) {}\n"
        + "    if (A_NETBUF_PULL(osbuf, sizeof(WMI_DATA_HDR)) != A_OK) {}\n"
        + "    A_MEMZERO(dtHdr, sizeof(WMI_DATA_HDR));\n"
        + "    WMI_DATA_HDR_SET_MSG_TYPE(dtHdr, msgType);\n"
        + "    WMI_DATA_HDR_SET_DATA_TYPE(dtHdr, data_type);\n"
        + "    WMI_DATA_HDR_SET_META(dtHdr, metaVersion);\n\n"
        + "    dtHdr->info3 = 0;\n"
        + patcher.OLD_SYNC_BODY
        + "\n"
    )
    cfg = patcher.OLD_CONFIG
    drv = (
        patcher.OLD_CSUM_PARAM
        + "\n"
        + patcher.OLD_MODULE_INIT
        + "\n"
        + patcher.OLD_RX_META
        + "\n"
        + patcher.OLD_TX_DECL
        + "\n"
        + "\n    A_NETBUF_PULL(skb, HTC_HEADER_LEN);\n"
        + patcher.OLD_RX_PREFIX_ANCHOR
        + "\n"
        + patcher.OLD_RX_ANCHOR
    )
    old_reorder = """                    aggr_process_recv_frm(ar->aggr_cntxt, tid, seq_no, is_amsdu, (void **)&skb);
                    /* N3DS_AR6014_RX_DROP_CENSUS: the reorder buffer keeps the
                     * frame and NULLs the pointer, which every counter we had
                     * scored exactly like a successful delivery. */
                    if (skb == NULL) {
                        atomic_inc(&n3ds_rx_drop_aggr);
                    }
                    ar6000_deliver_frames_to_nw_stack((void *) ar->arNetDev, (void *)skb);"""
    # Newer core patchers expose the exact aggregate-call anchor; older
    # revisions use this same stable source block directly.
    aggr_anchor = getattr(patcher, "OLD_AGGR_ANCHOR", old_reorder)
    drv += "\n" + aggr_anchor
    names = ("patch_wmi_h", "patch_wmi_c")
    assert all(hasattr(patcher, name) for name in names), "patcher API changed"
    patch_config = getattr(patcher, "patch_config", getattr(patcher, "patch_config_h", None))
    patch_driver = getattr(patcher, "patch_driver", getattr(patcher, "patch_driver_c", None))
    assert patch_config and patch_driver, "patcher config/driver API changed"
    functions = (patcher.patch_wmi_h, patcher.patch_wmi_c, patch_config, patch_driver)
    out = tuple(
        fn(text)
        for fn, text in zip(functions, (h, c, cfg, drv))
    )
    again = tuple(
        fn(text)
        for fn, text in zip(functions, out)
    )
    assert again == out, "source patching is not idempotent"
    return h, c, cfg, drv, out


def assert_source_contract(patcher) -> None:
    h, c, cfg, drv, (ph, pc, pcfg, pdrv) = transform_sources(patcher)
    marker = "N3DS_AR6014_NWM_DATA_HEADER"
    assert marker in ph
    assert "N3DS_AR6014_NWM_DATA_INFO_LAYOUT" in ph
    assert re.search(
        r"BUILD_BUG_ON\s*\(\s*sizeof\(WMI_DATA_HDR\)\s*!=\s*2\s*\)", pc
    )
    assert "#ifdef CONFIG_ARCH_CTR" in ph and "#else" in ph
    # Scratch mirrors use A_* typedefs; the canonical WSL tree uses Linux
    # s8/u8/u16 spellings.  Either is valid as long as both target and stock
    # fallback layouts are represented.
    assert re.search(r"(?:A_INT8|s8)\s+rssi;\s*(?:A_UINT8|u8)\s+info;", ph)
    assert re.search(r"(?:A_UINT16|u16)\s+info2;", ph)
    assert re.search(r"(?:A_UINT16|u16)\s+(?:reserved|info3);", ph)
    for macro in ("WMI_DATA_HDR_GET_SEQNO", "WMI_DATA_HDR_GET_META", "WMI_DATA_HDR_GET_DEVID"):
        assert macro in ph
    assert "WMI_DATA_HDR_IS_AMSDU" in ph or "WMI_DATA_HDR_GET_AMSDU" in ph
    assert re.search(r"WMI_DATA_HDR_GET_SEQNO\([^)]*\)\s+\(0\)", ph)
    assert re.search(r"WMI_DATA_HDR_(?:IS_AMSDU|GET_AMSDU)\([^)]*\)\s+\(0\)", ph)
    assert re.search(r"WMI_DATA_HDR_GET_META\([^)]*\)\s+\(0\)", ph)
    assert re.search(r"WMI_DATA_HDR_GET_DEVID\([^)]*\)\s+\(0\)", ph)
    for setter in ("SEQNO", "AMSDU", "META", "DEVID"):
        assert re.search(
            rf"WMI_DATA_HDR_SET_{setter}\([^\n]*\)\s+\(\(void\)0\)", ph
        )

    # The local NWM TX representation is [RSSI=0, info].  Its two bytes are
    # distinct from the generic [RSSI, info, info2, info3/reserved] ABI.
    assert 2 == 1 + 1
    assert 6 == 1 + 1 + 2 + 2
    tx_info = (0x01 << 6) | 0x02
    tx_header = bytes((0, tx_info))
    assert tx_header[0] == 0 and tx_header[1] == tx_info

    # TX data and sync helpers use the resulting sizeof; RX removes the same
    # size.  A zeroed object makes byte 0 (RSSI) deterministic before info is set.
    assert pc.count("A_NETBUF_PUSH(osbuf, sizeof(WMI_DATA_HDR))") >= 2
    assert pc.count("A_NETBUF_PULL(osbuf, sizeof(WMI_DATA_HDR))") >= 1
    assert "A_MEMZERO(dtHdr, sizeof(WMI_DATA_HDR));" in pc
    assert "WMI_DATA_HDR_SET_MSG_TYPE(dtHdr, msgType);" in pc
    assert "WMI_DATA_HDR_SET_DATA_TYPE(dtHdr, data_type);" in pc
    assert "AR6002 data: NWM two-byte header active; checksum metadata disabled" in pc
    assert "N3DS_AR6014_NWM_DATA_METADATA_DISABLED" in pc
    assert "N3DS_AR6014_NWM_SYNC_HEADER_ZERO" in pc

    assert "#ifdef CONFIG_ARCH_CTR" in pcfg
    assert "#undef CONFIG_CHECKSUM_OFFLOAD" in pcfg
    assert "#define CONFIG_CHECKSUM_OFFLOAD" in pcfg

    # HTC strips its six-byte transport header before ar6000_rx casts the WMI
    # data header; the NWM guard is before conversion/aggregation and skips dot11.
    htc = drv.index("A_NETBUF_PULL(skb, HTC_HEADER_LEN)")
    cast = drv.index("WMI_DATA_HDR *dhdr")
    assert htc < cast
    assert "N3DS_AR6014_NWM_RX_8023_BOUNDS" in pdrv
    assert "!processDot11Hdr" in pdrv
    assert "n3ds_frame" in pdrv
    length_guard = re.search(
        r"if\s*\(\s*A_NETBUF_LEN\(skb\)\s*<\s*sizeof\(WMI_DATA_HDR\)\s*\)",
        pdrv,
    )
    assert length_guard
    assert length_guard.start() < pdrv.index("WMI_DATA_HDR_GET_DATA_TYPE(dhdr)")
    assert "n3ds_expected_type" in pdrv
    assert "WMI_DATA_HDR_GET_DATA_TYPE(dhdr)" in pdrv
    assert "n3ds_ap_short" in pdrv
    assert re.search(
        r"n3ds_declared\s*=\s*\n?\s*\(\(?(?:A_UINT16|u16)\)?\s*n3ds_frame\[sizeof\(WMI_DATA_HDR\) \+ 12\].*",
        pdrv,
    )
    assert "n3ds_frame[sizeof(WMI_DATA_HDR) + 13]" in pdrv
    assert "n3ds_frame[sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR)] != 0xaa" in pdrv
    assert "goto rx_done" in pdrv
    assert "N3DS_AR6014_NWM_RX_REORDER_BYPASS" in pdrv
    aggr = pdrv.index("aggr_process_recv_frm")
    bypass = pdrv.index("N3DS_AR6014_NWM_RX_REORDER_BYPASS")
    assert bypass < aggr
    assert "#else" in pdrv[bypass:aggr]
    assert "ar->arNetworkType == AP_NETWORK" in pdrv
    assert "sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR)" in pdrv
    assert pdrv.index("n3ds_ap_short") < pdrv.index(
        "n3ds_frame[sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR)] != 0xaa"
    )

    # The generic path remains guarded, while CTR forces no RX metadata and
    # resolves CHECKSUM_PARTIAL in software before framing.
    assert "#ifndef CONFIG_ARCH_CTR" in pdrv
    assert "N3DS_AR6014_NWM_CSUM_PARAM_DISABLED" in pdrv
    assert "if(csumOffload && (csum==CHECKSUM_PARTIAL))" in pdrv
    assert "ar->rxMetaVersion = 0;" in pdrv
    assert "N3DS_AR6014_NWM_CHECKSUM_FALLBACK" in pdrv
    assert "skb_checksum_help(skb)" in pdrv
    assert "skb->ip_summed = CHECKSUM_NONE;" in pdrv
    assert "AR6000_STAT_INC(ar, tx_dropped);" in pdrv


def assert_pipeline_contract() -> None:
    build = (ROOT / "scripts" / "rebuild_everything.sh").read_text()
    verify = (ROOT / "scripts" / "verify_release_artifacts.sh").read_text()
    pipeline = (ROOT / "scripts" / "test_wifi_pipeline.py").read_text()
    patch = "patch_ar6014_nwm_data_header.py"
    test = "test_ar6014_nwm_data_header.py"
    assert build.count(f"run {patch}") == 1
    assert build.count(f"run {test}") == 1
    assert build.index(f"run {patch}") > build.index("run patch_ar6014_nwm_wmi_header.py")
    assert build.index(f"run {test}") > build.index("run test_ar6014_nwm_wmi_header.py")
    assert pipeline.count(patch) >= 2 and pipeline.count(test) >= 1
    assert verify.count(patch) >= 1 and verify.count(test) >= 1
    for marker in (
        "N3DS_AR6014_NWM_DATA_HEADER",
        "N3DS_AR6014_NWM_RX_8023_BOUNDS",
        "N3DS_AR6014_NWM_CHECKSUM_FALLBACK",
        "AR6002 data: NWM two-byte header active; checksum metadata disabled",
    ):
        assert marker in verify


def assert_compiled_contract(patcher) -> None:
    """Compile the actual patched layouts and RX checks, not a second model."""
    compiler = shutil.which("cc")
    assert compiler, "run the required compiled regression in WSL with cc"
    prefix = patcher.NEW_RX_PREFIX_ANCHOR.split("#ifdef CONFIG_ARCH_CTR", 1)[1]
    prefix = prefix.split("#endif", 1)[0]
    bounds = patcher.NEW_RX_ANCHOR.split("#ifdef CONFIG_ARCH_CTR", 1)[1]
    bounds = bounds.split("#endif", 1)[0]
    source = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef int8_t s8;
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define PREPACK
#define POSTPACK __attribute__((packed))
""" + patcher.NEW_INFO_FIELDS + patcher.NEW_STRUCT + r"""
#ifdef CONFIG_ARCH_CTR
_Static_assert(sizeof(WMI_DATA_HDR) == 2, "CTR wire header must be two bytes");
#else
_Static_assert(sizeof(WMI_DATA_HDR) == 6, "generic wire ABI must stay six bytes");
#endif
#define WMI_DATA_HDR_GET_DATA_TYPE(h) (((h)->info >> 6) & 3)
typedef enum {
    WMI_DATA_HDR_DATA_TYPE_802_3 = 0,
    WMI_DATA_HDR_DATA_TYPE_802_11 = 1
} WMI_DATA_HDR_DATA_TYPE;
typedef struct { u8 bytes[14]; } ATH_MAC_HDR;
typedef struct { u8 bytes[8]; } ATH_LLC_SNAP_HDR;
#ifdef CONFIG_ARCH_CTR
#define AP_NETWORK 16
#define AR6000_MAX_RX_MESSAGE_SIZE (3840 + 2 + 14 + 8)
#define A_NETBUF_DATA(skb) ((skb)->data)
#define A_NETBUF_LEN(skb) ((skb)->len)
#define A_NETBUF_FREE(skb) ((skb)->dropped = true)
#define AR6000_STAT_INC(ar, field) ((void)0)
#define atomic_inc(x) ((void)0)
#define AR_DEBUG_PRINTF(mask, args) ((void)0)
struct frame { u8 *data; unsigned len; bool dropped; };
static bool check(unsigned len, bool dot11, bool ap, u8 type,
                  unsigned declared, bool bad_llc) {
    struct frame packet = { calloc(len ? len : 1, 1), len, false };
    struct frame *skb = &packet;
    struct { unsigned arNetworkType; } device = { ap ? AP_NETWORK : 1 };
    typeof(device) *ar = &device;
    bool processDot11Hdr = dot11;
    unsigned minHdrLen = 2 + (dot11 ? 24 : 14) + 8;
    WMI_DATA_HDR *dhdr = (WMI_DATA_HDR *)packet.data;
    if (len >= 2) packet.data[1] = type << 6;
    if (len >= 16) {
        packet.data[14] = declared >> 8;
        packet.data[15] = declared;
    }
    if (len >= 19) {
        packet.data[16] = 0xaa;
        packet.data[17] = bad_llc ? 0xab : 0xaa;
        packet.data[18] = 3;
    }
""" + prefix + bounds + r"""
rx_done:
    free(packet.data);
    return !packet.dropped;
}
#endif
int main(void) {
    WMI_DATA_HDR h;
    memset(&h, 0, sizeof(h));
#ifdef CONFIG_ARCH_CTR
    WMI_DATA_HDR_SET_SEQNO(&h, 17);
    WMI_DATA_HDR_SET_AMSDU(&h, 1);
    WMI_DATA_HDR_SET_META(&h, 2);
    WMI_DATA_HDR_SET_DEVID(&h, 3);
    assert(!WMI_DATA_HDR_GET_SEQNO(&h));
    assert(!WMI_DATA_HDR_IS_AMSDU(&h));
    assert(!WMI_DATA_HDR_GET_META(&h));
    assert(!WMI_DATA_HDR_GET_DEVID(&h));
    assert(h.rssi == 0 && h.info == 0);
    assert(check(123, false, false, 0, 107, false));
    assert(check(24, false, false, 0, 8, false));
    assert(check(64, false, false, 0, 8, false));
    assert(!check(24, false, false, 0, 7, false));
    assert(!check(24, false, false, 0, 9, false));
    assert(!check(123, false, false, 0, 107, true));
    assert(!check(3865, false, false, 0, 8, false));
    for (unsigned n = 0; n < 24; n++) {
        assert(!check(n, false, false, 0, 8, false));
        assert(check(n, false, true, 0, 8, false) == (n == 16));
    }
    for (unsigned n = 0; n < 34; n++)
        assert(!check(n, true, true, 1, 8, false));
    assert(check(34, true, true, 1, 8, true));
    assert(!check(3865, true, true, 1, 8, false));
    for (unsigned type = 1; type < 4; type++) {
        assert(!check(123, false, false, type, 107, false));
        assert(!check(16, false, true, type, 8, false));
    }
#else
    WMI_DATA_HDR_SET_SEQNO(&h, 17);
    WMI_DATA_HDR_SET_AMSDU(&h, 1);
    WMI_DATA_HDR_SET_META(&h, 2);
    WMI_DATA_HDR_SET_DEVID(&h, 3);
    assert(WMI_DATA_HDR_GET_SEQNO(&h) == 17);
    assert(WMI_DATA_HDR_IS_AMSDU(&h));
    assert(WMI_DATA_HDR_GET_META(&h) == 2);
    assert(WMI_DATA_HDR_GET_DEVID(&h) == 3);
#endif
    return 0;
}
"""
    with tempfile.TemporaryDirectory(prefix="nwm-data-header-") as directory:
        for target in (True, False):
            output = str(Path(directory) / ("ctr" if target else "generic"))
            command = [compiler, "-std=gnu11", "-fsanitize=address,undefined",
                       "-g", "-x", "c", "-", "-o", output]
            if target:
                command.insert(1, "-DCONFIG_ARCH_CTR")
            subprocess.run(command, input=source, text=True, check=True)
            subprocess.run([output], check=True)
    print("compiled CTR/generic ABI + actual RX bounds (ASan/UBSan): PASS")


def assert_canonical_source(patcher) -> None:
    """Verify the active build source contains the exact tested replacements."""
    contracts = (
        (patcher.WMI_H, patcher.patch_wmi_h,
         (patcher.NEW_INFO_FIELDS, patcher.NEW_STRUCT)),
        (patcher.WMI_C, patcher.patch_wmi_c,
         (patcher.NEW_DATA_ADD_DECL, patcher.NEW_SYNC_BODY)),
        (patcher.CONFIG_H, patcher.patch_config, (patcher.NEW_CONFIG,)),
        (patcher.DRIVER_C, patcher.patch_driver,
         (patcher.NEW_CSUM_PARAM, patcher.NEW_RX_META, patcher.NEW_TX_DECL,
          patcher.NEW_RX_ANCHOR, patcher.NEW_RX_PREFIX_ANCHOR)),
    )
    for path, transform, blocks in contracts:
        assert path.is_file(), f"missing canonical source: {path}; run in WSL"
        source = path.read_text()
        assert transform(source) == source, f"canonical source is stale: {path}"
        for block in blocks:
            assert block in source, f"tested source block missing from {path}"
    print("canonical source matches exact tested replacements: PASS")


def assert_patch_rejects_drift(patcher) -> None:
    for transform, broken in (
        (patcher.patch_wmi_h, patcher.OLD_STRUCT),
        (patcher.patch_wmi_h, patcher.NEW_INFO_FIELDS + patcher.OLD_STRUCT),
        (patcher.patch_wmi_c, patcher.OLD_DATA_ADD_DECL),
        (patcher.patch_config, "missing expected config"),
        (patcher.patch_driver, patcher.CONFIG_MARKER),
    ):
        try:
            transform(broken)
        except RuntimeError:
            continue
        raise AssertionError("partial/drifted patch input was accepted")
    print("missing anchors and partial patch states rejected: PASS")


def main() -> None:
    assert_capture_layout()
    assert_validator_edges()
    assert_decompilation_evidence()
    patcher = load_patcher()
    assert_source_contract(patcher)
    assert_compiled_contract(patcher)
    assert_canonical_source(patcher)
    assert_patch_rejects_drift(patcher)
    assert_pipeline_contract()
    print("ar6014_nwm_data_header: PASS")


if __name__ == "__main__":
    main()
