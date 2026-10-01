#!/bin/bash
set -e
export APK_NAME=Browser
exec bash "$(dirname "$0")/prebake_launcher_odex.sh"
