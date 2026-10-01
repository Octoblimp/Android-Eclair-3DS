"""Android3DS build paths for the Python scripts in this directory.

The same two locations as a3ds_env.sh, resolved the same way: the
environment first, then ~/.config/android3ds/env, then the defaults.

    ANDROID3DS_ROOT  the Linux checkout (third_party/, toolchain/, build/);
                     default ~/android3ds
    ANDROID3DS_WIN   the checkout holding sdcard/ and content/; default
                     ANDROID3DS_ROOT
"""

import os
import shlex


def _config():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    values = {}
    try:
        with open(os.path.join(base, "android3ds", "env")) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                try:
                    parts = shlex.split(value, comments=True)
                except ValueError:
                    continue
                values[key.strip()] = parts[0] if parts else ""
    except IOError:
        pass
    return values


_CFG = _config()


def _get(name, default):
    return os.environ.get(name) or _CFG.get(name) or default


A3DS_ROOT = _get("ANDROID3DS_ROOT", os.path.expanduser("~/android3ds"))
A3DS_WIN = _get("ANDROID3DS_WIN", A3DS_ROOT)
