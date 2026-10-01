package com.android.phone;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Durable, user-visible 3DSTelco registration state stored on the FAT32
 * sdcard.  Updates use a synced sibling and atomic rename so duplicate or
 * stale credential lines cannot accumulate across enroll/clear cycles and a
 * failed write cannot destroy the last known-good registration.
 */
final class TelcoConfig {
    static final String READY = "N3DS_TELCO_DURABLE_REGISTRATION_READY";
    static final String REGISTRATION_CONFIG = "/sdcard/persistent/shared/mobile_registration.conf";
    static final String KEY_MOBILE_DATA_ON_BOOT = "mobile_data_on_boot";
    static final String KEY_SETUP_CODE = "setup_code";
    static final String KEY_TOKEN = "token";
    static final String KEY_NUMBER = "number";
    static final String KEY_ENDPOINT = "endpoint";
    static final String KEY_EXPIRES_AT = "expires_at";
    private static final long MAX_CONFIG_BYTES = 8192;
    private static final int MAX_CONFIG_LINES = 32;
    private static final int MAX_LINE_CHARS = 1024;

    private TelcoConfig() {
    }

    /** Parse the user-owned configuration file into (key, value) pairs. */
    static Map<String, String> read() throws IOException {
        Map<String, String> values = new LinkedHashMap<String, String>();
        File file = new File(REGISTRATION_CONFIG);
        if (!file.exists()) {
            return values;
        }
        if (!file.isFile() || file.length() > MAX_CONFIG_BYTES)
            throw new IOException("Registration configuration is unavailable.");
        BufferedReader reader = null;
        try {
            reader = new BufferedReader(new FileReader(file), 1024);
            String line;
            int lineCount = 0;
            while ((line = reader.readLine()) != null) {
                if (++lineCount > MAX_CONFIG_LINES || line.length() > MAX_LINE_CHARS) {
                    throw new IOException("Registration configuration exceeds limits.");
                }
                line = line.trim();
                if (line.length() == 0 || line.startsWith("#")) {
                    continue;
                }
                int eq = line.indexOf('=');
                if (eq <= 0) throw new IOException("Malformed registration configuration.");
                String key = line.substring(0, eq).trim();
                String value = line.substring(eq + 1).trim();
                if (isKnownKey(key) && value.length() == 0) continue;
                if (!isKnownKey(key) || !validValue(key, value))
                    throw new IOException("Invalid registration configuration.");
                values.put(key, value);
            }
        } catch (IOException error) {
            values.clear();
            throw error;
        } catch (Exception error) {
            values.clear();
            throw new IOException("Unable to read registration configuration.");
        } finally {
            close(reader);
        }
        return values;
    }

    /** Persist the issued credential set over any existing values. */
    static void writeEnrollment(String token, String number, String endpoint,
            String expiresAt, boolean mobileDataOnBoot) throws IOException {
        Map<String, String> values = read();
        values.put(KEY_MOBILE_DATA_ON_BOOT, mobileDataOnBoot ? "1" : "0");
        values.remove(KEY_SETUP_CODE);
        values.put(KEY_TOKEN, token);
        values.put(KEY_NUMBER, number);
        values.put(KEY_ENDPOINT, endpoint);
        values.put(KEY_EXPIRES_AT, expiresAt == null ? "" : expiresAt);
        write(values);
    }

    static void setMobileDataOnBoot(boolean enabled) throws IOException {
        Map<String, String> values = read();
        values.put(KEY_MOBILE_DATA_ON_BOOT, enabled ? "1" : "0");
        write(values);
    }

    static void setEndpoint(String endpoint) throws IOException {
        if (!TelcoContract.validEndpoint(endpoint))
            throw new IOException("Invalid 3DSTelco endpoint.");
        Map<String, String> values = read();
        values.put(KEY_ENDPOINT, endpoint);
        write(values);
    }

    /** Drop authenticating values while keeping non-secret settings. */
    static void clearCredentials() throws IOException {
        Map<String, String> values = read();
        values.remove(KEY_TOKEN);
        values.remove(KEY_NUMBER);
        values.remove(KEY_EXPIRES_AT);
        write(values);
    }

    static void clearSetupCode() throws IOException {
        Map<String, String> values = read();
        values.remove(KEY_SETUP_CODE);
        write(values);
    }

    private static void write(Map<String, String> values) throws IOException {
        for (Map.Entry<String, String> entry : values.entrySet()) {
            String value = entry.getValue();
            if (value == null || value.length() == 0) continue;
            if (!isKnownKey(entry.getKey()) || value.indexOf('\n') >= 0 || value.indexOf('\r') >= 0
                    || !validValue(entry.getKey(), value))
                throw new IOException("Invalid registration configuration value.");
        }
        StringBuilder out = new StringBuilder();
        out.append("# 3DSTelco Mobile Registration Configuration\n");
        appendLine(out, values, KEY_MOBILE_DATA_ON_BOOT);
        appendLine(out, values, KEY_SETUP_CODE);
        appendLine(out, values, KEY_TOKEN);
        appendLine(out, values, KEY_NUMBER);
        appendLine(out, values, KEY_ENDPOINT);
        appendLine(out, values, KEY_EXPIRES_AT);
        File file = new File(REGISTRATION_CONFIG);
        File parent = file.getParentFile();
        File temporary = null;
        FileOutputStream output = null;
        BufferedWriter writer = null;
        try {
            if (parent != null && !parent.exists() && !parent.mkdirs()) {
                throw new IOException("Unable to create registration directory.");
            }
            if (parent == null || !parent.isDirectory()) {
                throw new IOException("Registration directory is unavailable.");
            }
            // Write and sync a sibling first; a failed update leaves the last
            // known-good registration file untouched.
            temporary = File.createTempFile(".3ds-reg-", ".tmp", parent);
            output = new FileOutputStream(temporary, false);
            writer = new BufferedWriter(new OutputStreamWriter(output, "UTF-8"));
            writer.write(out.toString());
            writer.flush();
            output.getFD().sync();
            writer.close();
            writer = null;
            output = null;
            if (!temporary.renameTo(file)) {
                throw new IOException("Unable to atomically replace registration file.");
            }
            temporary = null;
        } finally {
            close(writer);
            close(output);
            if (temporary != null) temporary.delete();
        }
    }

    private static boolean isKnownKey(String key) {
        return KEY_MOBILE_DATA_ON_BOOT.equals(key) || KEY_SETUP_CODE.equals(key)
                || KEY_TOKEN.equals(key) || KEY_NUMBER.equals(key)
                || KEY_ENDPOINT.equals(key) || KEY_EXPIRES_AT.equals(key);
    }

    private static boolean validValue(String key, String value) {
        if (value.length() > MAX_LINE_CHARS) return false;
        if (KEY_MOBILE_DATA_ON_BOOT.equals(key)) return "0".equals(value) || "1".equals(value);
        if (KEY_SETUP_CODE.equals(key)) return value.matches("[A-Za-z0-9-]{8,80}");
        if (KEY_TOKEN.equals(key)) return value.matches("[A-Za-z0-9_-]{40,120}");
        if (KEY_NUMBER.equals(key)) return value.matches("[1-9][0-9]{2,3}");
        if (KEY_ENDPOINT.equals(key)) return TelcoContract.validEndpoint(value);
        return KEY_EXPIRES_AT.equals(key) && value.matches("[0-9TZ :+.\\-]{1,64}");
    }

    private static void appendLine(StringBuilder out, Map<String, String> values, String key) {
        String value = values.get(key);
        if (value != null && value.length() > 0) {
            out.append(key).append('=').append(value).append('\n');
        }
    }

    private static void close(BufferedReader reader) {
        if (reader != null) {
            try {
                reader.close();
            } catch (Exception ignored) {
            }
        }
    }

    private static void close(BufferedWriter writer) {
        if (writer != null) {
            try {
                writer.close();
            } catch (Exception ignored) {
            }
        }
    }

    private static void close(FileOutputStream output) {
        if (output != null) {
            try {
                output.close();
            } catch (Exception ignored) {
            }
        }
    }
}
