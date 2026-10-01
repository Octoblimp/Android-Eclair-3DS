#!/bin/bash
# Odex pre-bake wrapper for the real upstream Dev Tools port
# (com.android.development). Replaced the custom DevTools app and its
# prebake_devtools_app_odex.sh, both deleted 2026-09-10.
set -e
export APK_NAME=Development
exec bash "$(dirname "$0")/prebake_launcher_odex.sh"
