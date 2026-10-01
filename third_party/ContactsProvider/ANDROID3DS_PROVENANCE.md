# ContactsProvider source provenance

Official AOSP `platform/packages/providers/ContactsProvider`, fetched 2026-09-06
from https://android.googlesource.com/platform/packages/providers/ContactsProvider
at `android-2.0_r1`, commit `22d6a52eace0dab1e6a570bbfeb2b49c2858214f`.

Matches the canonical Android framework tag. Original sources and license
headers remain intact. `scripts/build_contacts_provider.sh` removes one unused
Calendar import in its disposable build copy and signs the APK with the shared
certificate required by the original manifest. This restores contacts and
call-log storage for the stock Contacts/Dialer and Phone packages.
