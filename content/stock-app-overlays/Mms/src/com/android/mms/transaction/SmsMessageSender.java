/* Android3DS 3DSTelco transport overlay for the original Eclair Mms app. */
package com.android.mms.transaction;

import com.google.android.mms.MmsException;

import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;

public class SmsMessageSender implements MessageSender {
    public static final String N3DS_TELCO_ORIGINAL_MMS_READY = "N3DS_TELCO_ORIGINAL_MMS_READY";
    private static final Uri TELCO_MESSAGES = Uri.parse("content://io.divergen.telco/messages");
    private final Context mContext;
    private final String[] mDests;
    private final String mMessageText;

    public SmsMessageSender(Context context, String[] dests, String msgText, long threadId) {
        mContext = context;
        if (dests != null) {
            mDests = new String[dests.length];
            System.arraycopy(dests, 0, mDests, 0, dests.length);
        } else {
            mDests = new String[0];
        }
        mMessageText = msgText;
    }

    public boolean sendMessage(long token) throws MmsException {
        if (mMessageText == null || mMessageText.length() == 0 || mDests.length == 0) {
            throw new MmsException("3DSTelco message body or destination is empty.");
        }
        try {
            if (mMessageText.getBytes("UTF-8").length > 1000) {
                throw new MmsException("3DSTelco messages are limited to 1000 UTF-8 bytes.");
            }
            for (int index = 0; index < mDests.length; index++) {
                String destination = mDests[index] == null ? "" : mDests[index].replaceAll("[^0-9]", "");
                // N3DS_TELCO_WEB_NUMBERS: 3DS (3-4), service (6) or web account (10) digits.
                if (!destination.matches("(?:[1-9][0-9]{2,3}|[1-9][0-9]{5}|[2-9][0-9]{9})")) {
                    throw new MmsException("3DSTelco recipients are 3–4 digit 3DS, 6 digit service or 10 digit web numbers.");
                }
                ContentValues values = new ContentValues();
                values.put("to", destination);
                values.put("body", mMessageText);
                Uri result = mContext.getContentResolver().insert(TELCO_MESSAGES, values);
                if (result == null) throw new MmsException("3DSTelco did not accept the message.");
            }
        } catch (MmsException error) {
            throw error;
        } catch (Exception error) {
            throw new MmsException("3DSTelco send failed: " + error.getMessage());
        }
        return false;
    }
}
