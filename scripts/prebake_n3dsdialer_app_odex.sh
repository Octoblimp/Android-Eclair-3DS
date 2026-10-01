#!/bin/bash
set -e
export APK_NAME=N3dsDialer
exec bash "$(dirname "$0")/prebake_launcher_odex.sh"
