#!/bin/bash
set -e
export APK_NAME=MediaProvider
exec bash "$(dirname "$0")/prebake_launcher_odex.sh"
