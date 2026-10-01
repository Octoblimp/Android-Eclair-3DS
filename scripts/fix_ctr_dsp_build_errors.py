from a3ds_paths import A3DS_ROOT
F = f"{A3DS_ROOT}/third_party/linux/drivers/platform/nintendo3ds/ctr_dsp.c"
with open(F) as f:
    c = f.read()

old_inc = "#include <linux/bitops.h>\n"
assert c.count(old_inc) == 1
c = c.replace(old_inc, old_inc + "#include <linux/of.h>\n")

old_fn = "static int ctr_dsp_fifo_write(struct ctr_dsp *dsp, u32 memsel, u32 addr,"
assert c.count(old_fn) == 1
c = c.replace(old_fn, "static int __maybe_unused ctr_dsp_fifo_write(struct ctr_dsp *dsp, u32 memsel, u32 addr,")

with open(F, "w") as f:
    f.write(c)
print("OK")
