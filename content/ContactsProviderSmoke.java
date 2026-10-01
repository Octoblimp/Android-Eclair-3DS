package com.android.providers.contacts;

import android.content.ContextWrapper;
import android.content.ContentResolver;
import android.content.res.Resources;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import java.io.File;
import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;

/** Original provider schema/ICU test; only the external sync service is stubbed. */
public final class ContactsProviderSmoke {
    static void require(boolean value, String label) {
        if (!value) throw new AssertionError(label);
    }
    static long scalar(SQLiteDatabase db, String query) {
        Cursor c = db.rawQuery(query, null);
        try { require(c.moveToFirst(), "result missing"); return c.getLong(0); }
        finally { c.close(); }
    }
    public static void main(String[] args) throws Exception {
        Class<?> service = Class.forName("android.content.IContentService");
        Field field = ContentResolver.class.getDeclaredField("sContentService");
        field.setAccessible(true);
        field.set(null, Proxy.newProxyInstance(service.getClassLoader(), new Class<?>[] {service},
                new InvocationHandler() {
                    public Object invoke(Object proxy, Method method, Object[] arguments) { return null; }
                }));
        ContextWrapper context = new ContextWrapper(null) {
            public Resources getResources() { return Resources.getSystem(); }
            public String getPackageName() { return "com.android.providers.contacts"; }
        };
        String path = "/data/contacts-provider-smoke.db";
        new File(path).delete();
        SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(path, null);
        new ContactsDatabaseHelper(context).onCreate(db);
        require(NameNormalizer.normalize("Andre").equals(NameNormalizer.normalize("ANDRE")), "ICU name matching");
        db.execSQL("INSERT INTO raw_contacts(_id,display_name) VALUES(1,'Fixture Contact')");
        db.execSQL("INSERT INTO calls(number,date,duration,type,new) VALUES('4321',1000,12,2,0)");
        require(scalar(db, "SELECT count(*) FROM calls") == 1, "call log storage");
        require(scalar(db, "SELECT count(*) FROM raw_contacts") == 1, "contact storage");
        db.close();
        db = SQLiteDatabase.openOrCreateDatabase(path, null);
        require(scalar(db, "SELECT count(*) FROM calls WHERE number='4321'") == 1, "call log reopen");
        db.close();
        System.out.println("PASS: ContactsProvider ARM schema, ICU names, contacts, call log and reopen");
        System.exit(0);
    }
}
