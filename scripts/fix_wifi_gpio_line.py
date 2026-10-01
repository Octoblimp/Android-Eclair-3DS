from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/platform/nintendo3ds/ctr_sdhc.c"
with open(path) as f:
    content = f.read()

old = 'struct gpio_desc *wifi_en = devm_gpiod_get_optional(dev, wifi-enable, GPIOD_OUT_HIGH);'
new = 'struct gpio_desc *wifi_en = devm_gpiod_get_optional(dev, "wifi-enable", GPIOD_OUT_HIGH);'

count = content.count(old)
assert count == 1, f"expected exactly 1 match, found {count}"
content = content.replace(old, new)

with open(path, 'w') as f:
    f.write(content)
print("OK")
