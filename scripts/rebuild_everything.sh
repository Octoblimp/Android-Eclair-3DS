#!/bin/bash
# Rebuild every artifact used by the Android3DS boot-to-launcher path.
#
# This deliberately keeps compilation, deployment, and cache generation in
# one fail-fast pipeline.  A successful compile is not sufficient in this
# tree: rootfs_overlay is the source of truth, output/target is additive, and
# sdcard/ is a third copy that can otherwise retain an older executable.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

S_WIN="${ANDROID3DS_WIN}/scripts"
S_WSL="${ANDROID3DS_ROOT}/scripts"
ROOT="${ANDROID3DS_ROOT}"
BUILDROOT="$ROOT/third_party/buildroot"
OVERLAY="$BUILDROOT/board/nintendo3ds/rootfs_overlay"
TARGET="$BUILDROOT/output/target"
LOG="$ROOT/rebuild_everything.log"

: > "$LOG"

find_script() {
    if [ -f "$S_WIN/$1" ]; then
        printf '%s\n' "$S_WIN/$1"
    elif [ -f "$S_WSL/$1" ]; then
        printf '%s\n' "$S_WSL/$1"
    else
        echo "FATAL: build script not found: $1" >&2
        return 1
    fi
}

run() {
    local script path
    script="$1"
    path="$(find_script "$script")"
    echo "=== $script ===" | tee -a "$LOG"
    if [[ "$path" == *.py ]]; then
        runner=(python3 "$path")
    else
        runner=(bash "$path")
    fi
    if ! "${runner[@]}" >> "$LOG" 2>&1; then
        echo "FATAL: $script failed; tail of $LOG follows" | tee -a "$LOG"
        tail -80 "$LOG"
        exit 1
    fi
}

# Patch hardware input and policy before either the kernel or services.jar is
# built.  The patch is idempotent and validates every expected source hunk.
run patch_update_safe_prefs.py
run patch_wifi_manual_boot_enable.py
run patch_telco_service.py
run patch_android_payload_layout.py
run patch_wireless_adb_init.py
run patch_n3ds_input.py
run patch_n3ds_hardware_input.py
run patch_n3ds_gralloc.py
run patch_n3ds_display_touch_recovery.py
run patch_n3ds_bootanim_touch.py
run patch_n3ds_slow_input_timeout.py
run patch_n3ds_touch_launcher_smp.py
run patch_arm9_sd_recovery.py
run patch_arm9_sd_luma_stability.py
run patch_arm9_sd_read_fallback.py
run patch_arm9_sd_adaptive_recovery.py
run patch_arm9_virtio_blk_abi.py
run patch_arm9_pxi_fairness.py
run patch_boot_io_quiet.py
run patch_ctr_sdhc_trace_control.py
# Keep the AR6014 scan safety fixes in the canonical clean rebuild.  The
# targeted entry point upgrades itself to the address-independent locator;
# channel validation must run after that replacement so it cannot be lost.
run patch_wifi_scan_ie_capability.py
run patch_wifi_bss_channel_guard.py
run patch_wifi_irq_panic_recovery.py
run patch_ar6014_2ghz_scan.py
run patch_ar6014_remove_ram_harvest.py
run patch_ar6014_association.py
run patch_ar6014_direct_reconnect.py
run patch_ar6014_nwm_keepalive.py
run patch_ar6014_connect_ctrl_flags_sweep.py
run patch_ar6014_nwm_host_wpa.py
run patch_ar6014_nwm_wmi_header.py
run patch_ar6014_nwm_data_header.py
run patch_ar6014_nwm_ready_layout.py
run patch_ar6014_nwm_channel_table.py
run patch_ar6014_nwm_connection_scan.py
run patch_ar6014_discovery_connect_split.py
run repair_ar6014_streetpass_ioctl.py
run port_ar6014_wext_ap.py
run patch_n3ds_wifi_sdio_recovery.py
run patch_wifi_reloadable_driver.py
run retire_legacy_mobiledata.py
run test_legacy_mobiledata_retired.py
run test_ar6014_ioctl_contract.py
run test_n3ds_wifi_sdio_recovery.py
run test_ar6014_wext_ap.py
run patch_wpa_remove_scan_harvest_timeout.py
run patch_wpa_remembered_ranking.py
run patch_wpa_remembered_discovery.py
run patch_wpa_scan_security_integrity.py
# Re-extract/rebuild the patched Buildroot package before build_libhardware
# consumes wpa_ctrl.c and before build_minimal_initramfs packages the binary.
run rebuild_buildroot_wifi.sh
run patch_n3ds_runtime_diagnostics.py
run test_arm9_sd_adaptive_recovery.py
run patch_n3ds_smp_poweroff_recovery.py
run patch_n3ds_shutdown_log_finalization.py
run patch_n3ds_touch_mt_restore_logs.py
run patch_n3ds_touch_cpu_diag.py
run patch_n3ds_launcher_layout.py
run patch_launcher_repeat_longpress.py
run add_pica200_driver.py
run patch_pica200_deferred_qualify.py
run test_pica200_completion_contract.py
run patch_ctr_dsp_loader.py
run test_ctr_dsp_loader.py
run patch_n3ds_input_render_latency.py
run patch_app_process_qemu_logging.py
run enable_n3ds_gles_stack.py
run patch_armv6_smp_atomics.py
run test_armv6_smp_atomics.py
run test_armv6_smp_atomics_qemu.sh
run patch_dalvik_abort_diagnostics.py
run patch_dalvik_transient_io.py
run patch_pixelflinger_register_exhaustion.py
run patch_pixelflinger_codegen_safety.py
run patch_audiomanager_null_safety.py
run patch_n3ds_boot_completion.py
run add_boot_sequence_rootfs.py
run test_dsp_boot_chime.py
run patch_n3ds_decor_overlay.py
run patch_n3ds_dialog_title_style.py
run patch_n3ds_alert_controller.py
run patch_n3ds_copybit.py
run patch_n3ds_globaltime_render.py
run test_pica_app_render_contract.py
run test_n3ds_copybit.py
run test_n3ds_copybit_qemu.sh
run patch_wifi_led_state.py
run patch_n3ds_wifi_led_class.py
run patch_settings_wifi_resilience.py
run patch_settings_wifi_security.py
run patch_settings_wifi_remembered_profile.py
run patch_settings_wifi_protected_label.py
run patch_wifi_scan_policy.py
run patch_wifi_deferred_disconnect.py
run patch_wifi_station_scan_guard.py
run test_latinime.py
run test_launcher_repeat_longpress.py
run test_wpa_scan_security_integrity.py
run test_settings_wifi_resilience.py
run test_settings_wifi_security.py
run test_settings_wifi_remembered_profile.py
run test_settings_wifi_protected_label.py
run test_ar6014_2ghz_scan.py
run test_ar6014_direct_wmi_only.py
run test_ar6014_association.py
run test_ar6014_direct_reconnect.py
run test_ar6014_nwm_keepalive.py
run test_ar6014_connect_ctrl_flags_sweep.py
run test_ar6014_nwm_host_wpa.py
run test_ar6014_nwm_wmi_header.py
run test_ar6014_nwm_data_header.py
run test_ar6014_nwm_ready_layout.py
run test_ar6014_nwm_channel_table.py
run test_ar6014_nwm_connection_scan.py
run test_ar6014_discovery_connect_split.py
run test_ctr_sdhc_trace_control.py
run test_wpa_remembered_ranking.py
run test_wpa_remembered_discovery.py
run test_wifi_led_state.py
run test_n3ds_wifi_led_class.py
run test_wifi_scan_policy.py
run test_wifi_deferred_disconnect.py
run test_wifi_station_scan_guard.py
run test_wireless_adb.py
run test_mobile_data_settings.py
run test_3ds_telco_client.py
run test_boot_connectivity_config.py
run test_telco_live_regressions.py
run test_telco_stock_apps_boot.py
run test_telco_message_persistence.py
run test_telco_config_java.py
run test_telco_identity_java.py
run test_telco_persistence.py
run test_supplicant_boot_toggle.sh
run test_wifi_reloadable_driver.py
run test_update_safe_prefs.py
run test_dalvik_abort_diagnostics.py
run test_app_process_qemu_logging.py
run test_n3ds_boot_completion.py
run test_n3ds_shutdown_log_finalization.py
run test_wifi_pipeline.py

# Kernel and hardware description.  Keep these in the same reproducible
# pipeline as userspace so a new callback or DT node cannot be built locally
# but omitted from the card image.
run build_kernel.sh
run build_dtbs.sh
run build_pica200_smoketest.sh
run build_dsp_chime.sh

# Host-side Android build tools.
run build_aapt.sh
run build_aidl.sh
run build_dx.sh

# Bionic and the external native foundations linked into app_process.
run build_bionic_libc.sh
run build_bionic_libm.sh
run build_libdl.sh
run build_zlib.sh
run build_fdlibm.sh
run build_expat_sqlite.sh
run build_openssl.sh
run build_icu4c.sh
run build_skia_deps.sh
run build_skia.sh
run build_dynamic_stack.sh

# WebCore is statically registered into app_process because this image's
# bionic app_process cannot dlopen shared JNI libraries.
# The remaining native stack, including a fresh app_process relink/deploy.
run rebuild_native_stack.sh
run patch_adbd_shell_path.py
run build_adbd.sh

# Java boot class path, framework resources, and the HOME activity.
run build_core_jar.sh
mkdir -p "$OVERLAY/system/framework" "$TARGET/system/framework"
cp "$ROOT/build/core/core.jar" "$OVERLAY/system/framework/core.jar"
cp "$ROOT/build/core/core.jar" "$TARGET/system/framework/core.jar"
chmod 644 "$OVERLAY/system/framework/core.jar" "$TARGET/system/framework/core.jar"

run build_framework_res.sh
run deploy_system_fonts.sh
run build_framework_jar.sh
run deploy_framework_jar.sh
run patch_n3ds_statusbar.py
run patch_telco_statusbar.py
run restore_n3ds_battery_statusbar.py
run test_n3ds_battery_statusbar.py
run build_services_jar.sh
run deploy_services_jar.sh
run build_keychars.sh
run build_launcher.sh
run build_browser.sh
run build_settings_provider.sh
run build_telephony_provider.sh
run build_contacts_provider.sh
run build_settings_app.sh
run build_latinime.sh
run build_touchdiag_app.sh
run build_globaltime_app.sh
run build_gpuz_app.sh
run build_n3dsdialer_app.sh
run build_development_app.sh

# The local 3DS Telco AP needs its bounded DHCP server in the rootfs before
# the initramfs and SD mirrors are assembled.
# Buildroot/sync can regenerate init.rc and build.prop after the early patch
# pass. Re-apply the idempotent lifecycle patch to output/target and both
# deploy mirrors before packaging the initramfs and final SD tree.

# Boot container and first-stage loader.
run build_minimal_initramfs.sh
run build_arm9linuxfw.sh
run build_firm_loader.sh

# Publish Android files, generate caches against exactly those files, then
# publish once more so the overlay/card mirrors contain identical odex files.
run build_telco_release_apps.sh
run sync_android_to_sdcard.sh
run build_dexpreopt_qemu.sh
run prebake_telco_odex.sh
# Exercise the native Bitmap width/height bridge and an actual scaled PNG;
# zygote at mdpi does not otherwise enter the density-scaling branch.
run test_bitmap_resources_qemu.sh
run test_key_input_qemu.sh
run test_decimal_format_qemu.sh
run test_pixelflinger_codegen_qemu.sh
# Run the real ARM zygote through every preloaded class and resource.  This
# catches missing JNI registrations/static-initializer failures before the
# image reaches physical hardware.
run test_zygote_preload_qemu.sh
run prebake_launcher_odex.sh
run prebake_browser_odex.sh
run prebake_settings_provider_odex.sh
run prebake_telephony_provider_odex.sh
run prebake_contacts_provider_odex.sh
run prebake_settings_app_odex.sh
run prebake_touchdiag_app_odex.sh
run prebake_globaltime_app_odex.sh
run prebake_gpuz_app_odex.sh
run prebake_latinime_odex.sh
run prebake_n3dsdialer_app_odex.sh
run prebake_development_app_odex.sh
run sync_android_to_sdcard.sh
run test_installd_qemu.sh
run test_telephony_provider_qemu.sh
run test_contacts_provider_qemu.sh

echo "=== rebuild_everything: ALL OK ===" | tee -a "$LOG"
