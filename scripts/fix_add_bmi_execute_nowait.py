from a3ds_paths import A3DS_ROOT
bmi_c = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/bmi/src/bmi.c"
bmi_h = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/include/bmi.h"

with open(bmi_c) as f:
    content = f.read()

def replace_once(content, old, new, label):
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    return content.replace(old, new)

old = """int
BMISetAppStart(struct hif_device *device,
               u32 address)
{"""

new = """/* AR6002 Phase 2: Nintendo's EEPROM-reading stub (see ar6000_ar6002_boot_firmware
 * in ar6000_drv.c) never responds through the normal BMIExecute completion
 * mechanism -- bmiBufferReceive's wait for that response is an unbounded busy
 * loop (see its own comment), and two hardware tests confirmed it hangs
 * forever when used with the stub. This variant sends the same BMI_EXECUTE
 * command (which is what actually makes the target jump to and run the code)
 * but does not wait for or read back a response, so it can be used to trigger
 * the stub without risking a permanent hang. Caller is responsible for
 * delaying an appropriate amount before assuming the code has finished. */
int
BMIExecuteNoWait(struct hif_device *device,
                 u32 address)
{
    u32 cid;
    int status;
    u32 offset;
    u32 param;

    A_ASSERT(BMI_COMMAND_FITS(sizeof(cid) + sizeof(address) + sizeof(param)));
    memset (pBMICmdBuf, 0, sizeof(cid) + sizeof(address) + sizeof(param));

    if (bmiDone) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("Command disallowed\\n"));
        return A_ERROR;
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_BMI,
       ("BMI Execute (no wait): Enter (device: 0x%p, address: 0x%x)\\n",
        device, address));

    cid = BMI_EXECUTE;
    param = 0;

    offset = 0;
    memcpy(&(pBMICmdBuf[offset]), &cid, sizeof(cid));
    offset += sizeof(cid);
    memcpy(&(pBMICmdBuf[offset]), &address, sizeof(address));
    offset += sizeof(address);
    memcpy(&(pBMICmdBuf[offset]), &param, sizeof(param));
    offset += sizeof(param);
    status = bmiBufferSend(device, pBMICmdBuf, offset);
    if (status) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("Unable to write to the device\\n"));
        return A_ERROR;
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_BMI, ("BMI Execute (no wait): Exit\\n"));
    return 0;
}

int
BMISetAppStart(struct hif_device *device,
               u32 address)
{"""

content = replace_once(content, old, new, "add BMIExecuteNoWait")

with open(bmi_c, 'w') as f:
    f.write(content)

with open(bmi_h) as f:
    hcontent = f.read()

old_h = """int
BMIExecute(struct hif_device *device,
           u32 address,
           u32 *param);"""

new_h = """int
BMIExecute(struct hif_device *device,
           u32 address,
           u32 *param);

int
BMIExecuteNoWait(struct hif_device *device,
                 u32 address);"""

hcontent = replace_once(hcontent, old_h, new_h, "declare BMIExecuteNoWait")

with open(bmi_h, 'w') as f:
    f.write(hcontent)

print("OK")
