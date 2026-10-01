#!/usr/bin/env python3
"""Static contract for Nintendo's zero-valued WMI_CONNECT control flags."""

from pathlib import Path


PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_connect_flags.py")


def main() -> None:
    patch = PATCH_PATH.read_text(encoding="utf-8")
    assert "N3DS_AR6014_NWM_CONNECT_FLAGS" in patch
    assert "ar->arConnectCtrlFlags = 0;" in patch
    replacement = patch.split("NEW = '''", 1)[1].split("'''", 1)[0]
    assert "DEFAULT_CONNECT_CTRL_FLAGS" not in replacement
    assert "CONNECT_PROFILE_MATCH_DONE" not in replacement
    assert replacement.index("ar->arConnectCtrlFlags = 0;") < replacement.index(
        "AR_DEBUG_PRINTF"
    )
    print("ar6014_nwm_connect_flags: PASS")


if __name__ == "__main__":
    main()
