/* Android3DS compatibility shell: the missing SlidingTab cellular UI is not
 * used for 3DSTelco calls, which run in TelcoCallActivity. */
package com.android.phone;

import android.content.Context;
import android.util.AttributeSet;
import android.widget.FrameLayout;

import com.android.internal.telephony.Phone;

public final class InCallTouchUi extends FrameLayout {
    public InCallTouchUi(Context context, AttributeSet attrs) { super(context, attrs); }
    void setInCallScreenInstance(InCallScreen screen) {}
    void updateState(Phone phone) { setVisibility(GONE); }
    boolean isTouchUiEnabled() { return false; }
}
