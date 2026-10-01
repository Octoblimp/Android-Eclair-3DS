"""Identify the unhandled WMI events NWM keeps sending, and stop them flooding.

The build-#254 capture carries 77 ``Unknown id 0x1025`` lines in four bursts,
one burst per association, on a strict ~306 ms cadence that starts ~0.3 s after
each association and stops exactly at each disconnect.  306 ms is 3 x a 100 ms
beacon period, i.e. DTIM 3 -- so whatever 0x1025 is, the target emits it once
per DTIM while associated and never otherwise.

In our host's event enum 0x1025 is WMI_ACL_DATA_EVENTID (Bluetooth co-existence
data), which cannot be what an NWM Wi-Fi-only target means by it.  The payload
has never been looked at.  This patch dumps up to 32 bytes of the first three
occurrences of each distinct unhandled id, then suppresses the per-event print
and reports a running total on power-of-two boundaries only -- the stock print
is unbounded and is a large part of what the user sees as "unknown ID errors".

It also logs the WMI_CONNECT_EVENT's own length.  If that length exceeds the
20-byte header, NWM is appending association IEs while reporting both IE
lengths as zero, and they can be recovered; if it is exactly 20, there are no
IEs to recover and N3DS_AR6014_ASSOC_IE_FIXUP's stashed copy is the only source.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/wmi/wmi.c"

MARKER = "N3DS_AR6014_WMI_UNKNOWN_EVENT_DUMP"

HELPER_OLD = r"""/*
 * WMI Extended Event received from Target.
 */
int
wmi_control_rx_xtnd(struct wmi_t *wmip, void *osbuf)
"""

HELPER_NEW = r"""/* N3DS_AR6014_WMI_UNKNOWN_EVENT_DUMP: stock ath6kl prints one unbounded line
 * per unhandled event id and nothing about its contents, which on this target
 * means 77 identical lines per boot that say nothing.  Dump the first few
 * payloads of each distinct id instead, then go quiet. */
#define N3DS_WMI_UNKNOWN_IDS      8
#define N3DS_WMI_UNKNOWN_DUMPS    3
#define N3DS_WMI_UNKNOWN_BYTES    32

static u16 n3ds_wmi_unknown_id[N3DS_WMI_UNKNOWN_IDS];
static u32 n3ds_wmi_unknown_seen[N3DS_WMI_UNKNOWN_IDS];
static u8  n3ds_wmi_unknown_used;

static void
n3ds_wmi_unknown_event(const char *path, u16 id, u8 *datap, u32 len)
{
    char line[3 * N3DS_WMI_UNKNOWN_BYTES + 1];
    u32 dump_len;
    u32 slot;
    u32 b;

    for (slot = 0; slot < n3ds_wmi_unknown_used; slot++) {
        if (n3ds_wmi_unknown_id[slot] == id)
            break;
    }
    if (slot == n3ds_wmi_unknown_used) {
        if (n3ds_wmi_unknown_used == N3DS_WMI_UNKNOWN_IDS)
            return;
        n3ds_wmi_unknown_id[slot] = id;
        n3ds_wmi_unknown_seen[slot] = 0;
        n3ds_wmi_unknown_used++;
    }

    n3ds_wmi_unknown_seen[slot]++;

    if (n3ds_wmi_unknown_seen[slot] > N3DS_WMI_UNKNOWN_DUMPS) {
        u32 seen = n3ds_wmi_unknown_seen[slot];

        /* powers of two only: 4, 8, 16, ... -- enough to see the cadence
         * without the flood */
        if ((seen & (seen - 1)) == 0)
            printk(KERN_ERR "AR6002 WMI unknown %s id=0x%04x seen=%u "
                   "(payload dump suppressed)\n", path, id, seen);
        return;
    }

    dump_len = (len > N3DS_WMI_UNKNOWN_BYTES) ? N3DS_WMI_UNKNOWN_BYTES : len;
    for (b = 0; b < dump_len; b++)
        snprintf(line + 3 * b, 4, "%02x ", datap[b]);
    line[3 * dump_len] = '\0';

    printk(KERN_ERR "AR6002 WMI unknown %s id=0x%04x #%u len=%u: %s\n",
           path, id, n3ds_wmi_unknown_seen[slot], len, line);
}

/*
 * WMI Extended Event received from Target.
 */
int
wmi_control_rx_xtnd(struct wmi_t *wmip, void *osbuf)
"""

XTND_OLD = r"""#endif /* CONFIG_TARGET_PROFILE_SUPPORT */
    default:
        A_DPRINTF(DBG_WMI|DBG_ERROR,
            (DBGFMT "Unknown id 0x%x\n", DBGARG, id));
"""

XTND_NEW = r"""#endif /* CONFIG_TARGET_PROFILE_SUPPORT */
    default:
        /* N3DS_AR6014_WMI_UNKNOWN_EVENT_DUMP */
        n3ds_wmi_unknown_event("xtnd", id, datap, len);
"""

MAIN_OLD = r"""        status = wmi_wapi_rekey_event_rx(wmip, datap, len);
        break;
#endif
    default:
        A_DPRINTF(DBG_WMI|DBG_ERROR,
            (DBGFMT "Unknown id 0x%x\n", DBGARG, id));
"""

MAIN_NEW = r"""        status = wmi_wapi_rekey_event_rx(wmip, datap, len);
        break;
#endif
    default:
        /* N3DS_AR6014_WMI_UNKNOWN_EVENT_DUMP */
        n3ds_wmi_unknown_event("ctrl", id, datap, len);
"""

EVTLEN_OLD = r"""    ev = (WMI_CONNECT_EVENT *)datap;

    A_DPRINTF(DBG_WMI,
"""

EVTLEN_NEW = r"""    ev = (WMI_CONNECT_EVENT *)datap;

    /* N3DS_AR6014_WMI_UNKNOWN_EVENT_DUMP: the event's own length settles
     * whether NWM appends association IEs that it then reports as
     * zero-length.  len > sizeof(WMI_CONNECT_EVENT) means they are there to be
     * recovered; len == sizeof() means there are none. */
    {
        static unsigned int n3ds_connect_evt_dumps;

        if (n3ds_connect_evt_dumps < 4) {
            n3ds_connect_evt_dumps++;
            printk(KERN_ERR "AR6002 WMI connect evt len=%d hdr=%u "
                   "beaconIeLen=%u assocReqLen=%u assocRespLen=%u\n",
                   len, (unsigned int)sizeof(WMI_CONNECT_EVENT),
                   ev->beaconIeLen, ev->assocReqLen, ev->assocRespLen);
        }
    }

    A_DPRINTF(DBG_WMI,
"""

HUNKS = (
    ("unknown-event dump helper", HELPER_OLD, HELPER_NEW),
    ("extended-event unknown id", XTND_OLD, XTND_NEW),
    ("control-event unknown id", MAIN_OLD, MAIN_NEW),
    ("connect-event length", EVTLEN_OLD, EVTLEN_NEW),
)


def patch_wmi(text):
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, "%s: expected exactly one anchor, found %d" % (
            name,
            text.count(old),
        )
        text = text.replace(old, new)
    return text


def main():
    text = TARGET.read_text()
    patched = patch_wmi(text)
    if patched == text:
        print("patch_ar6014_wmi_unknown_event_dump: already applied")
        return
    TARGET.write_text(patched)
    print("patch_ar6014_wmi_unknown_event_dump: applied to %s" % TARGET)


if __name__ == "__main__":
    main()
