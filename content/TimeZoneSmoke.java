package android3ds;

import android.net.SntpClient;
import android.os.SystemClock;

import java.util.Arrays;
import java.util.Calendar;
import java.util.GregorianCalendar;
import java.util.TimeZone;

/**
 * #327: America/Chicago "did not exist" on the device because no zoneinfo
 * database was shipped, and automatic time landed hours off because Eclair's
 * SntpClient doubled the clock offset. This runs the real core.jar and
 * framework.jar under qemu-arm against the staged /system.
 */
public class TimeZoneSmoke {
    private static final long HOUR = 3600L * 1000L;

    private static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError("FAIL: " + what);
        System.out.println("ok: " + what);
    }

    private static long utc(int year, int month, int day) {
        Calendar c = new GregorianCalendar(TimeZone.getTimeZone("UTC"));
        c.clear();
        c.set(year, month, day, 12, 0, 0);
        return c.getTimeInMillis();
    }

    public static void main(String[] args) {
        String[] ids = TimeZone.getAvailableIDs();
        check(ids.length > 300, "zoneinfo index has " + ids.length + " zones");
        check(Arrays.asList(ids).contains("America/Chicago"), "America/Chicago is listed");

        TimeZone chicago = TimeZone.getTimeZone("America/Chicago");
        check("America/Chicago".equals(chicago.getID()), "id resolves (got " + chicago.getID() + ")");
        check(chicago.getRawOffset() == -6 * HOUR, "raw offset -6h (got " + chicago.getRawOffset() + ")");
        check(chicago.getOffset(utc(2026, Calendar.JANUARY, 15)) == -6 * HOUR, "January is CST -6h");
        check(chicago.getOffset(utc(2026, Calendar.JULY, 1)) == -5 * HOUR, "July is CDT -5h");
        check(chicago.useDaylightTime(), "Chicago observes DST");

        TimeZone tokyo = TimeZone.getTimeZone("Asia/Tokyo");
        check(tokyo.getRawOffset() == 9 * HOUR, "Asia/Tokyo +9h");
        TimeZone london = TimeZone.getTimeZone("Europe/London");
        check(london.getOffset(utc(2026, Calendar.JULY, 1)) == HOUR, "Europe/London BST +1h");

        // SNTP: the device sets its clock from this exact class. Needs the
        // network, so an unreachable server is a skip, never a pass or fail.
        String server = args.length > 0 ? args[0] : "pool.ntp.org";
        SntpClient sntp = new SntpClient();
        if (sntp.requestTime(server, 5000)) {
            long ntpNow = sntp.getNtpTime() + SystemClock.elapsedRealtime() - sntp.getNtpTimeReference();
            long skew = ntpNow - System.currentTimeMillis();
            System.out.println("sntp " + server + " skew vs host clock = " + skew + " ms");
            check(Math.abs(skew) < 5000, "SntpClient agrees with the host clock within 5 s");
        } else {
            System.out.println("SKIP: SNTP server " + server + " unreachable");
        }

        System.out.println("PASS: zoneinfo America/Chicago + SNTP offset");
    }
}
