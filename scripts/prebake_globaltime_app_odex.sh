#!/bin/bash
set -e
export APK_NAME=GlobalTime
exec bash "$(dirname "$0")/prebake_launcher_odex.sh"
