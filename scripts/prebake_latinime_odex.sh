#!/bin/bash
# Generate the side-by-side ARM odex for AOSP LatinIME (the system keyboard).
set -euo pipefail

export APK_NAME=LatinIME
exec bash "$(dirname "$0")/prebake_launcher_odex.sh"
