#!/usr/bin/env python3
from a3ds_paths import A3DS_ROOT
from pathlib import Path

p = Path(f"{A3DS_ROOT}/third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/GlobalActions.java")
text = p.read_text()
text = text.replace(
    "        if (ServiceManager.checkService(Context.AUDIO_SERVICE) == null) {\n            mItems.remove(mSilentModeToggle);\n        }",
    "        if (android.os.ServiceManager.checkService(Context.AUDIO_SERVICE) == null) {\n            mItems.remove(mSilentModeToggle);\n        }"
)
text = text.replace(
    "        if (mAudioManager != null && ServiceManager.checkService(Context.AUDIO_SERVICE) != null) {\n            final boolean silentModeOn = mAudioManager.getRingerMode()\n                    != AudioManager.RINGER_MODE_NORMAL;\n            mSilentModeToggle.updateState(silentModeOn\n                    ? ToggleAction.State.On : ToggleAction.State.Off);\n        }",
    "        if (mAudioManager != null && android.os.ServiceManager.checkService(Context.AUDIO_SERVICE) != null) {\n            final boolean silentModeOn = mAudioManager.getRingerMode()\n                    != AudioManager.RINGER_MODE_NORMAL;\n            mSilentModeToggle.updateState(silentModeOn\n                    ? ToggleAction.State.On : ToggleAction.State.Off);\n        }"
)
p.write_text(text)
print("Updated GlobalActions.java successfully")
