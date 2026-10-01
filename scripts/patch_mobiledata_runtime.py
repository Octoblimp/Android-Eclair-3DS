#!/usr/bin/env python3
"""Install the fail-closed 3DS Telco userspace lifecycle.

The AP ioctl/rebind implementation is intentionally a separate binary owned
by the legacy ath6k slice.  This patch only installs its privileged controller
contract, static AP networking, DHCP launch, state properties, and init
lifecycle.  It never creates a credential-bearing persistent file.
"""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

from pathlib import Path
import os
import stat


ROOT = Path(__file__).resolve().parents[1]
# `rebuild_everything.sh` intentionally prefers the Windows-mounted scripts
# tree when it exists. Keep explicit authorities for both workspaces so a
# mounted invocation cannot silently patch only its own copy.
CANONICAL_ROOT = Path(A3DS_ROOT)
WINDOWS_ROOT = Path(
    A3DS_WIN
)
MARKER = "N3DS_MOBILE_DATA_LIFECYCLE"
PROP_MARKER = "N3DS_MOBILE_DATA_DEFAULTS"
IPC_MARKER = "service mobiledata_ipc /system/bin/mobiledata_ipc"
OVERLAY_RELATIVE = Path("third_party/buildroot/board/nintendo3ds/rootfs_overlay")
RUNTIME_RELATIVE = Path("etc/mobiledata.sh")
BOOT_PROGRESS_RELATIVE = Path("etc/boot_progress.sh")
RUNTIME_MARKERS = (
    "N3DS_MOBILE_DATA_RUNTIME",
    "MOBILEDATA_MODULE_ROOTS",
    "module_detect",
    "module_unload",
    "status_endpoint_failed",
)
BOOT_PROGRESS_MARKERS = (
    "WIFI_RE=",
    "mobiledata:",
    "mobiledata_apctl:",
    "=== Mobile Data properties ===",
    "init.svc.mobiledata=",
    "N3DS_DALVIK_ABORT|surfaceflinger",
    "Unhandled fault",
    "Code:",
    "r10:",
)
IPC_BLOCK = """service mobiledata_ipc /system/bin/mobiledata_ipc
    class default
    user root
    group root system
    socket mobiledata stream 0600 system system

"""

INIT_BLOCK = r'''

# N3DS_MOBILE_DATA_LIFECYCLE: 3DS Telco is a local AP, not a station-mode
# Wi-Fi connection. The controller owns AP qualification, static addressing,
# DHCP, client state, and rollback to station mode. It is disabled by default.
service mobiledata_ipc /system/bin/mobiledata_ipc
    class default
    user root
    group root system
    socket mobiledata stream 0600 system system

service md_dispatch /etc/mobiledata.sh dispatch
    class default
    user root
    group root wifi inet

service mobiledata /etc/mobiledata.sh daemon
    class default
    disabled
    oneshot
    user root
    group root wifi inet

on property:service.mobiledata.enable=1
    setprop sys.mobiledata.dispatch enable_requested
    setprop sys.mobiledata.state starting
    setprop sys.mobiledata.backend active
    setprop sys.mobiledata.error none
    setprop sys.mobiledata.stage request
    setprop sys.mobiledata.result enable_requested
    start md_dispatch
    start mobiledata

on property:service.mobiledata.enable=0
    setprop sys.mobiledata.dispatch disable_requested
    start md_dispatch
    setprop service.mobiledata.adb 0
    setprop service.adb.tcp.port 0
    setprop sys.mobiledata.state disabled
    setprop sys.mobiledata.client_count 0
    setprop sys.mobiledata.rssi unknown
    setprop sys.mobiledata.ap_ipv4 ""
    setprop sys.mobiledata.adb_address ""
    setprop sys.mobiledata.backend ready
    setprop sys.mobiledata.error none
    setprop sys.mobiledata.stage disabled
    setprop sys.mobiledata.result disable_requested
    setprop sys.mobiledata.module unknown
    setprop sys.mobiledata.rebind none
    setprop sys.mobiledata.primary_error none
    setprop sys.mobiledata.rollback none
    setprop sys.mobiledata.boundary none

on property:sys.powerctl=*
    stop md_dispatch
    stop mobiledata
'''


def _path_key(path: Path) -> str:
    """Return a stable deduplication key without requiring the path to exist."""
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def workspace_roots(base: Path | None = None) -> tuple[Path, ...]:
    """Enumerate canonical and Windows authorities exactly once.

    ``base`` is injectable for the offline regression that models a
    Windows-mounted script invocation. Production calls use ``ROOT`` (the
    launching script's workspace) plus both explicit authorities.
    """
    candidates = (base or ROOT, CANONICAL_ROOT, WINDOWS_ROOT)
    roots = []
    seen = set()
    for candidate in candidates:
        key = _path_key(candidate)
        if key in seen or not candidate.is_dir():
            continue
        seen.add(key)
        roots.append(candidate)
    return tuple(roots)


def lifecycle_targets(base: Path | None = None) -> tuple[Path, ...]:
    """Return existing managed overlay/output/staging roots, deduplicated."""
    relative_roots = (
        Path("third_party/buildroot/board/nintendo3ds/rootfs_overlay"),
        Path("third_party/buildroot/output/target"),
        Path("sdcard/linux/android"),
    )
    targets = []
    seen = set()
    for workspace in workspace_roots(base):
        for relative in relative_roots:
            target = workspace / relative
            key = _path_key(target)
            if key in seen or not target.is_dir():
                continue
            seen.add(key)
            targets.append(target)
    return tuple(targets)


def _authoritative_candidates(relative: Path) -> tuple[Path, ...]:
    """Return source candidates with the mounted Windows tree preferred.

    The Windows overlay is the source of truth when a WSL invocation sees it;
    a native Windows invocation instead reaches the same files through ROOT.
    Canonical WSL is a final fallback for environments without the mounted
    Windows workspace.  The first existing candidate is authoritative and is
    validated rather than silently replaced by an older copy.
    """
    candidates = []
    seen = set()
    for workspace in (WINDOWS_ROOT, ROOT, CANONICAL_ROOT):
        path = workspace / OVERLAY_RELATIVE / relative
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(path)
    return tuple(candidates)


def authoritative_source(relative: Path, markers: tuple[str, ...], label: str) -> Path:
    """Resolve and validate one managed script source, failing closed."""
    for candidate in _authoritative_candidates(relative):
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(
                f"patch_mobiledata_runtime: cannot read authoritative {label}: {candidate}"
            ) from exc
        missing = [marker for marker in markers if marker not in text]
        if missing:
            raise SystemExit(
                f"patch_mobiledata_runtime: authoritative {label} missing marker(s): "
                + ", ".join(missing)
            )
        if not text.startswith("#!/bin/sh\n"):
            raise SystemExit(
                f"patch_mobiledata_runtime: authoritative {label} has invalid shebang"
            )
        return candidate
    raise SystemExit(
        f"patch_mobiledata_runtime: authoritative {label} source is missing"
    )


def _is_windows_mount(path: Path) -> bool:
    """Return whether a target is below the mounted Windows authority."""
    try:
        Path(_path_key(path)).relative_to(Path(_path_key(WINDOWS_ROOT)))
        return True
    except ValueError:
        return False


def _mode_unrepresentable(path: Path) -> bool:
    """Identify NTFS/DrvFS targets where POSIX mode bits are not reliable."""
    return os.name == "nt" or _is_windows_mount(path)


def _accept_mode(path: Path, before: int, after: int) -> bool:
    """Accept a chmod result and report whether it changed effective state."""
    if after == 0o755:
        return before != after
    if _mode_unrepresentable(path) and after == before:
        # DrvFS without metadata (and native NTFS) can report the same mode
        # after chmod.  The call was still made, but it is not a real change.
        return False
    raise SystemExit(
        f"patch_mobiledata_runtime: managed target mode is not 0755: {path}"
    )


def install_managed_file(source: Path, target: Path, label: str) -> bool:
    """Install one validated script with mode 0755, without needless rewrites."""
    if target.parent.exists() and not target.parent.is_dir():
        raise SystemExit(
            f"patch_mobiledata_runtime: managed {label} target directory is missing: "
            f"{target.parent}"
        )
    # lifecycle_targets() contains only the three explicit Buildroot/deploy
    # roots, so creating their missing etc/ directory is bounded and makes the
    # installation complete even for a partially generated output/target.
    target.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    changed = not target.is_file() or target.read_bytes() != source_bytes
    if changed:
        target.write_bytes(source_bytes)
    mode = stat.S_IMODE(target.stat().st_mode)
    if mode != 0o755:
        try:
            target.chmod(0o755)
        except OSError:
            # A mounted Windows target may reject chmod without metadata;
            # canonical POSIX targets must fail closed instead.
            if not _mode_unrepresentable(target):
                raise
        after = stat.S_IMODE(target.stat().st_mode)
        changed |= _accept_mode(target, mode, after)
    return changed


def install_managed_scripts(targets: tuple[Path, ...]) -> bool:
    """Synchronize runtime and boot-progress scripts to every managed tree."""
    runtime_source = authoritative_source(
        RUNTIME_RELATIVE, RUNTIME_MARKERS, "mobiledata.sh"
    )
    boot_source = authoritative_source(
        BOOT_PROGRESS_RELATIVE, BOOT_PROGRESS_MARKERS, "boot_progress.sh"
    )
    changed = False
    for root in targets:
        changed |= install_managed_file(
            runtime_source, root / RUNTIME_RELATIVE, "mobiledata.sh"
        )
        changed |= install_managed_file(
            boot_source, root / BOOT_PROGRESS_RELATIVE, "boot_progress.sh"
        )
    return changed

PROP_BLOCK = r'''

# N3DS_MOBILE_DATA_DEFAULTS: mutable request properties are consumed by the
# root-owned controller. Secrets are never represented as Android properties.
service.mobiledata.enable=0
service.mobiledata.security=open
service.mobiledata.ssid=3DS
service.mobiledata.adb=0
sys.mobiledata.backend=ready
sys.mobiledata.error=none
sys.mobiledata.stage=booting
sys.mobiledata.result=none
sys.mobiledata.module=unknown
sys.mobiledata.rebind=none
sys.mobiledata.primary_error=none
sys.mobiledata.rollback=none
sys.mobiledata.boundary=none
sys.mobiledata.dispatch=booting
sys.mobiledata.dispatch_seq=0
sys.mobiledata.state=disabled
sys.mobiledata.client_count=0
sys.mobiledata.rssi=unknown
sys.mobiledata.ap_ipv4=
sys.mobiledata.adb_address=
'''


def patch_init(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if MARKER not in text:
        path.write_text(text.rstrip() + INIT_BLOCK + "\n", encoding="utf-8")
        return True
    changed = False
    marker_offset = text.find(MARKER)
    managed = text[marker_offset:]
    # Android 1.6 init limits service names to 16 bytes.  The older managed
    # name was rejected at boot, so Settings could request AP mode but no
    # privileged dispatcher existed to consume the property transition.
    if "mobiledata_dispatch" in managed:
        managed = managed.replace("mobiledata_dispatch", "md_dispatch")
        changed = True
    # This port issues only `class_start default`; a parsed class-core service
    # remains permanently stopped.  Keep both always-on control-plane
    # processes in the class the device actually starts.
    for service in ("mobiledata_ipc /system/bin/mobiledata_ipc",
                    "md_dispatch /etc/mobiledata.sh dispatch"):
        old = "service " + service + "\n    class core\n"
        new = "service " + service + "\n    class default\n"
        if old in managed:
            managed = managed.replace(old, new, 1)
            changed = True
    service_needle = "service mobiledata /etc/mobiledata.sh daemon\n    class default\n    disabled\n"
    if "service mobiledata /etc/mobiledata.sh daemon\n    class default\n    disabled\n    oneshot\n" not in managed:
        if service_needle not in managed:
            raise SystemExit("patch_mobiledata_runtime: mobiledata service shape changed")
        managed = managed.replace(service_needle,
                                  service_needle + "    oneshot\n", 1)
        changed = True
    if "service md_dispatch /etc/mobiledata.sh dispatch" not in managed:
        needle = "service mobiledata /etc/mobiledata.sh daemon\n"
        if needle not in managed:
            raise SystemExit("patch_mobiledata_runtime: lifecycle exists without mobiledata service")
        managed = managed.replace(
            needle,
            "service md_dispatch /etc/mobiledata.sh dispatch\n"
            "    class default\n"
            "    user root\n"
            "    group root wifi inet\n\n" + needle,
            1,
        )
        changed = True
    if "setprop sys.mobiledata.dispatch enable_requested" not in managed:
        needle = "on property:service.mobiledata.enable=1\n"
        if needle not in managed:
            raise SystemExit("patch_mobiledata_runtime: enable trigger shape changed")
        managed = managed.replace(needle, needle +
                                  "    setprop sys.mobiledata.dispatch enable_requested\n", 1)
        changed = True
    if "    start md_dispatch\n    start mobiledata\n" not in managed:
        needle = "    setprop sys.mobiledata.dispatch enable_requested\n"
        if needle not in managed:
            raise SystemExit("patch_mobiledata_runtime: enable action shape changed")
        managed = managed.replace(
            needle,
            needle
            + "    setprop sys.mobiledata.state starting\n"
            + "    setprop sys.mobiledata.backend active\n"
            + "    setprop sys.mobiledata.error none\n"
            + "    start md_dispatch\n",
            1,
        )
        changed = True
    if "setprop sys.mobiledata.dispatch disable_requested" not in managed:
        needle = "on property:service.mobiledata.enable=0\n"
        if needle not in managed:
            raise SystemExit("patch_mobiledata_runtime: disable trigger shape changed")
        managed = managed.replace(needle, needle +
                                  "    setprop sys.mobiledata.dispatch disable_requested\n", 1)
        changed = True
    disable_marker = "on property:service.mobiledata.enable=0\n"
    power_marker = "on property:sys.powerctl=*\n"
    disable_start = managed.index(disable_marker) + len(disable_marker)
    disable_end = managed.find(power_marker, disable_start)
    if disable_end < 0:
        disable_end = len(managed)
    disable_action = managed[disable_start:disable_end]
    # N3DS_MOBILEDATA_SINGLE_STOP_OWNER: the dispatcher owns the one stop
    # request for a disable edge. A direct init stop plus per-second dispatcher
    # stops can re-enter the worker's rollback trap and repeatedly reset SDIO.
    if "    stop mobiledata\n" in disable_action:
        disable_action = disable_action.replace("    stop mobiledata\n", "", 1)
        changed = True
    if "    start md_dispatch\n" not in disable_action:
        needle = "    setprop sys.mobiledata.dispatch disable_requested\n"
        if needle not in disable_action:
            raise SystemExit("patch_mobiledata_runtime: disable action shape changed")
        disable_action = disable_action.replace(
            needle, needle + "    start md_dispatch\n", 1)
        changed = True
    managed = managed[:disable_start] + disable_action + managed[disable_end:]
    if "    stop md_dispatch\n" not in managed:
        needle = "on property:sys.powerctl=*\n"
        if needle not in managed:
            raise SystemExit("patch_mobiledata_runtime: power trigger shape changed")
        managed = managed.replace(needle, needle + "    stop md_dispatch\n", 1)
        changed = True
    if "setprop sys.mobiledata.backend ready" not in managed:
        needle = '    setprop sys.mobiledata.adb_address ""\n'
        if needle not in managed:
            raise SystemExit("patch_mobiledata_runtime: disable action shape changed")
        managed = managed.replace(needle, needle +
                                  "    setprop sys.mobiledata.backend ready\n" +
                                  "    setprop sys.mobiledata.error none\n", 1)
        changed = True
    if managed != text[marker_offset:]:
        text = text[:marker_offset] + managed
    if IPC_MARKER not in text:
        needle = "service mobiledata /etc/mobiledata.sh daemon"
        if needle not in text:
            raise SystemExit("patch_mobiledata_runtime: lifecycle exists without mobiledata service")
        text = text.replace(needle, IPC_BLOCK + needle, 1)
        changed = True
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def patch_prop(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if PROP_MARKER not in text:
        path.write_text(text.rstrip() + PROP_BLOCK + "\n", encoding="utf-8")
        return True
    marker_offset = text.find(PROP_MARKER)
    managed = text[marker_offset:]
    if "sys.mobiledata.error=none" in managed and \
            "sys.mobiledata.stage=booting" in managed and \
            "sys.mobiledata.result=none" in managed and \
            "sys.mobiledata.module=unknown" in managed and \
            "sys.mobiledata.rebind=none" in managed and \
            "sys.mobiledata.primary_error=none" in managed and \
            "sys.mobiledata.rollback=none" in managed and \
            "sys.mobiledata.boundary=none" in managed and \
            "sys.mobiledata.dispatch=booting" in managed and \
            "sys.mobiledata.dispatch_seq=0" in managed and \
            "service.mobiledata.ssid=" in managed:
        return False
    needle = "sys.mobiledata.backend=ready\n"
    if needle not in managed:
        raise SystemExit("patch_mobiledata_runtime: defaults block shape changed")
    additions = ""
    if "service.mobiledata.ssid=" not in managed:
        additions += "service.mobiledata.ssid=3DS\n"
    if "sys.mobiledata.error=none" not in managed:
        additions += "sys.mobiledata.error=none\n"
    if "sys.mobiledata.stage=booting" not in managed:
        additions += "sys.mobiledata.stage=booting\n"
    if "sys.mobiledata.result=none" not in managed:
        additions += "sys.mobiledata.result=none\n"
    if "sys.mobiledata.module=unknown" not in managed:
        additions += "sys.mobiledata.module=unknown\n"
    if "sys.mobiledata.rebind=none" not in managed:
        additions += "sys.mobiledata.rebind=none\n"
    if "sys.mobiledata.primary_error=none" not in managed:
        additions += "sys.mobiledata.primary_error=none\n"
    if "sys.mobiledata.rollback=none" not in managed:
        additions += "sys.mobiledata.rollback=none\n"
    if "sys.mobiledata.boundary=none" not in managed:
        additions += "sys.mobiledata.boundary=none\n"
    if "sys.mobiledata.dispatch=booting" not in managed:
        additions += "sys.mobiledata.dispatch=booting\n"
    if "sys.mobiledata.dispatch_seq=0" not in managed:
        additions += "sys.mobiledata.dispatch_seq=0\n"
    managed = managed.replace(needle, needle + additions, 1)
    path.write_text(text[:marker_offset] + managed, encoding="utf-8")
    return True


def main() -> None:
    # Buildroot may regenerate output/target after the first patch pass, and
    # the final rsync can overwrite either deploy mirror. Keep every present
    # managed copy on the same lifecycle contract; data/ and persistent/ are
    # deliberately outside lifecycle_targets().
    targets = lifecycle_targets()
    changed = False
    found = False
    for root in targets:
        init = root / "etc/init.rc"
        prop = root / "system/build.prop"
        if init.exists() or prop.exists():
            found = True
        changed |= patch_init(init)
        changed |= patch_prop(prop)
    if not found:
        raise SystemExit("patch_mobiledata_runtime: no Android init/build.prop tree found")
    changed |= install_managed_scripts(targets)
    print("patch_mobiledata_runtime: installed" if changed else
          "patch_mobiledata_runtime: already installed")


if __name__ == "__main__":
    main()
