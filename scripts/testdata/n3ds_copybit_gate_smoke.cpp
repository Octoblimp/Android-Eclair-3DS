/* Execute the real Android3DS copybit open gate under ARM QEMU. */

#include <stdio.h>
#include <string.h>

static const char *test_property_value = "0";

extern "C" int n3ds_test_property_get(const char *key, char *value,
                                       const char *default_value)
{
    const char *selected = default_value;
    if (strcmp(key, "debug.n3ds.copybit") == 0)
        selected = test_property_value;
    if (selected == NULL)
        selected = "";
    strcpy(value, selected);
    return (int)strlen(selected);
}

#define property_get n3ds_test_property_get
#include "../../hal/copybit/copybit_n3ds.cpp"
#undef property_get

extern "C" struct hw_module_t n3ds_gralloc_module = { 0 };

int main()
{
    hw_device_t *raw = reinterpret_cast<hw_device_t *>(1);
    int result;

    test_property_value = "0";
    result = n3ds_copybit_module.common.methods->open(
        &n3ds_copybit_module.common, COPYBIT_HARDWARE_COPYBIT0, &raw);
    if (result != -ENODEV || raw != NULL) {
        printf("FAIL: default copybit gate result=%d device=%p\n", result, raw);
        return 1;
    }

    test_property_value = "1";
    result = n3ds_copybit_module.common.methods->open(
        &n3ds_copybit_module.common, COPYBIT_HARDWARE_COPYBIT0, &raw);
    if (result != 0 || raw == NULL) {
        printf("FAIL: explicit copybit opt-in result=%d device=%p\n",
               result, raw);
        return 2;
    }

    copybit_device_t *copybit = reinterpret_cast<copybit_device_t *>(raw);
    if (copybit->set_parameter == NULL || copybit->get == NULL ||
            copybit->blit == NULL || copybit->stretch == NULL ||
            copybit->get(copybit, COPYBIT_MINIFICATION_LIMIT) != 16) {
        printf("FAIL: opened copybit device has an invalid ABI\n");
        return 3;
    }
    if (copybit_close(copybit) != 0) {
        printf("FAIL: copybit close failed\n");
        return 4;
    }

    printf("PASS: copybit is built, default-quarantined, and explicit opt-in opens\n");
    return 0;
}
