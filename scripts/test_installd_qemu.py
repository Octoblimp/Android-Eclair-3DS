#!/usr/bin/env python3
import os
import shutil
import socket
import struct
import subprocess
import sys
import time


def recv_exact(sock, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("installd closed the socket")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def command(sock, value):
    payload = value.encode("ascii")
    sock.sendall(struct.pack("=H", len(payload)) + payload)
    length = struct.unpack("=H", recv_exact(sock, 2))[0]
    return recv_exact(sock, length).decode("ascii")


def main():
    qemu, installd, socket_path, data_path = sys.argv[1:5]
    os.makedirs("/data", exist_ok=True)
    subprocess.run(["mount", "--bind", data_path, "/data"], check=True)
    # N3DS_APPDATA_RESTORE: installd reads its mirror under /mnt/sd.  Copy
    # the binary out first, then put a private tmpfs over /mnt (this runs in
    # its own mount namespace, so the host's /mnt is untouched).
    private_installd = os.path.join(os.path.dirname(data_path), "installd")
    shutil.copy2(installd, private_installd)
    installd = private_installd
    subprocess.run(["mount", "-t", "tmpfs", "tmpfs", "/mnt"], check=True)
    mirror = "/mnt/sd/linux/android/persistent/appdata/com.android3ds.restore"
    for sub in ("shared_prefs", "databases", "files/nested", "cache"):
        os.makedirs(os.path.join(mirror, sub))
    with open(mirror + "/shared_prefs/prefs.xml", "w") as f:
        f.write("<map><int name=\"n\" value=\"7\" /></map>\n")
    with open(mirror + "/databases/good.db", "wb") as f:
        f.write(b"SQLite format 3\0" + bytes(4080))
    with open(mirror + "/databases/torn.db", "wb") as f:
        f.write(bytes(4096))
    with open(mirror + "/databases/.good.db.n3ds-save", "wb") as f:
        f.write(b"half a copy")
    with open(mirror + "/files/nested/wallpaper", "wb") as f:
        f.write(b"\x89PNG" + bytes(60))
    with open(mirror + "/cache/stale", "w") as f:
        f.write("never restored\n")
    try:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(5)
    env = os.environ.copy()
    env["ANDROID_SOCKET_installd"] = str(listener.fileno())
    proc = subprocess.Popen(
        [qemu, installd], env=env, pass_fds=(listener.fileno(),)
    )
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        deadline = time.monotonic() + 5
        while True:
            try:
                client.connect(socket_path)
                break
            except ConnectionRefusedError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

        if command(client, "ping") != "0":
            raise RuntimeError("installd ping failed")
        if command(client, "install com.android3ds.smoke 12345 12345") != "0":
            raise RuntimeError("installd install command failed")
        st = os.stat("/data/data/com.android3ds.smoke")
        if (st.st_uid, st.st_gid) != (12345, 12345):
            raise RuntimeError(
                f"wrong package ownership: uid={st.st_uid} gid={st.st_gid}"
            )
        print("PASS: ARM installd socket created uid=12345 gid=12345 package data")
        shutil.rmtree("/data/data/com.android3ds.smoke")

        if command(client, "install com.android3ds.restore 23456 23456") != "0":
            raise RuntimeError("installd install (with saved data) failed")
        pkg = "/data/data/com.android3ds.restore"
        want = ["databases/good.db", "files/nested/wallpaper",
                "shared_prefs/prefs.xml"]
        for rel in want + ["databases", "files", "files/nested", "shared_prefs"]:
            st = os.stat(os.path.join(pkg, rel))
            if (st.st_uid, st.st_gid) != (23456, 23456):
                raise RuntimeError(f"restored {rel} owned by {st.st_uid}:{st.st_gid}")
        for rel in want:
            a = open(os.path.join(mirror, rel), "rb").read()
            b = open(os.path.join(pkg, rel), "rb").read()
            if a != b:
                raise RuntimeError(f"restored {rel} differs from the mirror")
        for rel in ("databases/torn.db", "databases/.good.db.n3ds-save",
                    "cache/stale", "databases/good.db.n3ds-restore"):
            if os.path.exists(os.path.join(pkg, rel)):
                raise RuntimeError(f"{rel} must not be restored")
        print("PASS: N3DS_APPDATA_RESTORE refilled package data as uid=23456, "
              "skipped the torn database, temporaries and cache")

        if command(client, "remove com.android3ds.restore") != "0":
            raise RuntimeError("installd remove failed")
        trash = "/mnt/sd/linux/android/persistent/appdata.removed/com.android3ds.restore"
        if os.path.exists(mirror) or not os.path.isfile(trash + "/shared_prefs/prefs.xml"):
            raise RuntimeError("uninstall did not move the saved data aside")
        print("PASS: N3DS_APPDATA_FORGET moved an uninstalled package's saved data aside")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        listener.close()


if __name__ == "__main__":
    main()
