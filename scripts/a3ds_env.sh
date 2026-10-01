# Android3DS build paths, sourced by every script in this directory:
#
#     . "$(dirname "${BASH_SOURCE[0]}")/a3ds_env.sh"
#
# ANDROID3DS_ROOT  the Linux checkout: third_party/, toolchain/, build/.
#                  Default: ~/android3ds
# ANDROID3DS_WIN   the checkout that holds sdcard/ and content/. On a plain
#                  Linux machine that is the same checkout (the default).
#                  On Windows + WSL it can be a second copy on the Windows
#                  drive, so the SD card files are reachable from Windows.
#
# Machine-specific values go in ~/.config/android3ds/env (plain shell
# assignments), which is read first and never committed. For example:
#
#     ANDROID3DS_WIN="/mnt/c/path/to/Android3DS"
#     ANDROID3DS_SUDO_PASSWORD=...   # only if sudo must not prompt
#
# a3ds_sudo runs a command as root. It uses ANDROID3DS_SUDO_PASSWORD when
# set (for unattended runs) and plain sudo otherwise, and always keeps the
# two path variables.

_a3ds_cfg="${XDG_CONFIG_HOME:-$HOME/.config}/android3ds/env"
if [ -f "$_a3ds_cfg" ]; then
    . "$_a3ds_cfg"
fi
unset _a3ds_cfg
: "${ANDROID3DS_ROOT:=$HOME/android3ds}"
: "${ANDROID3DS_WIN:=$ANDROID3DS_ROOT}"
export ANDROID3DS_ROOT ANDROID3DS_WIN

a3ds_sudo() {
    if [ -n "${ANDROID3DS_SUDO_PASSWORD:-}" ]; then
        printf '%s\n' "$ANDROID3DS_SUDO_PASSWORD" |
            sudo -S -p '' --preserve-env=ANDROID3DS_ROOT,ANDROID3DS_WIN "$@"
    else
        sudo --preserve-env=ANDROID3DS_ROOT,ANDROID3DS_WIN "$@"
    fi
}
