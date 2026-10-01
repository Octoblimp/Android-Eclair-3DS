#!/bin/bash
# Release wrapper: build and publish Phone, Contacts, and Messages together.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

PROJECT="${ANDROID3DS_WIN}"
export STAGE_TELCO_APPS=1
exec bash "$PROJECT/scripts/build_telco_stock_apps.sh"
