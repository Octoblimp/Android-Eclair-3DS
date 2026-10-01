#!/bin/bash
set -e
export APK_NAME=TouchDiagnostic
exec bash "$(dirname "$0")/prebake_launcher_odex.sh"
