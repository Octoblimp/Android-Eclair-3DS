/*
 * Copyright (C) 2006 The Android Open Source Project
 * Copyright (C) 2026 Android3DS contributors
 * Licensed under the Apache License, Version 2.0.
 */
package com.android.browser;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.text.SpannableString;
import android.text.method.LinkMovementMethod;
import android.text.util.Linkify;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Small browser front end for the n3ds image. The port does not yet ship the
 * native WebKit engine, so this activity uses the platform Java HTTP stack and
 * renders readable page text plus clickable links. It intentionally retains
 * the stock Browser package, launcher identity, icon, and URL intent handling.
 */
public class BrowserActivity extends Activity {
    private static final int MAX_PAGE_CHARS = 1024 * 1024;
    private final Handler mHandler = new Handler();
    private final ArrayList<String> mHistory = new ArrayList<String>();
    private EditText mAddress;
    private TextView mStatus;
    private TextView mPage;
    private Button mBack;
    private int mGeneration;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        buildUi();
        openIntent(getIntent(), true);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        openIntent(intent, true);
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        mBack = new Button(this);
        mBack.setText("<");
        mBack.setEnabled(false);
        mBack.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { goBack(); }
        });
        bar.addView(mBack, new LinearLayout.LayoutParams(48, 48));

        mAddress = new EditText(this);
        mAddress.setSingleLine(true);
        mAddress.setTextSize(13);
        mAddress.setImeOptions(EditorInfo.IME_ACTION_GO);
        mAddress.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            public boolean onEditorAction(TextView v, int actionId, KeyEvent event) {
                if (actionId == EditorInfo.IME_ACTION_GO ||
                        (event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER)) {
                    load(mAddress.getText().toString(), true);
                    return true;
                }
                return false;
            }
        });
        bar.addView(mAddress, new LinearLayout.LayoutParams(0, 48, 1));

        Button go = new Button(this);
        go.setText("Go");
        go.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { load(mAddress.getText().toString(), true); }
        });
        bar.addView(go, new LinearLayout.LayoutParams(60, 48));
        root.addView(bar);

        mStatus = new TextView(this);
        mStatus.setTextColor(Color.DKGRAY);
        mStatus.setTextSize(11);
        mStatus.setPadding(4, 0, 4, 2);
        root.addView(mStatus);

        ScrollView scroll = new ScrollView(this);
        mPage = new TextView(this);
        mPage.setTextColor(Color.BLACK);
        mPage.setLinkTextColor(Color.BLUE);
        mPage.setTextSize(13);
        mPage.setPadding(6, 3, 6, 8);
        mPage.setMovementMethod(LinkMovementMethod.getInstance());
        scroll.addView(mPage);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
    }

    private void openIntent(Intent intent, boolean addHistory) {
        Uri data = intent == null ? null : intent.getData();
        load(data == null ? "http://www.google.com/" : data.toString(), addHistory);
    }

    private void load(String input, boolean addHistory) {
        String value = input == null ? "" : input.trim();
        if (value.length() == 0) return;
        if (value.indexOf("://") < 0) {
            if (value.indexOf('.') >= 0 && value.indexOf(' ') < 0) {
                value = "http://" + value;
            } else {
                try {
                    value = "https://www.google.com/search?q=" +
                            URLEncoder.encode(value, "UTF-8");
                } catch (Exception ignored) { return; }
            }
        }
        final String requested = value;
        if (addHistory && (mHistory.size() == 0 ||
                !requested.equals(mHistory.get(mHistory.size() - 1)))) {
            mHistory.add(requested);
        }
        mBack.setEnabled(mHistory.size() > 1);
        mAddress.setText(requested);
        mStatus.setText("Loading...");
        mPage.setText("");
        final int generation = ++mGeneration;
        new Thread(new Runnable() {
            public void run() { fetch(requested, generation); }
        }, "BrowserFetch").start();
    }

    private void fetch(String requested, final int generation) {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(requested);
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(20000);
            connection.setInstanceFollowRedirects(true);
            connection.setRequestProperty("User-Agent",
                    "Mozilla/5.0 (Nintendo 3DS; Android 2.0) Mobile");
            int code = connection.getResponseCode();
            InputStream stream = code >= 400 ? connection.getErrorStream() :
                    connection.getInputStream();
            if (stream == null) throw new Exception("HTTP " + code);
            BufferedReader reader = new BufferedReader(new InputStreamReader(stream, "UTF-8"));
            StringBuilder html = new StringBuilder();
            char[] buffer = new char[4096];
            int count;
            while ((count = reader.read(buffer)) >= 0 && html.length() < MAX_PAGE_CHARS) {
                html.append(buffer, 0, Math.min(count, MAX_PAGE_CHARS - html.length()));
            }
            reader.close();
            final String finalUrl = connection.getURL().toString();
            final String text = htmlToText(html.toString(), connection.getURL());
            final String status = "HTTP " + code + "  " + finalUrl;
            mHandler.post(new Runnable() {
                public void run() {
                    if (generation != mGeneration) return;
                    mAddress.setText(finalUrl);
                    mStatus.setText(status);
                    SpannableString page = new SpannableString(text);
                    Linkify.addLinks(page, Linkify.WEB_URLS);
                    mPage.setText(page);
                }
            });
        } catch (final Exception error) {
            mHandler.post(new Runnable() {
                public void run() {
                    if (generation != mGeneration) return;
                    mStatus.setText("Could not load page");
                    mPage.setText(error.toString());
                }
            });
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static String htmlToText(String html, URL base) {
        String text = html.replaceAll("(?is)<script[^>]*>.*?</script>", "")
                .replaceAll("(?is)<style[^>]*>.*?</style>", "");
        Pattern links = Pattern.compile("(?is)<a[^>]+href\\s*=\\s*['\"]?([^'\" >]+)[^>]*>(.*?)</a>");
        Matcher matcher = links.matcher(text);
        StringBuffer linked = new StringBuffer();
        while (matcher.find()) {
            String href = matcher.group(1);
            try { href = new URL(base, href).toString(); } catch (Exception ignored) { }
            String label = matcher.group(2).replaceAll("(?is)<[^>]+>", " ");
            matcher.appendReplacement(linked, Matcher.quoteReplacement(label + " (" + href + ")"));
        }
        matcher.appendTail(linked);
        text = linked.toString()
                .replaceAll("(?i)<br\\s*/?>", "\n")
                .replaceAll("(?i)</(p|div|h[1-6]|li|tr)>", "\n")
                .replaceAll("(?i)<li[^>]*>", "* ")
                .replaceAll("(?is)<[^>]+>", " ")
                .replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", "\"").replace("&#39;", "'");
        return text.replaceAll("[ \\t\\x0B\\f\\r]+", " ")
                .replaceAll(" *\\n *", "\n").replaceAll("\\n{3,}", "\n\n").trim();
    }

    private void goBack() {
        if (mHistory.size() <= 1) return;
        mHistory.remove(mHistory.size() - 1);
        load(mHistory.get(mHistory.size() - 1), false);
        mBack.setEnabled(mHistory.size() > 1);
    }

    @Override
    public void onBackPressed() {
        if (mHistory.size() > 1) goBack(); else super.onBackPressed();
    }
}
