#!/usr/bin/env python3
"""Repair the ARM9 virtio-blk wire ABI and split-ring wrap accounting.

Linux sends struct virtio_blk_outhdr as { type, ioprio, sector }.  The inherited
ARM9 firmware declared the first two u32 fields in the opposite order.  Once
write support began validating request type, every OUT request was therefore
read as IN (ioprio is normally zero) and completed with IOERR before TMIO ran.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
SDCARD = ROOT / "third_party/arm9linuxfw/source/vdev/sdcard.c"
QUEUE = ROOT / "third_party/arm9linuxfw/source/virt/queue.c"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


sdcard = SDCARD.read_text()
if "N3DS_VIRTIO_BLK_WIRE_ABI" not in sdcard:
    sdcard = replace_once(
        sdcard,
        """typedef struct {
	u32 resv;
	u32 type;
	u64 sector_offset;
} PACKED vblk_t;""",
        """/* N3DS_VIRTIO_BLK_WIRE_ABI: exact Linux virtio_blk_outhdr order.
 * The old {resv,type,sector} declaration read ioprio (normally zero) as the
 * operation, deterministically rejecting every write as an IN request. */
typedef struct {
	u32 type;
	u32 ioprio;
	u64 sector_offset;
} PACKED vblk_t;""",
        "virtio-blk request header",
    )

if "N3DS_VIRTIO_BLK_WIRE_ABI" not in sdcard:
    raise SystemExit("virtio-blk ABI marker missing")
SDCARD.write_text(sdcard)


queue = QUEUE.read_text()
if "N3DS_VIRTQUEUE_16BIT_WRAP" not in queue:
    queue = replace_once(
        queue,
        """	uint index, avail;
	const vqAvail_s *vqA = (const vqAvail_s*)vq->q_avail;

	if (UNLIKELY(!vq->ready))
		return -1;

	index = vq->avail_idx & vq->size_mask;
	avail = vqA->last & vq->size_mask;

	if (index == avail)
		return -1;

	vq->avail_idx = index + 1;
	return vqA->ring[index];
""",
        """	/* N3DS_VIRTQUEUE_16BIT_WRAP: avail_idx and avail->idx are monotonic
	 * 16-bit counters.  Mask only the ring slot, never the equality test or
	 * stored counter, otherwise a full ring revolution aliases empty. */
	u16 avail;
	uint index;
	const vqAvail_s *vqA = (const vqAvail_s*)vq->q_avail;

	if (UNLIKELY(!vq->ready))
		return -1;

	avail = vqA->last;
	if (vq->avail_idx == avail)
		return -1;

	index = vq->avail_idx & vq->size_mask;
	vq->avail_idx++;
	return vqA->ring[index];
""",
        "virtqueue avail counter",
    )

if "N3DS_VIRTQUEUE_16BIT_WRAP" not in queue:
    raise SystemExit("virtqueue wrap marker missing")
QUEUE.write_text(queue)

print("patch_arm9_virtio_blk_abi: correct OUT header parsing and 16-bit ring wrap")
