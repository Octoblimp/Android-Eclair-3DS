#!/usr/bin/env python3
"""Install the first hardware-evidenced PICA200 completion contract.

Build #233 proved that the first FINALIZE command raises P3D, but the driver
did not acknowledge the level-high source. It then rejected the completion
by sampling CMDBUF_JUMP0 immediately and deliberately returned IRQ_NONE for
the still-asserted line. Linux consequently entered its "nobody cared"
path, and later retries timed out.

The direct-hardware libn3ds contract is simpler: write zero to GPUREG_IRQ_ACK,
wait for the P3D busy/status bit to clear, then start the next command list.
This patch follows that contract, keeps every risky qualification MMIO access
inside the existing CPU0 watchdog window, and performs one delayed attempt.
No retry is allowed after a quarantining failure.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PICA_C = Path(
    f"{A3DS_ROOT}/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
)

FINAL_MARKERS = (
    "N3DS_PICA_P3D_IRQ_ACK",
    "N3DS_PICA_COMPLETION_IDLE_POLL",
    "N3DS_PICA_SINGLE_DEFERRED_QUALIFY",
    "N3DS_PICA_WATCHDOG_BEFORE_MMIO",
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"ctr_pica.c: expected one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def verify(text: str) -> None:
    missing = [marker for marker in FINAL_MARKERS if marker not in text]
    if missing:
        raise SystemExit(f"ctr_pica.c: missing final markers: {', '.join(missing)}")
    forbidden = (
        "N3DS_PICA_IRQ_STORM_BREAK",
        "PICA_CLOCK_LCD_ONLY",
        "qualify_retries",
        "retry in 2s",
    )
    present = [token for token in forbidden if token in text]
    if present:
        raise SystemExit(f"ctr_pica.c: retired behavior survived: {', '.join(present)}")

    irq = text.index("static irqreturn_t ctr_pica_p3d_irq")
    irq_end = text.index("static irqreturn_t ctr_pica_ppf_irq", irq)
    irq_body = text[irq:irq_end]
    if irq_body.index("pica_ack_p3d_irq(pica);") > irq_body.index(
        "atomic_read(&pica->submission_armed)"
    ):
        raise SystemExit("ctr_pica.c: P3D IRQ is not acknowledged before stale check")

    qualify = text.index("int ctr_pica_qualify(struct ctr_pica *pica)\n{")
    qualify_end = text.index("static int ctr_pica_probe", qualify)
    qualify_body = text[qualify:qualify_end]
    order = (
        "mutex_lock(&pica->submit_lock);",
        "pica_watchdog_arm_cpu0",
        "pica_prepare_gx_locked(pica)",
        "devm_request_irq",
        "pica_write(pica, PICA_REG_CMD_START, 1);",
        "wait_event_timeout",
        "pica_wait_p3d_idle",
    )
    offsets = [qualify_body.index(token) for token in order]
    if offsets != sorted(offsets):
        raise SystemExit("ctr_pica.c: qualification safety/completion order is wrong")


text = PICA_C.read_text()
if all(marker in text for marker in FINAL_MARKERS):
    verify(text)
    print("patch_pica200_deferred_qualify: already applied and verified")
    raise SystemExit(0)

if "N3DS_PICA_DEFERRED_QUALIFY" in text or "N3DS_PICA_IRQ_STORM_BREAK" in text:
    raise SystemExit(
        "ctr_pica.c: obsolete deferred patch layout detected; run "
        "add_pica200_driver.py once to regenerate the authoritative base"
    )

text = replace_once(
    text,
    "#define PICA_REG_INIT_1000          0x1000",
    "#define PICA_REG_IRQ_ACK            0x1000",
    "IRQ ACK register",
)
text = replace_once(
    text,
    "#define PICA_CLOCK_LCD_ONLY         0x00000100\n",
    "",
    "retired LCD-only clock gate",
)

text = replace_once(
    text,
    "\tbool wedged;\n\tbool qualified;\n};",
    "\tbool wedged;\n"
    "\tbool qualified;\n"
    "\t/* N3DS_PICA_SINGLE_DEFERRED_QUALIFY */\n"
    "\tstruct delayed_work qualify_work;\n"
    "};",
    "struct tail",
)

helpers_anchor = "static void pica_free_buffer(struct ctr_pica_file *file,\n"
helpers = r'''/* N3DS_PICA_P3D_IRQ_ACK
 * P3D is a level-high interrupt. libn3ds acknowledges the previous P3D
 * completion by writing zero to GPUREG_IRQ_ACK before looking at status or
 * starting another list. Flush the posted write with a safe external-status
 * read so the GIC line can deassert before this handler returns. */
static void pica_ack_p3d_irq(struct ctr_pica *pica)
{
	pica_write(pica, PICA_REG_IRQ_ACK, 0);
	wmb();
	(void)pica_read(pica, PICA_REG_BUSY);
}

/* N3DS_PICA_COMPLETION_IDLE_POLL
 * The command jump register is a trigger, not the interrupt acknowledge.
 * Completion is a fresh P3D IRQ followed by the documented P3D busy bit
 * becoming idle. Give posted GPU state up to 10 ms to converge after IRQ. */
static int pica_wait_p3d_idle(struct ctr_pica *pica)
{
	unsigned int tries = 1000;

	while (pica_read(pica, PICA_REG_BUSY) & PICA_BUSY_P3D) {
		if (!--tries)
			return -ETIMEDOUT;
		udelay(10);
	}
	return 0;
}

'''
if helpers_anchor not in text:
    raise SystemExit("ctr_pica.c: helper insertion anchor not found")
text = text.replace(helpers_anchor, helpers + helpers_anchor, 1)

old_irq = r'''static irqreturn_t ctr_pica_p3d_irq(int irq, void *data)
{
	struct ctr_pica *pica = data;

	/* A stale edge must never qualify the engine. */
	if (!atomic_read(&pica->submission_armed))
		return IRQ_NONE;
	atomic_set(&pica->irq_seen, 1);
	atomic64_inc(&pica->completed);
	wake_up_all(&pica->wait);
	return IRQ_HANDLED;
}'''
new_irq = r'''static irqreturn_t ctr_pica_p3d_irq(int irq, void *data)
{
	struct ctr_pica *pica = data;

	/* The source is level-high: acknowledge it even when it is stale. */
	pica_ack_p3d_irq(pica);
	if (!atomic_read(&pica->submission_armed))
		return IRQ_HANDLED;
	atomic_set(&pica->submission_armed, 0);
	atomic_set(&pica->irq_seen, 1);
	atomic64_inc(&pica->completed);
	wake_up_all(&pica->wait);
	return IRQ_HANDLED;
}'''
text = replace_once(text, old_irq, new_irq, "P3D IRQ handler")

old_submit_completion = r'''	if (waited == 0) {
		pica_recover_locked(pica, -ETIMEDOUT);
		ret = -ETIMEDOUT;
	} else if (waited < 0) {
		pica_recover_locked(pica, waited);
		ret = waited;
	} else if (pica_read(pica, PICA_REG_CMD_START) & 1) {
		pica_recover_locked(pica, -EIO);
		ret = -EIO;
	} else {
		atomic_set(&pica->last_error, 0);
		request.sequence = atomic64_read(&pica->completed);
		ret = copy_to_user((void __user *)arg, &request, sizeof(request)) ?
			-EFAULT : 0;
	}'''
new_submit_completion = r'''	if (waited == 0) {
		pica_recover_locked(pica, -ETIMEDOUT);
		ret = -ETIMEDOUT;
	} else if (waited < 0) {
		pica_recover_locked(pica, waited);
		ret = waited;
	} else {
		ret = pica_wait_p3d_idle(pica);
		if (ret) {
			pica_recover_locked(pica, ret);
		} else {
			atomic_set(&pica->last_error, 0);
			request.sequence = atomic64_read(&pica->completed);
			ret = copy_to_user((void __user *)arg, &request,
					   sizeof(request)) ? -EFAULT : 0;
		}
	}'''
text = replace_once(
    text, old_submit_completion, new_submit_completion, "submit completion"
)

qualify_anchor = "/* N3DS_PICA_PROBE_SELFTEST: explicit post-boot qualification."
deferred_block = r'''/* Prepare inherited GX state without gating the clock that feeds the live LCD
 * path. This function is called with submit_lock held and the watchdog armed. */
static int pica_prepare_gx_locked(struct ctr_pica *pica)
{
	int ret;

	pica_write(pica, PICA_REG_CLOCK, PICA_CLOCK_ALL);
	wmb();
	msleep(10);
	pica_write(pica, PICA_REG_PPF_CONTROL,
		   pica_read(pica, PICA_REG_PPF_CONTROL) & ~0x0000ff00);
	pica_write(pica, PICA_REG_PSC0_CONTROL,
		   pica_read(pica, PICA_REG_PSC0_CONTROL) & ~0x000000ff);
	pica_write(pica, PICA_REG_PSC1_CONTROL,
		   pica_read(pica, PICA_REG_PSC1_CONTROL) & ~0x000000ff);
	pica_ack_p3d_irq(pica);
	ret = pica_wait_p3d_idle(pica);
	if (ret)
		dev_err(pica->dev,
			"PICA200 inherited P3D state stayed busy: busy=%08x jump=%08x\n",
			pica_read(pica, PICA_REG_BUSY),
			pica_read(pica, PICA_REG_CMD_START));
	return ret;
}

int ctr_pica_qualify(struct ctr_pica *pica);
static void pica_qualify_work_fn(struct work_struct *work)
{
	struct ctr_pica *pica =
		container_of(to_delayed_work(work), struct ctr_pica, qualify_work);
	int ret;

	if (READ_ONCE(pica->qualified))
		return;
	dev_info(pica->dev, "PICA200 single deferred qualification attempt\n");
	ret = ctr_pica_qualify(pica);
	if (ret)
		dev_err(pica->dev,
			"PICA200 qualification failed (%d); software fallback active until reboot\n",
			ret);
	else
		dev_info(pica->dev, "PICA200 deferred qualification: PASS\n");
}

'''
if qualify_anchor not in text:
    raise SystemExit("ctr_pica.c: qualification insertion anchor not found")
text = text.replace(qualify_anchor, deferred_block + qualify_anchor, 1)

old_qualify_start = r'''	mutex_lock(&pica->submit_lock);
	watchdog_ret = work_on_cpu(0, pica_watchdog_arm_cpu0, pica);
	if (watchdog_ret) {
		ret = watchdog_ret;
		goto out_unlock;
	}
	/* N3DS_PICA_LAZY_IRQ_ENABLE: merely booting the kernel must not enable a
	 * potentially stale GPU interrupt.  Enable P3D only inside the watchdog-
	 * bounded qualification window. */
	if (!pica->irq_registered) {'''
new_qualify_start = r'''	mutex_lock(&pica->submit_lock);
	/* N3DS_PICA_WATCHDOG_BEFORE_MMIO: inherited GX state is untrusted. */
	watchdog_ret = work_on_cpu(0, pica_watchdog_arm_cpu0, pica);
	if (watchdog_ret) {
		ret = watchdog_ret;
		goto out_unlock;
	}
	ret = pica_prepare_gx_locked(pica);
	if (ret) {
		pica_recover_locked(pica, ret);
		goto out_disarm;
	}
	/* N3DS_PICA_LAZY_IRQ_ENABLE: the stale source was acknowledged above;
	 * only the watchdog-bounded qualification window owns the P3D line. */
	if (!pica->irq_registered) {'''
text = replace_once(text, old_qualify_start, new_qualify_start, "qualify start")

text = replace_once(
    text,
    "\tpica_write(pica, PICA_REG_INIT_1000, 0);",
    "\tpica_ack_p3d_irq(pica);",
    "qualification IRQ ACK write",
)

old_qualify_completion = r'''	atomic_set(&pica->submission_armed, 0);
	if (!waited || !atomic_read(&pica->irq_seen) ||
	    (pica_read(pica, PICA_REG_CMD_START) & 1)) {
		ret = waited ? -EIO : -ETIMEDOUT;
		pica_recover_locked(pica, ret);
		dev_err(pica->dev, "PICA200_PROBE FAIL error=%d\n", ret);
	} else {
		WRITE_ONCE(pica->stage, 5);
		WRITE_ONCE(pica->qualified, true);
		dev_info(pica->dev, "PICA200_PROBE PASS P3D sequence=%llu dma=%08x\n",
			 (unsigned long long)atomic64_read(&pica->completed),
			 lower_32_bits(dma));
	}'''
new_qualify_completion = r'''	atomic_set(&pica->submission_armed, 0);
	if (!waited || !atomic_read(&pica->irq_seen)) {
		ret = -ETIMEDOUT;
	} else {
		ret = pica_wait_p3d_idle(pica);
	}
	dev_info(pica->dev,
		 "PICA200 completion irq=%u busy=%08x jump=%08x\n",
		 atomic_read(&pica->irq_seen), pica_read(pica, PICA_REG_BUSY),
		 pica_read(pica, PICA_REG_CMD_START));
	if (ret) {
		pica_recover_locked(pica, ret);
		dev_err(pica->dev, "PICA200_PROBE FAIL error=%d stage=%u\n",
			ret, READ_ONCE(pica->stage));
	} else {
		WRITE_ONCE(pica->stage, 5);
		WRITE_ONCE(pica->qualified, true);
		atomic_set(&pica->last_error, 0);
		dev_info(pica->dev, "PICA200_PROBE PASS P3D sequence=%llu dma=%08x\n",
			 (unsigned long long)atomic64_read(&pica->completed),
			 lower_32_bits(dma));
	}'''
text = replace_once(
    text,
    old_qualify_completion,
    new_qualify_completion,
    "qualification completion",
)

old_probe = r'''	/* N3DS_PICA_ENFORCED_BOOT_MMIO: probe performs qualification synchronously. */
	dev_info(&pdev->dev, "PICA200 P3D irq=%d, running boot qualification; watchdog=%s\n",
		 pica->irq_p3d, pica->watchdog_regs ? "ready" : "missing");
	ret = ctr_pica_qualify(pica);
	if (ret)
		dev_err(&pdev->dev, "Boot qualification failed: %d\n", ret);
	return 0;'''
new_probe = r'''	/* N3DS_PICA_SINGLE_DEFERRED_QUALIFY: one attempt after early boot. */
	dev_info(&pdev->dev,
		 "PICA200 P3D irq=%d, watchdog=%s; single qualification deferred 3 s\n",
		 pica->irq_p3d, pica->watchdog_regs ? "ready" : "missing");
	INIT_DELAYED_WORK(&pica->qualify_work, pica_qualify_work_fn);
	schedule_delayed_work(&pica->qualify_work, msecs_to_jiffies(3000));
	return 0;'''
text = replace_once(text, old_probe, new_probe, "probe qualification")

old_remove = "static int ctr_pica_remove(struct platform_device *pdev)\n{\n\tstruct ctr_pica *pica = platform_get_drvdata(pdev);\n\n\tmisc_deregister(&pica->misc);"
new_remove = "static int ctr_pica_remove(struct platform_device *pdev)\n{\n\tstruct ctr_pica *pica = platform_get_drvdata(pdev);\n\n\tcancel_delayed_work_sync(&pica->qualify_work);\n\tmisc_deregister(&pica->misc);"
text = replace_once(text, old_remove, new_remove, "remove cancellation")

verify(text)
PICA_C.write_text(text)
print("patch_pica200_deferred_qualify: single-attempt IRQ ACK repair applied")
