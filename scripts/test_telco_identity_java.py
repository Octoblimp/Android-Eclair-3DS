#!/usr/bin/env python3
"""Execute the production MAC, copied-code and endpoint-bar Java methods."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PHONE = ROOT / 'content/stock-app-overlays/Phone/src/com/android/phone'
service = (PHONE / 'TelcoService.java').read_text()
settings = (ROOT / 'content/settings/src/com/android/settings/MobileDataSettings.java').read_text()
policy = (ROOT / 'third_party/frameworks/base/services/java/com/android/server/status/StatusBarPolicy.java').read_text()

def method(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    cursor = opening + 1
    while depth:
        depth += (source[cursor] == '{') - (source[cursor] == '}')
        cursor += 1
    return source[start:cursor]

mac = method(service, 'private static boolean validMac(')
code = method(service, 'private static String normalizeProvisioningCode(')
assert code == method(settings, 'private static String normalizeProvisioningCode(')
bars = method(policy, 'private int getN3dsTelcoSignalLevel(')
online = method(policy, 'private boolean isN3dsTelcoOnline(')
with tempfile.TemporaryDirectory(prefix='telco-identity-') as directory:
    root = Path(directory)
    java = '''public class Harness {
        static long latency;
        static long sample = 99999;
        static int enabled = 1;
        static String status = "Online over Wi-Fi";
        Context mContext = new Context();
        static class Context { Object getContentResolver() { return null; } }
        static class Settings { static class System {
            static long getLong(Object resolver, String key, long fallback) { return key.contains("sample") ? sample : latency; }
            static int getInt(Object resolver, String key, int fallback) { return enabled; }
            static String getString(Object resolver, String key) { return status; }
        } }
    ''' + mac + '\n' + code + '\n' + bars + '\n' + online + '''
        static void check(boolean value) { if (!value) throw new AssertionError(); }
        public static void main(String[] args) {
            check(!validMac(null)); check(!validMac("00:00:00:00:00:00"));
            check(!validMac("02:00:00:00:00:00")); check(!validMac("ff:ff:ff:ff:ff:ff"));
            check(!validMac("01:11:22:33:44:55")); check(validMac("02:11:22:33:44:55"));
            check(validMac("00:11:22:AA:bb:cc"));
            check("ABCD1234EFGH".equals(normalizeProvisioningCode(" abcd-1234-efgh ")));
            check(!normalizeProvisioningCode("bad!code!").matches("[A-Z0-9]{8,80}"));
            long[] times = {-1,0,149,150,399,400,999,1000,2499,2500,9000};
            int[] expected = {0,4,4,3,3,2,2,1,1,0,0};
            Harness h = new Harness();
            for (int i=0; i<times.length; i++) { latency=times[i]; check(h.getN3dsTelcoSignalLevel()==expected[i]); }
            check(h.isN3dsTelcoOnline());
            sample=54999; check(!h.isN3dsTelcoOnline());
            sample=55000; check(h.isN3dsTelcoOnline());
            sample=100001; check(!h.isN3dsTelcoOnline());
            sample=99999; enabled=0; check(!h.isN3dsTelcoOnline());
            enabled=1; status="Offline"; check(!h.isN3dsTelcoOnline());
            java.lang.System.out.println("telco_identity_java: PASS (MAC, code normalization, latency boundaries, stale/future/disabled/offline state)");
        }
    }'''
    (root / 'Harness.java').write_text(java)
    clock = root / 'android/os/SystemClock.java'
    clock.parent.mkdir(parents=True)
    clock.write_text('package android.os; public class SystemClock { public static long elapsedRealtime() { return 100000; } }')
    subprocess.run(['javac', '-d', str(root), str(root / 'Harness.java'), str(clock)], check=True)
    subprocess.run(['java', '-cp', str(root), 'Harness'], check=True)
