#!/bin/bash
# Resume the fail-fast release build after framework.jar has compiled.
set -euo pipefail

S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for script in \
    deploy_framework_jar.sh patch_n3ds_statusbar.py \
    build_services_jar.sh deploy_services_jar.sh build_keychars.sh \
    build_launcher.sh build_browser.sh build_settings_provider.sh build_settings_app.sh \
    build_latinime.sh \
    retire_legacy_mobiledata.py test_legacy_mobiledata_retired.py \
    test_3ds_telco_client.py \
    build_touchdiag_app.sh build_globaltime_app.sh \
    build_n3dsdialer_app.sh build_development_app.sh \
    build_minimal_initramfs.sh build_arm9linuxfw.sh build_firm_loader.sh \
    sync_android_to_sdcard.sh build_dexpreopt_qemu.sh \
    test_bitmap_resources_qemu.sh test_key_input_qemu.sh \
    test_pixelflinger_codegen_qemu.sh test_zygote_preload_qemu.sh \
    prebake_launcher_odex.sh prebake_browser_odex.sh prebake_settings_provider_odex.sh \
    prebake_settings_app_odex.sh prebake_touchdiag_app_odex.sh \
    prebake_globaltime_app_odex.sh prebake_latinime_odex.sh \
    prebake_n3dsdialer_app_odex.sh prebake_development_app_odex.sh sync_android_to_sdcard.sh \
    test_installd_qemu.sh; do
    echo "=== $script ==="
    case "$script" in
        *.py) python3 "$S/$script" ;;
        *) bash "$S/$script" ;;
    esac
done

echo '=== resume_release_after_framework: ALL OK ==='
