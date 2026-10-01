#!/usr/bin/env python3
"""Run the ARM zygote under qemu with a real inherited zygote socket.

Android init normally creates /dev/socket/zygote and passes its listening file
descriptor through ANDROID_SOCKET_zygote.  The host-side preload test has no
Android init, so this tiny wrapper supplies the same contract before replacing
itself with qemu-arm-static.
"""

import os
import socket
import sys


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "usage: qemu_zygote_socket_exec.py SOCKET QEMU ARM_PROGRAM [ARG ...]"
        )

    socket_path, qemu, arm_program, *arm_args = sys.argv[1:]
    try:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(4)

    zygote_fd = 3
    if listener.fileno() != zygote_fd:
        os.dup2(listener.fileno(), zygote_fd, inheritable=True)
        listener.close()
    else:
        os.set_inheritable(zygote_fd, True)

    env = os.environ.copy()
    env["ANDROID_SOCKET_zygote"] = str(zygote_fd)
    qemu_args = [qemu]
    gdb_port = env.pop("ANDROID3DS_QEMU_GDB_PORT", "")
    if gdb_port:
        qemu_args.extend(["-g", gdb_port])
    qemu_args.extend([arm_program, *arm_args])
    os.execve(qemu, qemu_args, env)


if __name__ == "__main__":
    main()
