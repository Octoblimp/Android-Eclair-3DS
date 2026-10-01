#!/usr/bin/env python3
"""Record what the host sent the target before it asserted (A4 + W7).

Mobile Data now fails with a firmware assert, not a rejection.  Two AP attempts
in the 2026-09-01 capture produced two byte-identical target register dumps --
60 words, in which words 43-59 repeat words 2-18, i.e. two copies of one Xtensa
exception frame.  Everything after that is the driver rolling back: the host
never learns which command it was processing when it died.

The host side already tells us something.  An unknown WMI command ID produces
WMI_CMDERROR (proven 40 times over for cmd=0x0011), not an assert, so
WMI_AP_CONFIG_COMMIT's ID is very likely valid and the crash is about the
payload or the state the target was in when it arrived.  And
ar6000_ap_mode_profile_commit() sends exactly one command: the commit.  Stock
ath6kl AP bring-up first sends hidden-SSID, max-station, ACL policy, inactivity
and protected-scan-time commands, so the target may be processing a commit
against uninitialised AP state.

Recording a bounded ring of the last commands sent, and printing it from
ar6000_target_failure(), turns the next assert from "the firmware died" into
"the firmware died N ms after command 0x00xx".  The hex dump of WMI_CONNECT and
WMI_AP_CONFIG_COMMIT payloads covers the other half: the exact 52 bytes on the
wire, which no capture so far has ever shown.

Both are budgeted.  A driver that logs without a budget filled the 256 KB log
buffer in 20 s here once already.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
WMI_C = ROOT / "wmi/wmi.c"
WMI_API_H = ROOT / "include/wmi_api.h"
DRV_C = ROOT / "os/linux/ar6000_drv.c"

MARKER = "N3DS_AR6014_WMI_CMD_HISTORY"

# --- 1. prototypes -----------------------------------------------------------

API_OLD = """int wmi_cmd_send(struct wmi_t *wmip, void *osbuf, WMI_COMMAND_ID cmdId,
                      WMI_SYNC_FLAG flag);
"""

API_NEW = """int wmi_cmd_send(struct wmi_t *wmip, void *osbuf, WMI_COMMAND_ID cmdId,
                      WMI_SYNC_FLAG flag);

/* N3DS_AR6014_WMI_CMD_HISTORY: the target can assert without ever answering,
 * and the register dump it leaves behind names no command.  Every send is
 * recorded in a small ring so the assert handler can say what preceded it. */
void n3ds_wmi_history_dump(const char *why);
"""

# --- 2. the ring itself ------------------------------------------------------

RING_OLD = """/*
 * Called to send a wmi command. Command specific data is already built
 * on osbuf and current osbuf->data points to it.
 */
int
wmi_cmd_send(struct wmi_t *wmip, void *osbuf, WMI_COMMAND_ID cmdId,
               WMI_SYNC_FLAG syncflag)
{
"""

RING_NEW = """/* N3DS_AR6014_WMI_CMD_HISTORY: NWM firmware asserts on some AP-mode command
 * sequences and the resulting target register dump identifies no command at
 * all -- the two AP attempts captured on hardware produced byte-identical
 * dumps and nothing else.  Keep the last few sends in a ring so
 * ar6000_target_failure() can print what the host had just asked for.  The
 * ring is written from whatever context a command is sent in, so it takes an
 * irqsave lock and does no allocation. */
#define N3DS_WMI_HISTORY_DEPTH 16

struct n3ds_wmi_history_entry {
    u16 cmd_id;
    u16 payload_len;
    unsigned long sent_at;
};

static struct n3ds_wmi_history_entry
    n3ds_wmi_history[N3DS_WMI_HISTORY_DEPTH];
static unsigned int n3ds_wmi_history_sends;   /* total sends, monotonic */
static DEFINE_SPINLOCK(n3ds_wmi_history_lock);

static void n3ds_wmi_history_record(u16 cmd_id, u16 payload_len)
{
    unsigned long flags;

    spin_lock_irqsave(&n3ds_wmi_history_lock, flags);
    n3ds_wmi_history[n3ds_wmi_history_sends % N3DS_WMI_HISTORY_DEPTH] =
        (struct n3ds_wmi_history_entry){ cmd_id, payload_len, jiffies };
    n3ds_wmi_history_sends++;
    spin_unlock_irqrestore(&n3ds_wmi_history_lock, flags);
}

void n3ds_wmi_history_dump(const char *why)
{
    struct n3ds_wmi_history_entry snapshot[N3DS_WMI_HISTORY_DEPTH];
    unsigned int sends, depth, i;
    unsigned long flags, now = jiffies;

    spin_lock_irqsave(&n3ds_wmi_history_lock, flags);
    sends = n3ds_wmi_history_sends;
    memcpy(snapshot, n3ds_wmi_history, sizeof(snapshot));
    spin_unlock_irqrestore(&n3ds_wmi_history_lock, flags);

    depth = (sends < N3DS_WMI_HISTORY_DEPTH) ? sends : N3DS_WMI_HISTORY_DEPTH;
    printk(KERN_ERR "AR6002 WMI history (%s): %u sends, last %u\\n",
           why, sends, depth);
    /* Oldest first, so the last line is the command that was in flight. */
    for (i = depth; i > 0; i--) {
        struct n3ds_wmi_history_entry *e =
            &snapshot[(sends - i) % N3DS_WMI_HISTORY_DEPTH];

        printk(KERN_ERR "AR6002 WMI history: -%u cmd=0x%04x len=%u "
               "age=%ums\\n", i - 1, e->cmd_id, e->payload_len,
               jiffies_to_msecs(now - e->sent_at));
    }
}

/*
 * Called to send a wmi command. Command specific data is already built
 * on osbuf and current osbuf->data points to it.
 */
int
wmi_cmd_send(struct wmi_t *wmip, void *osbuf, WMI_COMMAND_ID cmdId,
               WMI_SYNC_FLAG syncflag)
{
"""

# --- 3. record + hex dump at the send point ---------------------------------

SEND_OLD = """    *(u16 *)A_NETBUF_DATA(osbuf) = (u16)cmdId;
    if (!n3ds_nwm_wmi_header_logged) {
        n3ds_nwm_wmi_header_logged = true;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 WMI: NWM u16 command/event header active\\n"));
    }
"""

SEND_NEW = """    *(u16 *)A_NETBUF_DATA(osbuf) = (u16)cmdId;
    if (!n3ds_nwm_wmi_header_logged) {
        n3ds_nwm_wmi_header_logged = true;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 WMI: NWM u16 command/event header active\\n"));
    }
    n3ds_wmi_history_record((u16)cmdId, (u16)A_NETBUF_LEN(osbuf));

    /* N3DS_AR6014_WMI_CMD_HISTORY: WMI_CONNECT has been submitted hundreds of
     * times across a dozen theories and its 52 bytes have never once been
     * read back off the wire; WMI_AP_CONFIG_COMMIT carries the same struct and
     * is what the target asserts on.  Dump both, bounded -- an unbudgeted log
     * has filled this device's 256 KB buffer in 20 s before. */
    if (cmdId == WMI_CONNECT_CMDID || cmdId == WMI_AP_CONFIG_COMMIT_CMDID) {
        static unsigned int n3ds_wmi_payload_dumps;

        if (n3ds_wmi_payload_dumps < 12) {
            u32 dump_len = A_NETBUF_LEN(osbuf);
            u8 *dump = (u8 *)A_NETBUF_DATA(osbuf);
            u32 offset;

            n3ds_wmi_payload_dumps++;
            if (dump_len > 64)
                dump_len = 64;
            for (offset = 0; offset < dump_len; offset += 16) {
                u32 chunk = dump_len - offset;
                char line[3 * 16 + 1];
                u32 b;

                if (chunk > 16)
                    chunk = 16;
                for (b = 0; b < chunk; b++)
                    snprintf(line + 3 * b, 4, "%02x ", dump[offset + b]);
                line[3 * chunk] = '\\0';
                printk(KERN_ERR "AR6002 WMI tx cmd=0x%04x +%02u: %s\\n",
                       (u16)cmdId, offset, line);
            }
        }
    }
"""

# --- 4. print the ring when the target asserts ------------------------------

FAIL_OLD = """        printk(KERN_ERR "ar6000_target_failure: target asserted \\n");
"""

FAIL_NEW = """        printk(KERN_ERR "ar6000_target_failure: target asserted \\n");

        /* N3DS_AR6014_WMI_CMD_HISTORY: the register dump below names no
         * command, so print what the host had just sent first -- the last
         * line of the ring is the command that was in flight. */
        n3ds_wmi_history_dump("target assert");
"""

HUNKS = (
    (WMI_API_H, "history prototype", API_OLD, API_NEW),
    (WMI_C, "history ring", RING_OLD, RING_NEW),
    (WMI_C, "send-point record + payload dump", SEND_OLD, SEND_NEW),
    (DRV_C, "assert-time dump", FAIL_OLD, FAIL_NEW),
)


def patch_text(path: Path, text: str) -> str:
    """Apply this patch's hunks for one file.  Idempotent."""
    if MARKER in text:
        return text
    for target, name, old, new in HUNKS:
        if target != path:
            continue
        assert text.count(old) == 1, (
            f"{path.name}/{name}: expected exactly one match, "
            f"found {text.count(old)}")
        text = text.replace(old, new)
    return text


def main() -> None:
    touched = False
    for path in (WMI_API_H, WMI_C, DRV_C):
        original = path.read_text(encoding="utf-8")
        patched = patch_text(path, original)
        if patched == original:
            print(f"ar6014_wmi_cmd_history: already applied to {path.name}")
            continue
        path.write_text(patched, encoding="utf-8")
        print(f"ar6014_wmi_cmd_history: patched {path}")
        touched = True
    if not touched:
        print("ar6014_wmi_cmd_history: nothing to do")


if __name__ == "__main__":
    main()
