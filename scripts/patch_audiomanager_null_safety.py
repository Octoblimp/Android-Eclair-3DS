#!/usr/bin/env python3
"""Make AudioManager null-safe when AudioService is absent."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(A3DS_ROOT)
AUDIO_MGR = ROOT / "third_party/frameworks/base/media/java/android/media/AudioManager.java"
POLICY = ROOT / "third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/GlobalActions.java"

text = AUDIO_MGR.read_text()
if "N3DS_AUDIO_SERVICE_NULL_SAFE" not in text:
    old_ringer = """    public int getRingerMode() {
        IAudioService service = getService();
        try {
            return service.getRingerMode();
        } catch (RemoteException e) {
            Log.e(TAG, "Dead object in getRingerMode", e);
            return RINGER_MODE_NORMAL;
        }
    }"""
    new_ringer = """    public int getRingerMode() {
        /* N3DS_AUDIO_SERVICE_NULL_SAFE: on platforms with no AudioService,
         * getService() returns null. Return normal mode instead of throwing NPE. */
        IAudioService service = getService();
        if (service == null) {
            return RINGER_MODE_NORMAL;
        }
        try {
            return service.getRingerMode();
        } catch (RemoteException e) {
            Log.e(TAG, "Dead object in getRingerMode", e);
            return RINGER_MODE_NORMAL;
        }
    }"""
    if text.count(old_ringer) == 1:
        text = text.replace(old_ringer, new_ringer, 1)
    else:
        raise SystemExit("AudioManager getRingerMode anchor not found")

    old_set = """    public void setRingerMode(int ringerMode) {
        IAudioService service = getService();
        try {
            service.setRingerMode(ringerMode);
        } catch (RemoteException e) {
            Log.e(TAG, "Dead object in setRingerMode", e);
        }
    }"""
    new_set = """    public void setRingerMode(int ringerMode) {
        IAudioService service = getService();
        if (service == null) {
            return;
        }
        try {
            service.setRingerMode(ringerMode);
        } catch (RemoteException e) {
            Log.e(TAG, "Dead object in setRingerMode", e);
        }
    }"""
    if text.count(old_set) == 1:
        text = text.replace(old_set, new_set, 1)
    else:
        raise SystemExit("AudioManager setRingerMode anchor not found")

    old_set_mode = """    public void setMode(int mode) {
        IAudioService service = getService();
        try {
            service.setMode(mode);
        } catch (RemoteException e) {
            Log.e(TAG, "Dead object in setMode", e);
        }
    }"""
    new_set_mode = """    public void setMode(int mode) {
        IAudioService service = getService();
        if (service == null) return;
        try {
            service.setMode(mode);
        } catch (RemoteException e) {
            Log.e(TAG, "Dead object in setMode", e);
        }
    }"""
    if text.count(old_set_mode) == 1:
        text = text.replace(old_set_mode, new_set_mode, 1)
    else:
        # Check if already patched by my generic script
        if "if (service == null) return;" not in text:
            raise SystemExit("AudioManager setMode anchor not found")

    old_get_mode = """    public int getMode() {
        IAudioService service = getService();
        try {
            return service.getMode();
        } catch (RemoteException e) {
            Log.e(TAG, "Dead object in getMode", e);
            return MODE_INVALID;
        }
    }"""
    new_get_mode = """    public int getMode() {
        IAudioService service = getService();
        if (service == null) return MODE_NORMAL;
        try {
            return service.getMode();
        } catch (RemoteException e) {
            Log.e(TAG, "Dead object in getMode", e);
            return MODE_INVALID;
        }
    }"""
    if text.count(old_get_mode) == 1:
        text = text.replace(old_get_mode, new_get_mode, 1)

    AUDIO_MGR.write_text(text)
    print("patch_audiomanager_null_safety: AudioManager.java patched")
else:
    print("patch_audiomanager_null_safety: already applied")
