from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/htc2/htc.c"
with open(path) as f:
    content = f.read()

def replace_once(old, new, label):
    global content
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    content = content.replace(old, new)

# Piece 1: right after HTCWaitforControlMessage succeeds.
old1 = """        if (status) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, (" Target Not Available!!\\n"));
            break;
        }

            /* we controlled the buffer creation so it has to be properly aligned */
        pRdyMsg = (HTC_READY_EX_MSG *)pPacket->pBuffer;

        if ((pRdyMsg->Version2_0_Info.MessageID != HTC_MSG_READY_ID) ||
            (pPacket->ActualLength < sizeof(HTC_READY_MSG))) {
                /* this message is not valid */
            AR_DEBUG_ASSERT(false);
            status = A_EPROTO;
            break;
        }"""

new1 = """        if (status) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, (" Target Not Available!!\\n"));
            break;
        }

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 DIAG: HTC control msg received, ActualLength=%d\\n",
            pPacket->ActualLength));

            /* we controlled the buffer creation so it has to be properly aligned */
        pRdyMsg = (HTC_READY_EX_MSG *)pPacket->pBuffer;

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 DIAG: HTC ready msg: MessageID=0x%x (want 0x%x) CreditCount=%d CreditSize=%d\\n",
            pRdyMsg->Version2_0_Info.MessageID, HTC_MSG_READY_ID,
            pRdyMsg->Version2_0_Info.CreditCount, pRdyMsg->Version2_0_Info.CreditSize));

        if ((pRdyMsg->Version2_0_Info.MessageID != HTC_MSG_READY_ID) ||
            (pPacket->ActualLength < sizeof(HTC_READY_MSG))) {
                /* this message is not valid */
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 DIAG: HTC ready msg INVALID (bad MessageID or too short)\\n"));
            AR_DEBUG_ASSERT(false);
            status = A_EPROTO;
            break;
        }"""

replace_once(old1, new1, "piece1 ready-message header trace")

# Piece 2: the CreditCount/CreditSize zero-check.
old2 = """        if (pRdyMsg->Version2_0_Info.CreditCount == 0 || pRdyMsg->Version2_0_Info.CreditSize == 0) {
              /* this message is not valid */
            AR_DEBUG_ASSERT(false);
            status = A_EPROTO;
            break;
        }"""

new2 = """        if (pRdyMsg->Version2_0_Info.CreditCount == 0 || pRdyMsg->Version2_0_Info.CreditSize == 0) {
              /* this message is not valid */
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 DIAG: HTC ready msg INVALID (zero CreditCount/CreditSize)\\n"));
            AR_DEBUG_ASSERT(false);
            status = A_EPROTO;
            break;
        }"""

replace_once(old2, new2, "piece2 credit zero-check trace")

# Piece 3: HTCConnectService status for the pseudo control endpoint.
old3 = """        status = HTCConnectService((HTC_HANDLE)target,
                                   &connect,
                                   &resp);

        if (!status) {
            break;
        }

    } while (false);"""

new3 = """        status = HTCConnectService((HTC_HANDLE)target,
                                   &connect,
                                   &resp);

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 DIAG: HTCConnectService (control) status=%d\\n", status));

        if (!status) {
            break;
        }

    } while (false);"""

replace_once(old3, new3, "piece3 HTCConnectService trace")

with open(path, 'w') as f:
    f.write(content)
print("OK")
