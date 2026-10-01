#!/usr/bin/env python3
"""Focused source regression for the #233 PICA200 completion failure."""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

from pathlib import Path
import runpy


ROOT = Path(A3DS_ROOT)
SRC = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
PATCH = Path(
    f"{A3DS_WIN}/"
    "scripts/patch_pica200_deferred_qualify.py"
)

text = SRC.read_text()


def require(token: str) -> None:
    assert token in text, f"missing PICA completion contract: {token}"


for token in (
    "N3DS_PICA_P3D_IRQ_ACK",
    "pica_write(pica, PICA_REG_IRQ_ACK, 0);",
    "N3DS_PICA_COMPLETION_IDLE_POLL",
    "while (pica_read(pica, PICA_REG_BUSY) & PICA_BUSY_P3D)",
    "N3DS_PICA_SINGLE_DEFERRED_QUALIFY",
    "N3DS_PICA_WATCHDOG_BEFORE_MMIO",
    "PICA200 completion irq=%u busy=%08x jump=%08x",
    "cancel_delayed_work_sync(&pica->qualify_work);",
):
    require(token)

for retired in (
    "N3DS_PICA_IRQ_STORM_BREAK",
    "PICA_CLOCK_LCD_ONLY",
    "qualify_retries",
    "retry in 2s",
    "else if (pica_read(pica, PICA_REG_CMD_START) & 1)",
):
    assert retired not in text, f"retired PICA behavior survived: {retired}"

irq_start = text.index("static irqreturn_t ctr_pica_p3d_irq")
irq_end = text.index("static irqreturn_t ctr_pica_ppf_irq", irq_start)
irq = text[irq_start:irq_end]
assert irq.index("pica_ack_p3d_irq(pica);") < irq.index(
    "atomic_read(&pica->submission_armed)"
)
assert irq.count("return IRQ_HANDLED;") == 2

qualify_start = text.index("int ctr_pica_qualify(struct ctr_pica *pica)\n{")
qualify_end = text.index("static int ctr_pica_probe", qualify_start)
qualify = text[qualify_start:qualify_end]
ordered = (
    "mutex_lock(&pica->submit_lock);",
    "pica_watchdog_arm_cpu0",
    "pica_prepare_gx_locked(pica)",
    "devm_request_irq",
    "pica_write(pica, PICA_REG_CMD_START, 1);",
    "wait_event_timeout",
    "pica_wait_p3d_idle",
    "pica_watchdog_disarm_cpu0",
)
positions = [qualify.index(token) for token in ordered]
assert positions == sorted(positions), "qualification order regression"

worker_start = text.index("static void pica_qualify_work_fn")
worker_end = text.index("N3DS_PICA_PROBE_SELFTEST", worker_start)
worker = text[worker_start:worker_end]
assert worker.count("ctr_pica_qualify(pica)") == 1
assert "schedule_delayed_work" not in worker

# The real patch must itself be idempotent on canonical generated source.
try:
    runpy.run_path(str(PATCH), run_name="__main__")
except SystemExit as exc:
    assert exc.code in (None, 0), f"idempotent patch exited {exc.code}"
assert SRC.read_text() == text, "second PICA patch application changed source"

print("test_pica200_completion_contract: PASS")
