#!/usr/bin/env python3
"""Keep verbose successful CMD53 tracing available but off by default."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


SOURCE = Path(
    f"{A3DS_ROOT}/third_party/linux/drivers/platform/"
    "nintendo3ds/ctr_sdhc.c"
)
MARKER = "N3DS_SDHC_CMD53_TRACE_CONTROL"

PARAM_ANCHOR = '''MODULE_PARM_DESC(pio_inline_max,
                 "largest FIFO block copied in hard IRQ context");
'''

PARAM_BLOCK = PARAM_ANCHOR + '''
/* N3DS_SDHC_CMD53_TRACE_CONTROL: successful per-request transport logging is
 * useful for controller bring-up but floods the visible console and adds I/O
 * to the firmware bootstrap.  Keep it opt-in; timeout and error reports below
 * remain unconditional. */
static bool cmd53_success_trace;
module_param(cmd53_success_trace, bool, 0644);
MODULE_PARM_DESC(cmd53_success_trace,
                 "trace the first 64 successful AR6014 CMD53 requests");
'''

ACTIVATION_OLD = '''	host->transport_trace_active = false;
	if (mrq->cmd && mrq->cmd->opcode == SD_IO_RW_EXTENDED &&
	    host->transport_trace_count < 64) {
'''

ACTIVATION_NEW = '''	host->transport_trace_active = false;
	if (cmd53_success_trace && mrq->cmd &&
	    mrq->cmd->opcode == SD_IO_RW_EXTENDED &&
	    host->transport_trace_count < 64) {
'''

ERROR_OLD = '''			if (host->transport_trace_active)
				dev_info(host->dev,
					 "AR6002 SDHC CMD53 error seq=%u status=%08x error=%d\\n",
					 host->transport_trace_active_seq,
					 int_reg, error);
'''

ERROR_NEW = '''			if (host->cmd &&
			    host->cmd->opcode == SD_IO_RW_EXTENDED)
				dev_err(host->dev,
					"AR6002 SDHC CMD53 error status=%08x error=%d\\n",
					int_reg, error);
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_source(text: str) -> str:
    if MARKER in text:
        return text
    text = replace_once(text, PARAM_ANCHOR, PARAM_BLOCK, "trace parameter")
    text = replace_once(text, ACTIVATION_OLD, ACTIVATION_NEW, "trace activation")
    return replace_once(text, ERROR_OLD, ERROR_NEW, "CMD53 error reporting")


def main() -> None:
    original = SOURCE.read_text(encoding="utf-8")
    patched = patch_source(original)
    if patched != original:
        SOURCE.write_text(patched, encoding="utf-8")
        print("ctr_sdhc_trace_control: patched")
    else:
        print("ctr_sdhc_trace_control: already patched")


if __name__ == "__main__":
    main()
