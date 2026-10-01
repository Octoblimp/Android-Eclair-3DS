#!/usr/bin/env python3
"""Make system_server's "start a worker thread and wait for it" sites fail
loudly instead of hanging forever.

Four services in frameworks/base/services follow the identical pattern:

    Worker thr = new Worker();
    thr.start();
    synchronized (thr) {
        while (thr.mService == null) {   // or !thr.mRunning / !mInitComplete
            try { thr.wait(); } catch (InterruptedException e) { }
        }
    }

    // ... and in the worker:
    public void run() {
        Looper.prepare();
        Foo f = new Foo(...);            // <-- if THIS throws
        synchronized (this) {
            mService = f;                //     these two lines never run
            notifyAll();
        }
        Looper.loop();
    }

If the construction throws, the worker thread dies without ever publishing a
result and without notifying, so the *caller* -- ServerThread, i.e. the whole
of system_server's boot -- blocks in wait() forever. Nothing throws out of the
caller, so the try/catch (Throwable) blocks SystemServer.java wraps these calls
in cannot help: the failure mode is a hang, not an exception.

On a shipping device this never fires, because none of these constructors are
expected to fail. On this port they are: there is no compositor yet, so
WindowManagerService's constructor reaches android.view.Surface natives that
were never registered in gRegJNI[] and throws UnsatisfiedLinkError. The result
was a permanently wedged system_server on every boot that got that far, which
is easy to mistake for -- and was previously investigated as -- a kernel-level
lockup.

This patch gives every one of the four an explicit "done" flag that is set on
both paths plus a recorded Throwable, so the caller always wakes up and either
gets a service or a real exception. It is idempotent: run it as many times as
you like.

  WindowManagerService.WMThread       -> handled directly in the .java file
                                         (see the comment there), not here
  WindowManagerService.PolicyThread   -> mPolicy.init() may throw
  ActivityManagerService.AThread      -> new ActivityManagerService() may throw
  PowerManagerService.mHandlerThread  -> initInThread() may throw
  ConnectivityService.ConnectivityThread -> new ConnectivityService() may throw
"""
from a3ds_paths import A3DS_ROOT
import sys

BASE = (f"{A3DS_ROOT}/third_party/frameworks/base/services/java/"
        "com/android/server/")

# (path, description, [(old, new), ...])
PATCHES = []

# --------------------------------------------------------------------------
# 1. WindowManagerService.PolicyThread -- mPolicy.init() is PhoneWindowManager
#    bring-up; it touches the status bar, the display and the power manager.
# --------------------------------------------------------------------------
PATCHES.append((
    "WindowManagerService.java",
    "PolicyThread: publish a verdict even when mPolicy.init() throws",
    [
        (
            """        private final PowerManagerService mPM;
        boolean mRunning = false;
""",
            """        private final PowerManagerService mPM;
        boolean mRunning = false;
        // Android3DS: set on both the success and failure paths so the
        // constructor's wait() below can never block forever. mFailure is
        // non-null exactly when init() threw.
        boolean mDone = false;
        Throwable mFailure;
""",
        ),
        (
            """            android.os.Process.setThreadPriority(
                    android.os.Process.THREAD_PRIORITY_FOREGROUND);
            mPolicy.init(mContext, mService, mPM);

            synchronized (this) {
                mRunning = true;
                notifyAll();
            }

            Looper.loop();
        }
    }
""",
            """            android.os.Process.setThreadPriority(
                    android.os.Process.THREAD_PRIORITY_FOREGROUND);

            Throwable failure = null;
            try {
                mPolicy.init(mContext, mService, mPM);
            } catch (Throwable e) {
                // Throwable, not Exception: the realistic failure on this port
                // is UnsatisfiedLinkError from an unregistered native.
                failure = e;
            }

            synchronized (this) {
                mRunning = (failure == null);
                mFailure = failure;
                mDone = true;
                notifyAll();
            }

            if (failure != null) {
                // Nothing will ever post to this Looper; don't park a thread
                // on it forever.
                return;
            }

            Looper.loop();
        }
    }
""",
        ),
        (
            """        synchronized (thr) {
            while (!thr.mRunning) {
                try {
                    thr.wait();
                } catch (InterruptedException e) {
                }
            }
        }

        mInputThread.start();
""",
            """        synchronized (thr) {
            while (!thr.mDone) {
                try {
                    thr.wait();
                } catch (InterruptedException e) {
                }
            }
        }
        if (thr.mFailure != null) {
            // Surface as an exception out of this constructor, which
            // WMThread.run() catches -- rather than leaving the caller
            // blocked in wait() for the rest of the boot.
            throw new RuntimeException("WindowManagerPolicy init failed",
                    thr.mFailure);
        }

        mInputThread.start();
""",
        ),
    ],
))

# --------------------------------------------------------------------------
# 2. ActivityManagerService.AThread
# --------------------------------------------------------------------------
PATCHES.append((
    "am/ActivityManagerService.java",
    "AThread: publish a verdict even when the constructor throws",
    [
        (
            """    static class AThread extends Thread {
        ActivityManagerService mService;
        boolean mReady = false;
""",
            """    static class AThread extends Thread {
        ActivityManagerService mService;
        boolean mReady = false;
        // Android3DS: see scripts/patch_serverthread_hangs.py -- without
        // these, a throwing constructor leaves main() blocked forever.
        boolean mDone = false;
        Throwable mFailure;
""",
        ),
        (
            """            ActivityManagerService m = new ActivityManagerService();

            synchronized (this) {
                mService = m;
                notifyAll();
            }
""",
            """            ActivityManagerService m = null;
            Throwable failure = null;
            try {
                m = new ActivityManagerService();
            } catch (Throwable e) {
                failure = e;
            }

            synchronized (this) {
                mService = m;
                mFailure = failure;
                mDone = true;
                notifyAll();
            }

            if (m == null) {
                return;
            }
""",
        ),
        (
            """        synchronized (thr) {
            while (thr.mService == null) {
                try {
                    thr.wait();
                } catch (InterruptedException e) {
                }
            }
        }

        ActivityManagerService m = thr.mService;
""",
            """        synchronized (thr) {
            while (!thr.mDone) {
                try {
                    thr.wait();
                } catch (InterruptedException e) {
                }
            }
        }
        if (thr.mFailure != null) {
            throw new RuntimeException("ActivityManagerService init failed",
                    thr.mFailure);
        }

        ActivityManagerService m = thr.mService;
""",
        ),
    ],
))

# --------------------------------------------------------------------------
# 3. PowerManagerService.init() / initInThread()
# --------------------------------------------------------------------------
PATCHES.append((
    "PowerManagerService.java",
    "mHandlerThread: publish a verdict even when initInThread() throws",
    [
        (
            """                initInThread();
            }
        };
        mHandlerThread.start();
        
        synchronized (mHandlerThread) {
            while (!mInitComplete) {
                try {
                    mHandlerThread.wait();
                } catch (InterruptedException e) {
                    // Ignore
                }
            }
        }
    }
""",
            """                // Android3DS: initInThread() ends by setting mInitComplete
                // and notifying. If it throws before it gets there, nothing
                // ever notifies and the caller below waits forever. Record
                // the failure, always report completion, and rethrow on the
                // caller's thread where it can actually be handled.
                try {
                    initInThread();
                } catch (Throwable e) {
                    synchronized (this) {
                        mInitFailure = e;
                        mInitComplete = true;
                        notifyAll();
                    }
                }
            }
        };
        mHandlerThread.start();

        synchronized (mHandlerThread) {
            while (!mInitComplete) {
                try {
                    mHandlerThread.wait();
                } catch (InterruptedException e) {
                    // Ignore
                }
            }
        }
        if (mInitFailure != null) {
            throw new RuntimeException("PowerManagerService init failed",
                    mInitFailure);
        }
    }

    /** Android3DS: non-null if initInThread() threw. */
    private volatile Throwable mInitFailure;
""",
        ),
    ],
))

# --------------------------------------------------------------------------
# 4. ConnectivityService.ConnectivityThread
# --------------------------------------------------------------------------
PATCHES.append((
    "ConnectivityService.java",
    "ConnectivityThread: publish a verdict even when the constructor throws",
    [
        (
            """            Looper.prepare();
            synchronized (this) {
                sServiceInstance = new ConnectivityService(mContext);
                notifyAll();
            }
            Looper.loop();
        }
""",
            """            Looper.prepare();
            // Android3DS: a throwing constructor used to leave
            // getServiceInstance() blocked forever -- see
            // scripts/patch_serverthread_hangs.py.
            Throwable failure = null;
            try {
                sServiceInstance = new ConnectivityService(mContext);
            } catch (Throwable e) {
                failure = e;
            }
            synchronized (this) {
                sFailure = failure;
                sDone = true;
                notifyAll();
            }
            if (failure != null) {
                return;
            }
            Looper.loop();
        }

        private static volatile boolean sDone;
        private static volatile Throwable sFailure;
""",
        ),
        (
            """            synchronized (thread) {
                while (sServiceInstance == null) {
                    try {
                        // Wait until sServiceInstance has been initialized.
                        thread.wait();
                    } catch (InterruptedException ignore) {
                        Log.e(TAG,
                            "Unexpected InterruptedException while waiting"+
                            " for ConnectivityService thread");
                    }
                }
            }

            return sServiceInstance;
""",
            """            synchronized (thread) {
                while (!sDone) {
                    try {
                        // Wait until sServiceInstance has been initialized.
                        thread.wait();
                    } catch (InterruptedException ignore) {
                        Log.e(TAG,
                            "Unexpected InterruptedException while waiting"+
                            " for ConnectivityService thread");
                    }
                }
            }
            if (sFailure != null) {
                throw new RuntimeException("ConnectivityService init failed",
                        sFailure);
            }

            return sServiceInstance;
""",
        ),
    ],
))


def main():
    rc = 0
    for rel, desc, edits in PATCHES:
        path = BASE + rel
        try:
            src = open(path).read()
        except IOError as e:
            print("MISSING %s: %s" % (rel, e))
            rc = 1
            continue

        changed = 0
        skipped = 0
        for old, new in edits:
            if new in src:
                skipped += 1
                continue
            if old not in src:
                print("FAIL %s: anchor not found:\n---\n%s\n---" % (rel, old[:200]))
                rc = 1
                continue
            src = src.replace(old, new, 1)
            changed += 1

        if changed:
            open(path, "w").write(src)
        print("%-42s %s (%d applied, %d already present)"
              % (rel, desc, changed, skipped))
    return rc


if __name__ == "__main__":
    sys.exit(main())
