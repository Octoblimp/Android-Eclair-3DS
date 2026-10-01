#!/usr/bin/env python3
"""Static checks for the privileged Mobile Data WPA2 handoff."""

from pathlib import Path
import os
import socket
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "content/settings/src/com/android/settings/MobileDataSettings.java"
HELPER = ROOT / "native/mobiledata_ipc.c"
RUNTIME = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/mobiledata.sh"
INIT = ROOT / "sdcard/linux/android/etc/init.rc"
PIPELINE = ROOT / "scripts/rebuild_everything.sh"
BUILD = ROOT / "scripts/build_mobiledata_ipc.sh"


def main() -> None:
    java = JAVA.read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")
    init = INIT.read_text(encoding="utf-8")
    pipeline = PIPELINE.read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")

    for marker in (
        "LocalSocketAddress.Namespace.RESERVED", "SECRET_PROVISION",
        "SECRET_CLEAR", "socket.shutdownOutput()", "provisionSecret",
        "clearSecret",
    ):
        assert marker in java, "Settings missing private handoff marker " + marker
    assert "service.mobiledata.passphrase" not in java, \
        "secret handoff must not publish a credential property"
    assert "FileOutputStream" not in java and "FileInputStream" not in java

    for marker in (
        "SO_PEERCRED", "SETTINGS_UID 1000", "ANDROID_SOCKET_mobiledata",
        "--provision-secret", "--clear-secret", "write_all",
        "listen(server, SERVER_QUEUE_DEPTH)",
    ):
        assert marker in helper, "IPC helper missing " + marker
    assert "printf" not in helper and "LOG" not in helper
    assert "--clear-secret" in runtime
    assert "rm -f \"$SECRET_FILE\"" in runtime
    assert "service mobiledata_ipc /system/bin/mobiledata_ipc" in init
    assert "socket mobiledata stream 0600 system system" in init
    assert "run test_mobiledata_secret_ipc.py" in pipeline
    assert "run build_mobiledata_ipc.sh" in pipeline
    assert "mobiledata_ipc.c" in build
    sh = subprocess.run(["bash", "-n", str(BUILD)], capture_output=True,
                        text=True)
    assert sh.returncode == 0, sh.stderr

    # Reproduce Android init's contract: it creates and binds the AF_UNIX
    # stream socket but does not listen.  The daemon must transition it to a
    # listening socket and remain alive long enough to reject a bounded,
    # non-secret invalid request from the authenticated local peer.
    if os.name != "nt":
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = Path(temp_dir) / "mobiledata_ipc_host"
            compile_result = subprocess.run(
                ["cc", "-D_GNU_SOURCE", f"-DSETTINGS_UID={os.getuid()}",
                 str(HELPER), "-o", str(binary)], capture_output=True, text=True)
            assert compile_result.returncode == 0, compile_result.stderr
            socket_path = str(Path(temp_dir) / "mobiledata.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(socket_path)
            environment = os.environ.copy()
            environment["ANDROID_SOCKET_mobiledata"] = str(server.fileno())
            daemon = subprocess.Popen(
                [str(binary)], env=environment, pass_fds=(server.fileno(),))
            try:
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.settimeout(2)
                deadline = time.monotonic() + 2
                while True:
                    try:
                        client.connect(socket_path)
                        break
                    except ConnectionRefusedError:
                        assert daemon.poll() is None, "IPC daemon exited before listen"
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.01)
                client.sendall(b"X")
                client.shutdown(socket.SHUT_WR)
                assert client.recv(3) == b"ER"
                client.close()
                assert daemon.poll() is None, "IPC daemon exited after one client"
            finally:
                daemon.terminate()
                daemon.wait(timeout=2)
                server.close()
    print("mobiledata_secret_ipc: PASS")


if __name__ == "__main__":
    main()
