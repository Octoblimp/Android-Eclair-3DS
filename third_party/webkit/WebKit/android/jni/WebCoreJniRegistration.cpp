/*
 * Copyright 2009, The Android Open Source Project
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *  * Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *  * Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
 * EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL APPLE COMPUTER, INC. OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 * PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 * OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/*  Static counterpart to WebCoreJniOnLoad.cpp.
 *
 *  Upstream shipped the engine as libwebcore.so, so the thirteen registrations
 *  below ran from JNI_OnLoad the moment WebViewCore's static initialiser called
 *  System.loadLibrary("webcore").  app_process here is statically linked and
 *  bionic dlopen() returns NULL from a static executable, so there is no load
 *  event and no JNI_OnLoad to hang them off.  AndroidRuntime::startReg() names
 *  this function in gRegJNI[] instead -- the same treatment the services/jni
 *  registrations got when libandroid_servers.so was retired.
 *
 *  This has to be its own translation unit rather than an extra entry point in
 *  WebCoreJniOnLoad.cpp.  That file's JNI_OnLoad is a second definition of the
 *  one in libjavacore.a(sql__sqlite_jni.o), so its object must never be pulled
 *  into the link; keeping the registration separate means the only member of
 *  libwebcore.a the linker reaches for it carries no JNI_OnLoad at all.
 */

#define LOG_TAG "webcoreglue"

#include "config.h"

#include "jni_utility.h"
#include <jni.h>
#include <stdlib.h>
#include <time.h>
#include <utils/Log.h>

namespace android {

extern int register_webframe(JNIEnv*);
extern int register_javabridge(JNIEnv*);
extern int register_resource_loader(JNIEnv*);
extern int register_webviewcore(JNIEnv*);
extern int register_webhistory(JNIEnv*);
extern int register_webicondatabase(JNIEnv*);
extern int register_websettings(JNIEnv*);
extern int register_webview(JNIEnv*);
extern int register_webcorejni(JNIEnv*);
#if ENABLE(DATABASE)
extern int register_webstorage(JNIEnv*);
#endif
extern int register_geolocation_permissions(JNIEnv*);
extern int register_mock_geolocation(JNIEnv*);
#if ENABLE(VIDEO)
extern int register_mediaplayer(JNIEnv*);
#endif

struct WebCoreRegistrationMethod {
    const char* name;
    int (*func)(JNIEnv*);
};

/*  Copied verbatim from gWebCoreRegMethods in WebCoreJniOnLoad.cpp, order
 *  included: the later entries cache field and method IDs the earlier ones
 *  install, so this table is as load-bearing as gRegJNI[] itself.
 */
static const WebCoreRegistrationMethod gWebCoreRegMethods[] = {
    { "JavaBridge", register_javabridge },
    { "WebFrame", register_webframe },
    { "WebCoreResourceLoader", register_resource_loader },
    { "WebCoreJni", register_webcorejni },
    { "WebViewCore", register_webviewcore },
    { "WebHistory", register_webhistory },
    { "WebIconDatabase", register_webicondatabase },
    { "WebSettings", register_websettings },
#if ENABLE(DATABASE)
    { "WebStorage", register_webstorage },
#endif
    { "WebView", register_webview },
    { "GeolocationPermissions", register_geolocation_permissions },
    { "MockGeolocation", register_mock_geolocation },
#if ENABLE(VIDEO)
    { "HTML5VideoViewProxy", register_mediaplayer },
#endif
};

int register_android_webkit_WebCore(JNIEnv* env)
{
    /*  JSC::Bindings::getJavaVM() is how every WebCore worker thread attaches
     *  itself; JNI_OnLoad used to be where the pointer was seeded, and nothing
     *  else in the engine seeds it.
     */
    JavaVM* vm = NULL;
    if (env->GetJavaVM(&vm) < 0 || vm == NULL) {
        LOGE("WebCore registration: GetJavaVM failed");
        return -1;
    }
    JSC::Bindings::setJavaVM(vm);

    const WebCoreRegistrationMethod* method = gWebCoreRegMethods;
    const WebCoreRegistrationMethod* end =
        method + sizeof(gWebCoreRegMethods) / sizeof(WebCoreRegistrationMethod);
    while (method < end) {
        if (method->func(env) < 0) {
            LOGE("%s registration failed!", method->name);
            return -1;
        }
        method++;
    }

    /*  rand() is used in FileSystemAndroid to name temporary files.  Seeding it
     *  in the zygote means every forked app inherits the same sequence, which
     *  was already true when this ran from JNI_OnLoad in the preloading zygote.
     */
    srand(time(NULL));
    return 0;
}

}  // namespace android
