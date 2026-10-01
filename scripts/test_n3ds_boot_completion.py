#!/usr/bin/env python3
"""Static regressions for post-statusbar HOME completion and safe poweroff."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WSL = Path(A3DS_ROOT)


def main() -> None:
    patch = (ROOT / "scripts/patch_n3ds_boot_completion.py").read_text(encoding="utf-8")
    pipeline = (ROOT / "scripts/rebuild_everything.sh").read_text(encoding="utf-8")
    server = (WSL / "third_party/frameworks/base/services/java/com/android/server/SystemServer.java").read_text(encoding="utf-8")
    ams = (WSL / "third_party/frameworks/base/services/java/com/android/server/am/ActivityManagerService.java").read_text(encoding="utf-8")
    actions = (WSL / "third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/GlobalActions.java").read_text(encoding="utf-8")

    for token in ("N3DS_BOOT_COMPLETION_ISOLATION",
                  "Failure synchronizing ADB setting",
                  "Failure making Package Manager ready"):
        assert token in server, token
    assert server.index("N3DS_BOOT_COMPLETION_ISOLATION") < server.index(
        ".systemReady(new Runnable()")
    assert "N3DS_BUNDLED_HOME_FALLBACK" in ams
    assert '"com.android.launcher2.Launcher"' in ams
    assert "PackageManager.NameNotFoundException" in ams
    # The power-off item's onPress body carries N3DS_DIRECT_GLOBAL_POWER_OFF
    # until the confirmation step lands and N3DS_POWER_OFF_CONFIRM afterwards:
    # the property write moved out of onPress and into the confirm dialog's
    # positive button, which is what N3DS_POWER_OFF_LOG_FINALIZER marks.
    # patch_n3ds_boot_completion.py accepts both states and migrates the first
    # into the second, so anchor on whichever one this tree is in. Demanding
    # the old name asserted that the confirmation step had NOT been written.
    press_marker = ("N3DS_POWER_OFF_CONFIRM" if "N3DS_POWER_OFF_CONFIRM" in actions
                    else "N3DS_DIRECT_GLOBAL_POWER_OFF")
    assert press_marker in actions
    assert "N3DS_POWER_OFF_LOG_FINALIZER" in actions
    assert 'SystemProperties.set("sys.n3ds.poweroff", "1");' in actions
    assert "import android.os.SystemProperties;" in actions

    def code_only(block):
        """Drop comment lines: these blocks *name* ShutdownThread to explain
        why it is unusable here, and that prose must not read as a call."""
        return chr(10).join(line for line in block.splitlines()
                            if not line.strip().startswith(("*", "/*", "//", "*/")))

    # Neither the keypress nor the branch that actually shuts down may halt the
    # board itself: ShutdownThread ends in Power.shutdown(), which cuts power
    # without flushing the SD card. init owns the real poweroff.
    press_block = code_only(actions[actions.index(press_marker):
                                    actions.index("public boolean showDuringKeyguard()",
                                                  actions.index(press_marker))])
    final_block = code_only(actions[actions.index("N3DS_POWER_OFF_LOG_FINALIZER"):
                                    actions.index("private void prepareDialog()")])
    for power_block in (press_block, final_block):
        assert "ShutdownThread.shutdown" not in power_block
        assert "Power.shutdown();" not in power_block
    assert 'SystemProperties.set("sys.n3ds.poweroff", "1");' in final_block
    assert "run patch_n3ds_boot_completion.py" in pipeline
    assert "run patch_n3ds_shutdown_log_finalization.py" in pipeline
    assert "run test_n3ds_boot_completion.py" in pipeline
    assert "run test_n3ds_shutdown_log_finalization.py" in pipeline
    assert pipeline.index("run patch_n3ds_boot_completion.py") < pipeline.index(
        "run build_services_jar.sh")
    print("n3ds_boot_completion: PASS")


if __name__ == "__main__":
    main()
