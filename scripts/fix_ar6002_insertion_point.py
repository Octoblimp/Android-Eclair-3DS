from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()

# The stray "int\n" return-type line ended up before my inserted comment
# instead of before ar6000_sysfs_bmi_get_config's name, splitting that
# original declaration in two. Remove it from its current (wrong) spot...
old_start = "int\n/* Phase 2 (WiFi bring-up, legacy AR6002 driver port):"
new_start = "/* Phase 2 (WiFi bring-up, legacy AR6002 driver port):"
count = content.count(old_start)
assert count == 1, f"start marker: expected 1, found {count}"
content = content.replace(old_start, new_start)

# ...and put it back immediately before the function it actually belongs to.
old_end = "ar6000_sysfs_bmi_get_config(struct ar6_softc *ar, u32 mode)\n{"
new_end = "int\nar6000_sysfs_bmi_get_config(struct ar6_softc *ar, u32 mode)\n{"
count = content.count(old_end)
assert count == 1, f"end marker: expected 1, found {count}"
content = content.replace(old_end, new_end)

with open(path, 'w') as f:
    f.write(content)
print("OK")
