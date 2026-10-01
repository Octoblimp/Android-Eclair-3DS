from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/Makefile"
with open(path) as f:
    content = f.read()

old = "obj-\t\t+= ath6k_legacy/"
new = "obj-$(CONFIG_ATH6K_LEGACY)\t\t+= ath6k_legacy/"

count = content.count(old)
assert count == 1, f"expected exactly 1 match, found {count}"
content = content.replace(old, new)

with open(path, 'w') as f:
    f.write(content)
print("OK")
