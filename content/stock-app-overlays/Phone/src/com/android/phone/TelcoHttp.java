package com.android.phone;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/** Modern certificate-verified HTTPS through the private stdin-only helper. */
final class TelcoHttp {
    static final String NATIVE_READY = "N3DS_TELCO_NATIVE_HTTPS_READY";
    private static final String TRANSPORT = "/system/bin/telco_https";
    private static final int MAX_RESPONSE = 131072;
    // 60s of 8kHz mono 16-bit PCM, the voicemail cap the backend enforces.
    private static final int MAX_BINARY_RESPONSE = 60 * 8000 * 2;

    static final class Failure extends Exception {
        final int status;
        final String code;
        Failure(int status, String code, String message) { super(message); this.status = status; this.code = code; }
    }

    private final Context context;
    private final SharedPreferences secrets;

    TelcoHttp(Context context) {
        this.context = context;
        secrets = context.getSharedPreferences("n3ds_telco_credentials", Context.MODE_PRIVATE);
    }

    String token() {
        String credentialEndpoint = secrets.getString("endpoint", null);
        return TelcoContract.endpoint(context).equals(credentialEndpoint)
                ? secrets.getString("token", null) : null;
    }
    String number() { return token() == null ? null : secrets.getString("number", null); }
    void clear() throws Exception {
        // Keep the app-private credential until the durable file has been
        // updated.  If the SD card is unavailable, a valid registration is
        // never silently discarded and the caller reports the failure.
        TelcoConfig.clearCredentials();
        if (!secrets.edit().clear().commit())
            throw new Exception("Unable to clear the durable 3DSTelco registration.");
    }

    /** Rehydrate validated credentials from the user-owned configuration file. */
    void restoreFromConfig() throws Exception {
        java.util.Map<String, String> conf = TelcoConfig.read();
        String token = conf.get(TelcoConfig.KEY_TOKEN);
        String number = conf.get(TelcoConfig.KEY_NUMBER);
        String confEndpoint = conf.get(TelcoConfig.KEY_ENDPOINT);
        if (token == null || number == null || confEndpoint == null) return;
        if (!TelcoContract.endpoint(context).equals(confEndpoint)) return;
        if (token.length() < 40 || !token.matches("[A-Za-z0-9_-]{40,120}")
                || !number.matches("[1-9][0-9]{2,3}")) return;
        String expiresAt = conf.get(TelcoConfig.KEY_EXPIRES_AT);
        if (!secrets.edit().putString("token", token).putString("number", number)
                .putString("endpoint", confEndpoint)
                .putString("expires_at", expiresAt == null ? "" : expiresAt).commit())
            throw new Exception("Unable to restore saved registration.");
    }

    void saveEnrollment(JSONObject response) throws Exception {
        String token = response.getString("token");
        String number = response.getString("number");
        if (token.length() < 40 || !token.matches("[A-Za-z0-9_-]{40,120}")
                || !number.matches("[1-9][0-9]{2,3}")) {
            throw new Exception("Server returned an invalid identity.");
        }
        String endpoint = TelcoContract.endpoint(context);
        String expiresAt = response.optString("expires_at", "");
        // Keep the issued token recoverable if the SD write fails after the
        // one-time code was consumed. A poll retries this pending file write;
        // it must succeed before we claim registration/online success.
        if (!secrets.edit().putString("token", token).putString("number", number)
                .putString("endpoint", endpoint).putString("expires_at", expiresAt)
                .putBoolean("pending_config", true)
                .commit())
            throw new Exception("Unable to persist the 3DSTelco registration.");
        persistPendingEnrollment();
    }

    void persistPendingEnrollment() throws Exception {
        if (!secrets.getBoolean("pending_config", false) || token() == null) return;
        try {
            TelcoConfig.writeEnrollment(token(), number(), TelcoContract.endpoint(context),
                    secrets.getString("expires_at", ""), TelcoContract.enabled(context));
        } catch (java.io.IOException error) {
            throw new Failure(503, "registration_storage_failed",
                    "Registration received, but mobile_registration.conf could not be saved. Check SD storage; the save will retry.");
        }
        if (!secrets.edit().putBoolean("pending_config", false).commit())
            throw new Exception("Registration file saved; local confirmation will retry.");
    }

    JSONObject request(String method, String path, JSONObject body, boolean authenticated) throws Exception {
        byte[] payload = body == null ? new byte[0] : body.toString().getBytes("UTF-8");
        Result result = exchange(method, path, payload, authenticated, MAX_RESPONSE);
        String text = new String(result.body, "UTF-8");
        JSONObject response = text.length() == 0 ? new JSONObject() : new JSONObject(text);
        if (result.status < 200 || result.status >= 300) {
            String code = response.optString("error", "http_" + result.status);
            if (result.status == 401 && authenticated) clear();
            throw new Failure(result.status, code, response.optString("message", "3DSTelco request failed."));
        }
        return response;
    }

    /**
     * Fetches a raw (non-JSON) authenticated response, e.g. recorded
     * voicemail audio. The envelope already carries an arbitrary-length body
     * after its LENGTH header, so this needs no transport-binary change --
     * only a response path here that skips JSON decoding.
     */
    byte[] requestBinary(String path) throws Exception {
        Result result = exchange("GET", path, new byte[0], true, MAX_BINARY_RESPONSE);
        if (result.status < 200 || result.status >= 300) {
            if (result.status == 401) clear();
            String text = new String(result.body, "UTF-8");
            JSONObject response;
            try { response = text.length() == 0 ? new JSONObject() : new JSONObject(text); }
            catch (Exception ignored) { response = new JSONObject(); }
            throw new Failure(result.status, response.optString("error", "http_" + result.status),
                    response.optString("message", "3DSTelco request failed."));
        }
        return result.body;
    }

    private static final class Result {
        final int status;
        final byte[] body;
        Result(int status, byte[] body) { this.status = status; this.body = body; }
    }

    private Result exchange(String method, String path, byte[] payload, boolean authenticated, int maxResponse) throws Exception {
        if (!TelcoContract.enabled(context)) throw new Failure(503, "mobile_data_disabled", "Mobile Data is disabled in Settings.");
        if (!TelcoContract.wifiConnected(context)) throw new Failure(503, "wifi_required", "Connect Wi-Fi before using 3DSTelco.");
        if (!("GET".equals(method) || "POST".equals(method) || "DELETE".equals(method))
                || path == null || !path.startsWith("/"))
            throw new Failure(400, "invalid_request", "The 3DSTelco request is invalid.");
        String authorization = "-";
        if (authenticated) {
            authorization = token();
            if (authorization == null) throw new Failure(401, "not_enrolled", "Register this 3DS in Settings first.");
        }
        if (payload.length > 16384) throw new Failure(413, "request_too_large", "Request exceeded 16 KiB.");

        Process process;
        try { process = Runtime.getRuntime().exec(new String[] {TRANSPORT}); }
        catch (Exception error) { throw new Failure(503, "https_transport_missing", "The 3DSTelco HTTPS transport is unavailable."); }
        StreamCollector errors = new StreamCollector(process.getErrorStream(), 4096);
        Thread errorThread = new Thread(errors, "3DSTelco-https-errors");
        errorThread.start();
        try {
            OutputStream input = process.getOutputStream();
            writeLine(input, "N3DS-TELCO-HTTPS/1");
            writeLine(input, "METHOD " + method);
            writeLine(input, "URL " + TelcoContract.endpoint(context) + path);
            writeLine(input, "TOKEN " + authorization);
            writeLine(input, "BODY " + payload.length);
            writeLine(input, "");
            input.write(payload);
            input.close();

            InputStream output = process.getInputStream();
            String magic = readLine(output, 64);
            String statusLine = readLine(output, 64);
            String lengthLine = readLine(output, 64);
            String separator = readLine(output, 4);
            if (!"N3DS-TELCO-HTTPS/1".equals(magic) || !statusLine.startsWith("STATUS ")
                    || !lengthLine.startsWith("LENGTH ") || separator.length() != 0)
                throw new Exception("The HTTPS transport returned a malformed envelope.");
            int status = Integer.parseInt(statusLine.substring(7));
            int length = Integer.parseInt(lengthLine.substring(7));
            if (status < 100 || status > 599 || length < 0 || length > maxResponse)
                throw new Exception("The HTTPS transport returned invalid bounds.");
            byte[] responseBytes = readExactly(output, length);
            output.close();
            int exit = process.waitFor();
            errorThread.join();
            if (exit != 0) throw new Exception(errors.text("HTTPS request failed."));
            return new Result(status, responseBytes);
        } catch (Failure error) {
            throw error;
        } catch (Exception error) {
            try { process.destroy(); } catch (Exception ignored) {}
            try { errorThread.join(1000); } catch (InterruptedException ignored) {}
            String detail = errors.text(error.getMessage() == null ? "HTTPS request failed." : error.getMessage());
            throw new Failure(503, "https_transport_failed", detail);
        } finally {
            try { process.destroy(); } catch (Exception ignored) {}
        }
    }

    private static void writeLine(OutputStream output, String line) throws Exception {
        output.write(line.getBytes("UTF-8"));
        output.write('\n');
    }

    private static String readLine(InputStream input, int limit) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        while (output.size() <= limit) {
            int value = input.read();
            if (value < 0) throw new Exception("The HTTPS transport closed early.");
            if (value == '\n') return new String(output.toByteArray(), "UTF-8");
            if (value != '\r') output.write(value);
        }
        throw new Exception("The HTTPS transport line was too long.");
    }

    private static byte[] readExactly(InputStream input, int length) throws Exception {
        byte[] bytes = new byte[length];
        int offset = 0;
        while (offset < length) {
            int count = input.read(bytes, offset, length - offset);
            if (count < 0) throw new Exception("The HTTPS response ended early.");
            offset += count;
        }
        return bytes;
    }

    private static final class StreamCollector implements Runnable {
        private final InputStream input;
        private final int limit;
        private final ByteArrayOutputStream output = new ByteArrayOutputStream();
        StreamCollector(InputStream input, int limit) { this.input = input; this.limit = limit; }
        public void run() {
            byte[] bytes = new byte[512];
            try {
                int count;
                while ((count = input.read(bytes)) >= 0 && output.size() < limit) {
                    output.write(bytes, 0, Math.min(count, limit - output.size()));
                }
            } catch (Exception ignored) {
            } finally { try { input.close(); } catch (Exception ignored) {} }
        }
        String text(String fallback) {
            try {
                String value = new String(output.toByteArray(), "UTF-8").trim();
                return value.length() == 0 ? fallback : value;
            } catch (Exception ignored) { return fallback; }
        }
    }
}
