#!/usr/bin/env python3
"""Persist a first-scan timeout suitable for the AR6014 RAM BSS harvest."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PACKAGE = Path(
    f"{A3DS_ROOT}/third_party/buildroot/package/wpa_supplicant/"
    "0002-n3ds-ar6014-scan-harvest-timeout.patch"
)

PATCH = """From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: Android3DS <android3ds@localhost>
Date: Fri, 21 Aug 2026 20:52:00 -0500
Subject: [PATCH] nl80211: allow AR6014 first-scan result harvest to finish

The Nintendo AR6014 firmware completes RF scanning before its private BSS
table has been exported to cfg80211.  The legacy host adapter recovers that
table before scan_done; the first scan therefore needs the same 30-second
fallback already used after nl80211 scan-complete events are learned.

---
 src/drivers/driver_nl80211_scan.c | 6 +++++-
 1 file changed, 5 insertions(+), 1 deletion(-)

diff --git a/src/drivers/driver_nl80211_scan.c b/src/drivers/driver_nl80211_scan.c
index 1111111..2222222 100644
--- a/src/drivers/driver_nl80211_scan.c
+++ b/src/drivers/driver_nl80211_scan.c
@@ -396,7 +396,11 @@ int wpa_driver_nl80211_scan(struct i802_bss *bss,
 \tdrv->scan_state = SCAN_REQUESTED;
 \t/* Not all drivers generate "scan completed" wireless event, so try to
 \t * read results after a timeout. */
-\ttimeout = 10;
+\t/* N3DS_AR6014_SCAN_HARVEST_TIMEOUT: the Nintendo firmware's RF scan
+\t * completes quickly, but its private target-RAM BSS table must be
+\t * exported to cfg80211 before scan_done. Do not report a false empty
+\t * first scan while that bounded export is still running. */
+\ttimeout = 30;
 \tif (drv->scan_complete_events) {
 \t\t/*
 \t\t * The driver seems to deliver events to notify when scan is
-- 
2.39.5
"""

PACKAGE.write_text(PATCH)
print(f"Wrote persistent Buildroot patch: {PACKAGE}")
