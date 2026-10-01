#!/usr/bin/env python3
"""Keep ARM9 PXI responsive while servicing the single SD virtqueue."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(A3DS_ROOT)
MANAGER = ROOT / "third_party/arm9linuxfw/source/virt/manager.c"
MANAGER_H = ROOT / "third_party/arm9linuxfw/include/virt/manager.h"
QUEUE = ROOT / "third_party/arm9linuxfw/source/virt/queue.c"
SDCARD = ROOT / "third_party/arm9linuxfw/source/vdev/sdcard.c"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


manager = MANAGER.read_text()
if "N3DS_PXI_INTERRUPTIBLE_DEVICE_WORK" not in manager:
    manager = replace_once(manager, r'''bool vman_process_pending(void)
{
	bool ret = true;
	vqueue_s *vq;
	list_node_s *next_vq;

	CRITICAL_BLOCK(
		if (list_empty(&vq_pending)) {
			// no queues left to process
			// let the system sleep a bit
			ret = false;
			break;
		}

		next_vq = list_head(&vq_pending);
		list_remove(next_vq);

		vq = CONTAINER_OF(next_vq, vqueue_s, node);

		// alert the device that there MIGHT be pending
		// descriptors in this virtqueue
		vdev_process_vqueue(vqueue_owner(vq), vq);
	);

	return ret;
}

bool vman_add_pending(vqueue_s *vq)
{
	return list_append_if_not_embedded(&vq->node, &vq_pending);
}
''', r'''/* N3DS_PXI_INTERRUPTIBLE_DEVICE_WORK: IRQs are masked only while
 * unlinking or linking a pending-list node. SD PIO must not starve PXI RX. */
bool vman_process_pending(void)
{
	bool have_work = false;
	vqueue_s *vq = NULL;

	CRITICAL_BLOCK(
		if (!list_empty(&vq_pending)) {
			list_node_s *next_vq = list_head(&vq_pending);
			list_remove(next_vq);
			vq = CONTAINER_OF(next_vq, vqueue_s, node);
			have_work = true;
		}
	);

	if (have_work)
		vdev_process_vqueue(vqueue_owner(vq), vq);
	return have_work;
}

bool vman_add_pending(vqueue_s *vq)
{
	bool added;
	CRITICAL_BLOCK(
		added = list_append_if_not_embedded(&vq->node, &vq_pending);
	);
	return added;
}
''', "interruptible device work")
MANAGER.write_text(manager)


manager_h = MANAGER_H.read_text()
if "N3DS_VIRQ_SHORT_CRITICAL_NOTIFY" not in manager_h:
    manager_h = replace_once(manager_h, r'''static inline void vman_notify_host(vdev_s *vdev, uint mode) {
	virtirq_set(vdev_id(vdev), mode);
	virtirq_sync();
}''', r'''/* N3DS_VIRQ_SHORT_CRITICAL_NOTIFY: virtirq_set() requires its shared
 * bitmap update to run atomically. Keep only that notification critical. */
static inline void vman_notify_host(vdev_s *vdev, uint mode) {
	CRITICAL_BLOCK(
		virtirq_set(vdev_id(vdev), mode);
		virtirq_sync();
	);
}''', "short critical host notification")
MANAGER_H.write_text(manager_h)


queue = QUEUE.read_text()
if "N3DS_VQUEUE_SHORT_CRITICAL_SECTIONS" not in queue:
    start = queue.index("int vqueue_fetch_avail_first(")
    queue = queue[:start] + r'''/* N3DS_VQUEUE_SHORT_CRITICAL_SECTIONS: update shared ring metadata
 * atomically, then restore IRQs before device I/O. */
/* N3DS_VIRTQUEUE_16BIT_WRAP: avail_idx/used_idx remain monotonic u16
 * counters and are masked only when indexing the power-of-two ring. */
int vqueue_fetch_avail_first(vqueue_s *vq)
{
	u32 sr = arm_enter_critical();
	const vqAvail_s *vqA = (const vqAvail_s*)vq->q_avail;
	int result = -1;

	if (vq->ready && vq->avail_idx != vqA->last) {
		uint index = vq->avail_idx & vq->size_mask;
		vq->avail_idx++;
		result = vqA->ring[index];
	}
	arm_leave_critical(sr);
	return result;
}

int vqueue_fetch_avail_next(vqueue_s *vq, u16 prev)
{
	u32 sr = arm_enter_critical();
	const vqDesc_s *vqD = (const vqDesc_s*)vq->q_desc;
	int result = (vqD[prev].flags & VQ_DESC_F_NEXT) ? vqD[prev].next : -1;
	arm_leave_critical(sr);
	return result;
}

void vqueue_push_used(vqueue_s *vq, u16 first, u32 len)
{
	u32 sr = arm_enter_critical();
	vqUsed_s *vqU = (vqUsed_s*)vq->q_used;
	unsigned index = vq->used_idx & vq->size_mask;

	vqU->ring[index].id = first;
	vqU->ring[index].len = len;
	arm_sync_barrier();
	vq->used_idx++;
	vqU->last++;
	arm_sync_barrier();
	arm_leave_critical(sr);
}

void vqueue_get_desc(vqueue_s *vq, u16 index, vdesc_s *desc)
{
	u32 sr = arm_enter_critical();
	const vqDesc_s *vqD = (const vqDesc_s*)vq->q_desc;

	if (index <= vq->size_mask) {
		desc->data = (u8*)((u32)vqD[index].addr);
		desc->length = vqD[index].len;
		desc->dir = (vqD[index].flags & VQ_DESC_F_WRITE) ?
			VDEV_TO_HOST : HOST_TO_VDEV;
	} else {
		desc->data = NULL;
	}
	arm_leave_critical(sr);
}
'''
if "N3DS_VIRTQUEUE_16BIT_WRAP" not in queue:
    queue = replace_once(queue,
        "/* N3DS_VQUEUE_SHORT_CRITICAL_SECTIONS: update shared ring metadata\n"
        " * atomically, then restore IRQs before device I/O. */",
        "/* N3DS_VQUEUE_SHORT_CRITICAL_SECTIONS: update shared ring metadata\n"
        " * atomically, then restore IRQs before device I/O. */\n"
        "/* N3DS_VIRTQUEUE_16BIT_WRAP: avail_idx/used_idx remain monotonic u16\n"
        " * counters and are masked only when indexing the power-of-two ring. */",
        "16-bit virtqueue wrap marker")
QUEUE.write_text(queue)


sdcard = SDCARD.read_text()
if "N3DS_SD_ONE_REQUEST_PER_PASS" not in sdcard:
    sdcard = replace_once(sdcard, '''static void sdmc_process_vqueue(vdev_s *vdev, vqueue_s *vq)
{
	vjob_s vjob;

	while (vqueue_fetch_job_new(vq, &vjob) >= 0) {''', '''/* N3DS_SD_ONE_REQUEST_PER_PASS: return to the IRQ-capable main loop
 * between block requests instead of draining an unbounded batch. */
static void sdmc_process_vqueue(vdev_s *vdev, vqueue_s *vq)
{
	vjob_s vjob;
	bool processed = false;

	if (vqueue_fetch_job_new(vq, &vjob) >= 0) {
		processed = true;''', "one request entry")
    sdcard = replace_once(sdcard, '''		vqueue_push_job(vq, &vjob);
	}

	vman_notify_host(vdev, VIRQ_VQUEUE);
}''', '''		vqueue_push_job(vq, &vjob);
	}

	/* One harmless empty follow-up pass avoids consuming a descriptor just
	 * to test whether more work exists. */
	if (processed)
		vman_add_pending(vq);
	vman_notify_host(vdev, VIRQ_VQUEUE);
}''', "one request exit")
SDCARD.write_text(sdcard)

for path, marker in ((MANAGER, "N3DS_PXI_INTERRUPTIBLE_DEVICE_WORK"),
                     (MANAGER_H, "N3DS_VIRQ_SHORT_CRITICAL_NOTIFY"),
                     (QUEUE, "N3DS_VQUEUE_SHORT_CRITICAL_SECTIONS"),
                     (SDCARD, "N3DS_SD_ONE_REQUEST_PER_PASS")):
    if marker not in path.read_text():
        raise SystemExit(f"missing {marker} in {path}")

print("patch_arm9_pxi_fairness: IRQ-capable bounded SD queue passes enabled")
