"""Install update-safe state inside the sdcard/linux/android payload."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
WSL_ROOT = Path(A3DS_ROOT)
ROOT = WSL_ROOT if (WSL_ROOT / "third_party").exists() else HERE
OVERLAY = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay"
INIT_RC = OVERLAY / "etc/init.rc"
STAGED_INIT_RC = ROOT / "sdcard/linux/android/etc/init.rc"
WORKSPACE_INIT_RC = HERE / "sdcard/linux/android/etc/init.rc"
WORKSPACE_SERVICE = (
    HERE
    / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/android_prefs_init.sh"
)
SERVICE = OVERLAY / "etc/android_prefs_init.sh"
STAGED_SERVICE = ROOT / "sdcard/linux/android/etc/android_prefs_init.sh"
MOBILE_TEMPLATE_SOURCE = HERE / "scripts/mobile_registration.conf.template"
MOBILE_TEMPLATE_REL = Path("sdcard/linux/android/templates/mobile_registration.conf.example")

MARKER = "N3DS_UPDATE_SAFE_PREFS"


def sync_service() -> None:
    """Publish the reviewed initializer into canonical WSL and staging.

    The rebuild script is executed from the Windows workspace but selects the
    canonical WSL tree as ROOT.  Keeping this copy explicit prevents an older
    WSL overlay from silently discarding newly added durable-state handlers.
    """
    if not WORKSPACE_SERVICE.is_file():
        raise RuntimeError(f"missing workspace initializer: {WORKSPACE_SERVICE}")
    payload = WORKSPACE_SERVICE.read_bytes()
    workspace_staged_service = HERE / "sdcard/linux/android/etc/android_prefs_init.sh"
    for destination in (SERVICE, STAGED_SERVICE, workspace_staged_service):
        if destination.resolve() == WORKSPACE_SERVICE.resolve():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or destination.read_bytes() != payload:
            destination.write_bytes(payload)
        destination.chmod(0o755)

    if not MOBILE_TEMPLATE_SOURCE.is_file():
        raise RuntimeError(f"missing mobile registration template: {MOBILE_TEMPLATE_SOURCE}")
    template = MOBILE_TEMPLATE_SOURCE.read_bytes()
    for destination in (HERE / MOBILE_TEMPLATE_REL, WSL_ROOT / MOBILE_TEMPLATE_REL):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or destination.read_bytes() != template:
            destination.write_bytes(template)
        destination.chmod(0o644)


def add_once(text: str, needle: str, addition: str, label: str) -> str:
    marker_line = next(line for line in addition.splitlines() if MARKER in line)
    if marker_line in text:
        return text
    count = text.count(needle)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(needle, needle + addition, 1)


def patch(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text()

    # This action is synchronous: the SD root is already mounted by the
    # initramfs, and the bind alias exists before any Android app can resolve
    # Environment.getExternalStorageDirectory().  The Wi-Fi import itself is
    # deliberately inserted after /data/misc/wifi and its fallback exist.
    boot_anchor = "on boot\n"
    boot_add = (
        "    # N3DS_UPDATE_SAFE_PREFS: expose the physical SD namespace at the\n"
        "    # Android-facing path requested by apps.  The credential import runs\n"
        "    # below, after its /data destination and fallback file exist.\n"
        "    mkdir /sdcard 0755 root root\n"
        "    mount none /mnt/sd/linux/android /sdcard bind\n"
    )
    text = add_once(text, boot_anchor, boot_add, "init boot anchor")

    # Repair the original integration as well as fresh trees: it ran before
    # /data/misc/wifi existed and its result was then overwritten by `copy`.
    import_anchor = (
        "    copy /system/etc/wifi/wpa_supplicant.conf "
        "/data/misc/wifi/wpa_supplicant.conf\n"
    )
    import_comment = (
        "    # Import the durable file last so the packaged fallback cannot overwrite\n"
        "    # it.  This is synchronous and still precedes the Wi-Fi service.\n"
    )
    import_add = import_comment + "    exec /etc/android_prefs_init.sh\n"
    # Remove the complete generated block, including comments.  Removing only
    # the exec line leaves another comment pair behind on every idempotent run.
    text = text.replace(import_comment, "")
    text = text.replace("    exec /etc/android_prefs_init.sh\n", "")
    count = text.count(import_anchor)
    if count != 1:
        raise RuntimeError(f"Wi-Fi fallback anchor: expected one anchor, found {count}")
    text = text.replace(import_anchor, import_anchor + import_add, 1)

    service_anchor = "# Wi-Fi authentication daemon\n"
    service_add = (
        "# N3DS_UPDATE_SAFE_PREFS: this privileged init service copies runtime\n"
        "# changes back to the durable namespace after boot.\n"
        "service prefs_sync /etc/android_prefs_init.sh --watch\n"
        "    class default\n"
        "    disabled\n"
        "    user root\n"
        "    group root\n\n"
    )
    text = add_once(text, service_anchor, service_add, "Wi-Fi service anchor")

    # Start the long-lived copy-back watcher only after Android is ready; the
    # one-shot initializer has already restored the runtime file by then.
    boot_completed = "on property:sys.boot_completed=1\n"
    boot_completed_add = (
        "    # N3DS_UPDATE_SAFE_PREFS_BOOT_COMPLETED: persist runtime Wi-Fi\n"
        "    # changes after Android has initialized.\n"
        "    start prefs_sync\n"
    )
    text = add_once(text, boot_completed, boot_completed_add, "boot-complete trigger")
    text = text.replace("service android_prefs_sync ", "service prefs_sync ")
    text = text.replace("    start android_prefs_sync\n", "    start prefs_sync\n")
    path.write_text(text)
    print(f"patch_update_safe_prefs: updated {path}")


sync_service()

for candidate in dict.fromkeys((INIT_RC, STAGED_INIT_RC, WORKSPACE_INIT_RC)):
    patch(candidate)

if not INIT_RC.is_file() and not STAGED_INIT_RC.is_file():
    raise SystemExit("patch_update_safe_prefs: no init.rc candidate found")
